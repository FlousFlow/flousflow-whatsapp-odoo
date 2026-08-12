import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../src/inbox/phone_format.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { formatConversationLabel, formatPhoneForDisplay, formatConversationName, formatConversationPhone } = await import(moduleUrl);

test("separates the Egyptian country calling code", () => {
    assert.equal(formatPhoneForDisplay("201223946194"), "(+20) 1223946194");
    assert.equal(formatPhoneForDisplay("+201018721607"), "(+20) 1018721607");
});

test("supports one and three digit country calling codes", () => {
    assert.equal(formatPhoneForDisplay("14155552671"), "(+1) 4155552671");
    assert.equal(formatPhoneForDisplay("971501234567"), "(+971) 501234567");
});

test("keeps a real customer name and formats numeric partner labels", () => {
    assert.equal(formatConversationLabel("Mohamed Gamal", null, "201223946194"), "Mohamed Gamal");
    assert.equal(formatConversationLabel(null, "WhatsApp Profile", "201223946194"), "WhatsApp Profile");
    assert.equal(formatConversationLabel("201223946194", null, "201223946194"), "(+20) 1223946194");
    assert.equal(formatConversationLabel(null, null, "201223946194"), "(+20) 1223946194");
});

test("does not invent formatting for invalid values", () => {
    assert.equal(formatPhoneForDisplay("status"), "status");
    assert.equal(formatPhoneForDisplay(""), "");
});

test("conversation name prefers a real name and phone stays separate", () => {
    assert.equal(formatConversationName("Mohamed Gamal", null, "201223946194"), "Mohamed Gamal");
    assert.equal(formatConversationName(null, "WhatsApp Profile", "201223946194"), "WhatsApp Profile");
    assert.equal(formatConversationName(null, null, "201223946194"), "(+20) 1223946194");
    assert.equal(formatConversationPhone("201223946194"), "(+20) 1223946194");
    assert.equal(formatConversationPhone("+201018721607"), "(+20) 1018721607");
    assert.equal(formatConversationPhone(""), "");
});
