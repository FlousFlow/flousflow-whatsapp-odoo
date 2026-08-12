/** @odoo-module **/

// CRITICAL: On Chromium, MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")
// is FALSE and isTypeSupported("audio/mp4") is TRUE but Chromium muxes
// audio/mp4 as VIDEO (VP9) → silent files. So WebM/Opus must come BEFORE
// audio/mp4: it records real audio on Chrome/Edge/Firefox. audio/ogg is kept
// for Firefox-native recording, audio/mp4 only as a last-resort for Safari.
const RECORDER_MIME_TYPES = [
    "audio/webm;codecs=opus",
    "audio/ogg;codecs=opus",
    "audio/webm",
    "audio/mp4",
];

export function attachmentContentUrl(attachment) {
    const id = Array.isArray(attachment) ? Number(attachment[0]) : Number(attachment || 0);
    return id > 0 ? `/web/content/${id}?download=false` : "";
}

export function chooseRecorderMimeType(isTypeSupported) {
    return RECORDER_MIME_TYPES.find((mimetype) => isTypeSupported(mimetype)) || "";
}

export function audioFilename(mimetype, timestamp = Date.now()) {
    const normalized = String(mimetype || "").toLowerCase();
    const extension = normalized.includes("ogg") ? "ogg" : normalized.includes("mp4") ? "m4a" : "webm";
    return `voice-${timestamp}.${extension}`;
}

export function recordedAudioAttachment(blob, content, timestamp = Date.now()) {
    return {
        filename: audioFilename(blob.type, timestamp),
        mimetype: blob.type,
        content,
        voice_note: true,
    };
}
