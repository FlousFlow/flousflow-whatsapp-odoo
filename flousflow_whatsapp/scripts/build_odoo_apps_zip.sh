#!/usr/bin/env bash
set -euo pipefail

module_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
workspace_dir="$(dirname "$module_dir")"
release_dir="$workspace_dir/release"
archive="$release_dir/flousflow_whatsapp-19.0.1.6.5.zip"

python3 "$module_dir/scripts/validate_release.py"
mkdir -p "$release_dir"
rm -f "$archive"
cd "$workspace_dir"
zip -qr "$archive" flousflow_whatsapp \
  -x '*/__pycache__/*' '*.pyc' '*/.DS_Store' '*/.git/*'
unzip -tq "$archive"
echo "$archive"
