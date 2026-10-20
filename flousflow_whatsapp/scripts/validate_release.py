#!/usr/bin/env python3
"""Fail fast on common Odoo Apps packaging mistakes."""

from __future__ import annotations

import ast
import compileall
import csv
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "__init__.py", "__manifest__.py", "README.md", "CHANGELOG.md",
    "CONNECTOR_COMPATIBILITY.md", "LICENSE", "static/description/icon.png",
    "static/description/index.html", "security/ir.access.csv",
]
FORBIDDEN_PARTS = {".git", "node_modules"}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


for relative in REQUIRED:
    if not (ROOT / relative).is_file():
        fail(f"missing required release file: {relative}")

manifest = ast.literal_eval((ROOT / "__manifest__.py").read_text(encoding="utf-8"))
if not manifest.get("installable") or not manifest.get("application"):
    fail("manifest must be installable and application=True")
if manifest.get("license") not in {"LGPL-3", "OPL-1", "OEEL-1"}:
    fail("manifest license is missing or unsupported")
if not str(manifest.get("version", "")).startswith("20.0."):
    fail("manifest version must target Odoo 20")

with (ROOT / "security/ir.access.csv").open(encoding="utf-8", newline="") as stream:
    access_rows = list(csv.DictReader(stream))
expected_access_columns = ["id", "name", "model_id", "group_id/id", "operation", "domain"]
if not access_rows or list(access_rows[0]) != expected_access_columns:
    fail("security/ir.access.csv must use the Odoo 20 access schema")
access_ids = [row["id"] for row in access_rows]
if len(access_ids) != len(set(access_ids)):
    fail("security/ir.access.csv contains duplicate record IDs")
for row in access_rows:
    if not row["model_id"]:
        fail(f"access row {row['id']} is missing a model")
    if not row["group_id/id"] and not row["domain"]:
        fail(f"global access row {row['id']} must define a restricting domain")
    if not row["operation"] or set(row["operation"]) - set("crud"):
        fail(f"access row {row['id']} has an invalid operation set")

security_xml = ROOT / "security/security.xml"
if security_xml.is_file() and 'model="ir.rule"' in security_xml.read_text(encoding="utf-8"):
    fail("Odoo 20 security must not define legacy ir.rule records")

for path in ROOT.rglob("*"):
    if any(part in FORBIDDEN_PARTS for part in path.parts):
        fail(f"forbidden release artifact: {path.relative_to(ROOT)}")
    if path.is_file() and path.suffix == ".xml":
        try:
            ET.parse(path)
        except ET.ParseError as exc:
            fail(f"invalid XML {path.relative_to(ROOT)}: {exc}")

if not compileall.compile_dir(ROOT, quiet=1, force=True):
    fail("Python compilation failed")

print(f"Release validation passed: {manifest['name']} {manifest['version']}")
