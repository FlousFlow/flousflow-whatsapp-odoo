import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
    attachmentContentUrl,
    chooseRecorderMimeType,
    recordedAudioAttachment,
} from "../src/inbox/audio.js";

test("builds an authenticated inline attachment URL", () => {
    assert.equal(attachmentContentUrl([1157, "voice.ogg"]), "/web/content/1157?download=false");
    assert.equal(attachmentContentUrl(false), "");
});

test("selects a supported audio recorder format without accepting video", () => {
    const supported = new Set(["audio/webm;codecs=opus", "video/webm"]);
    assert.equal(
        chooseRecorderMimeType((mimetype) => supported.has(mimetype)),
        "audio/webm;codecs=opus",
    );
    assert.equal(chooseRecorderMimeType(() => false), "");
});

test("keeps responsive audio sizing compatible with Odoo's SCSS compiler", async () => {
    const scss = await readFile(new URL("../src/inbox/inbox.scss", import.meta.url), "utf8");
    assert.doesNotMatch(scss, /min\([^)]*(?:px[^)]*vw|vw[^)]*px)/i);
    assert.match(scss, /\.o_ff_wa_audio\s*\{[^}]*width:\s*65vw;[^}]*max-width:\s*320px;/s);
});

test("turns a completed browser recording into a native voice-note attachment", () => {
    const attachment = recordedAudioAttachment(
        { type: "audio/webm;codecs=opus", size: 2048 },
        "base64-audio",
        12345,
    );
    assert.deepEqual(attachment, {
        filename: "voice-12345.webm",
        mimetype: "audio/webm;codecs=opus",
        content: "base64-audio",
        voice_note: true,
    });
});
