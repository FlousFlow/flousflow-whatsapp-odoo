/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { formatConversationLabel, formatConversationName, formatConversationPhone } from "./phone_format";
import { attachmentContentUrl, chooseRecorderMimeType, recordedAudioAttachment } from "./audio";

const MAX_FILE_BYTES = 10 * 1024 * 1024;
const ALLOWED_FILE_TYPES = [
    "image/jpeg", "image/png", "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "audio/ogg", "audio/mpeg", "audio/mp4",
    "audio/webm",
];
const MAX_RECORDING_SECONDS = 5 * 60;

const EMOJIS = [
    "😀", "😂", "😊", "😍", "😘", "😎", "🤔", "😢", "😭", "😡",
    "👍", "👎", "👏", "🙏", "💪", "🤝", "🙌", "👌", "✌️", "🤗",
    "❤️", "💙", "✅", "❌", "⭐", "🔥", "🎉", "💰", "📞", "📩",
];

export class WhatsappInbox extends Component {
    static template = "flousflow_whatsapp.WhatsappInbox";
    static props = { action: { type: Object, optional: true }, "*": true };

    setup() {
        this.inbox = useService("flousflowWhatsappInbox");
        this.notification = useService("notification");
        this.action = useService("action");
        this.busService = useService("bus_service");
        this.fileInput = useRef("fileInput");
        this.state = useState({
            loading: true,
            conversations: [],
            selected: null,
            messages: [],
            lock: { locked: false, owned_by_me: false },
            draft: "",
            attachment: null,
            sending: false,
            filter: "all",
            search: "",
            numbers: [],
            numberFilter: "all",
            showEmoji: false,
            documentActions: [],
            recording: false,
            recordingSeconds: 0,
            recordingPreviewUrl: "",
            recordingLevel: 0,
            externalReplyDetected: false,
        });
        this.heartbeatTimer = null;
        this.refreshTimer = null;
        this.fallbackTimer = null;
        this.mediaRecorder = null;
        this.recordingStream = null;
        this.recordingTimer = null;
        this.levelTimer = null;
        this.audioAnalyser = null;
        this.audioData = null;
        this.maxRecordingLevel = 0;
        this.cancelCurrentRecording = false;
        this.onRealtimeMessage = (payload) => this.handleRealtimeMessage(payload);
        this.busService.subscribe("flousflow_whatsapp.message", this.onRealtimeMessage);
        onWillStart(async () => {
            await Promise.all([this.loadNumbers(), this.loadConversations()]);
            this.fallbackTimer = setInterval(() => this.scheduleRealtimeRefresh(), 5000);
        });
        onWillUnmount(() => {
            this.busService.unsubscribe("flousflow_whatsapp.message", this.onRealtimeMessage);
            if (this.refreshTimer) clearTimeout(this.refreshTimer);
            if (this.fallbackTimer) clearInterval(this.fallbackTimer);
            this.cancelRecording();
            this.revokeRecordingPreview();
            this.cleanupLock();
        });
    }

    get filteredConversations() {
        let items = this.state.conversations;
        if (this.state.numberFilter !== "all") {
            items = items.filter((item) => Number(item.number_id?.[0]) === this.state.numberFilter);
        }
        if (this.state.filter === "unassigned") {
            items = items.filter((item) => !item.assigned_user_id);
        } else if (this.state.filter === "breached") {
            items = items.filter((item) => item.sla_state === "breached");
        }
        const term = this.state.search.trim().toLowerCase();
        if (term) {
            items = items.filter((item) => {
                const label = this.conversationLabel(item).toLowerCase();
                const phone = String(item.customer_phone_normalized || "").toLowerCase();
                const name = String(item.name || "").toLowerCase();
                return label.includes(term) || phone.includes(term) || name.includes(term);
            });
        }
        return items;
    }

    get typingForSelected() {
        return Boolean(this.state.selected?.customer_typing);
    }

    get canSend() {
        // Mirror the production behaviour: sending requires owning the lock.
        return Boolean(
            this.state.selected && this.state.lock?.owned_by_me &&
            (this.state.draft.trim() || this.state.attachment) &&
            !this.state.sending && !this.state.recording
        );
    }

    conversationLabel(conversation) {
        return formatConversationLabel(
            conversation?.partner_id?.[1],
            conversation?.customer_display_name,
            conversation?.customer_phone_normalized,
        );
    }

    conversationName(conversation) {
        return formatConversationName(
            conversation?.partner_id?.[1],
            conversation?.customer_display_name,
            conversation?.customer_phone_normalized,
        );
    }

    conversationPhone(conversation) {
        return formatConversationPhone(conversation?.customer_phone_normalized);
    }

    attachmentUrl(message) {
        return attachmentContentUrl(message?.attachment_id);
    }

    attachmentDownloadUrl(message) {
        const url = this.attachmentUrl(message);
        return url ? url.replace("download=false", "download=true") : "";
    }

    formatFileSize(bytes) {
        const size = Number(bytes || 0);
        if (!size) return "";
        if (size < 1024 * 1024) return `${Math.ceil(size / 1024)} KB`;
        return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    }

    receiptIcon(message) {
        if (message.direction !== "outbound") return "";
        return { queued: "clock-o", sending: "clock-o", sent: "check", delivered: "check",
            read: "check", failed: "exclamation-triangle" }[message.state] || "";
    }

    receiptTitle(message) {
        return { queued: "Queued", sending: "Sending", sent: "Sent", delivered: "Delivered",
            read: "Read", failed: "Failed" }[message.state] || message.state;
    }

    get recordingTime() {
        const minutes = Math.floor(this.state.recordingSeconds / 60);
        const seconds = String(this.state.recordingSeconds % 60).padStart(2, "0");
        return `${minutes}:${seconds}`;
    }

    scheduleRealtimeRefresh(payload = null) {
        if (payload?.conversation_id && this.state.selected?.id &&
            payload.conversation_id !== this.state.selected.id) {
            this.refreshConversationList();
            return;
        }
        if (this.refreshTimer) {
            clearTimeout(this.refreshTimer);
        }
        this.refreshTimer = setTimeout(() => {
            this.refreshTimer = null;
            void this.refreshWorkspace();
        }, 100);
    }

    handleRealtimeMessage(payload) {
        const isSelectedExternalReply = Boolean(
            payload?.conversation_id === this.state.selected?.id &&
            payload?.direction === "outbound" &&
            payload?.source === "whatsapp_device"
        );
        if (isSelectedExternalReply && this.state.lock?.owned_by_me) {
            this.stopHeartbeat();
            this.state.lock = { ...this.state.lock, locked: false, owned_by_me: false };
            this.state.externalReplyDetected = true;
            this.notification.add(
                _t("A reply was sent from the WhatsApp phone. Review it before continuing; your draft was preserved."),
                { type: "warning", sticky: true },
            );
        }
        if (payload?.event === "typing" && payload?.conversation_id) {
            const conversation = this.state.conversations.find(
                (item) => item.id === payload.conversation_id
            );
            if (conversation) {
                conversation.customer_typing = Boolean(payload.typing);
            }
            if (this.state.selected?.id === payload.conversation_id) {
                this.state.selected.customer_typing = Boolean(payload.typing);
            }
            return;
        }
        if (payload?.event === "seen" && payload?.conversation_id) {
            const conversation = this.state.conversations.find(
                (item) => item.id === payload.conversation_id
            );
            if (conversation) {
                conversation.unread_count = 0;
            }
            return;
        }
        if (payload?.event === "closed" && payload?.conversation_id) {
            this.state.conversations = this.state.conversations.filter(
                (item) => item.id !== payload.conversation_id
            );
            if (this.state.selected?.id === payload.conversation_id) {
                this.state.selected = null;
                this.state.messages = [];
                this.state.lock = { locked: false, owned_by_me: false };
            }
            return;
        }
        this.scheduleRealtimeRefresh(payload);
    }

    async refreshConversationList() {
        try {
            this.state.conversations = await this.inbox.loadConversations();
        } catch {
            // The fallback timer or next bus event retries without interrupting the agent.
        }
    }

    async refreshWorkspace() {
        try {
            const conversations = await this.inbox.loadConversations();
            this.state.conversations = conversations;
            if (this.state.selected?.id) {
                const selected = conversations.find((item) => item.id === this.state.selected.id);
                if (selected) {
                    this.state.selected = selected;
                    [this.state.messages, this.state.lock] = await Promise.all([
                        this.inbox.loadMessages(selected.id),
                        this.inbox.getLockInfo(selected.id),
                    ]);
                }
            }
        } catch {
            // Keep the current screen usable during a transient connection interruption.
        }
    }

    async openLead() {
        if (!this.state.selected?.id) return;
        try {
            const action = await this.inbox.openLead(this.state.selected.id);
            await this.action.doAction(action);
        } catch (error) {
            const message = error?.data?.message || error?.message ||
                _t("The CRM lead could not be opened.");
            this.notification.add(message, { type: "danger" });
        }
    }

    async openDocumentWizard(providerKey) {
        if (!this.state.selected?.id) return;
        try {
            const action = await this.inbox.openDocumentWizard(
                this.state.selected.id, providerKey
            );
            await this.action.doAction(action);
        } catch {
            this.notification.add(_t("The document could not be prepared for WhatsApp."), {
                type: "danger",
            });
        }
    }

    async loadNumbers() {
        try {
            this.state.numbers = await this.inbox.loadNumbers();
            // Drop a number filter that no longer matches (e.g. number disabled).
            if (
                this.state.numberFilter !== "all" &&
                !this.state.numbers.some((n) => Number(n.id) === this.state.numberFilter)
            ) {
                this.state.numberFilter = "all";
            }
        } catch {
            this.state.numbers = [];
            this.state.numberFilter = "all";
        }
    }

    async loadConversations() {
        this.state.loading = true;
        try {
            this.state.conversations = await this.inbox.loadConversations();
            if (!this.state.selected && this.state.conversations.length) {
                await this.selectConversation(this.state.conversations[0]);
            }
        } catch {
            this.notification.add(_t("Could not load WhatsApp conversations."), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async selectConversation(conversation) {
        if (!conversation?.id) {
            return;
        }
        if (this.state.selected?.id === conversation.id) {
            return;
        }
        await this.cleanupLock();
        this.cancelRecording();
        this.revokeRecordingPreview();
        this.state.selected = conversation;
        this.state.messages = [];
        this.state.lock = { locked: false, owned_by_me: false };
        this.state.attachment = null;
        this.state.documentActions = [];
        this.state.externalReplyDetected = false;
        try {
            [this.state.messages, this.state.documentActions] = await Promise.all([
                this.inbox.loadMessages(conversation.id),
                this.inbox.loadDocumentActions(conversation.id),
            ]);
            try {
                await this.inbox.acquireLock(conversation.id);
            } catch {
                // Read access is intentional when another employee owns the lock.
            }
            this.state.lock = await this.inbox.getLockInfo(conversation.id);
            if (this.state.lock.owned_by_me) {
                this.startHeartbeat();
            }
            // Clear the unread badge once the conversation is opened.
            if (conversation.unread_count) {
                conversation.unread_count = 0;
                this.inbox.markSeen(conversation.id).catch(() => {});
            }
        } catch {
            this.notification.add(_t("Could not open this WhatsApp conversation."), { type: "danger" });
        }
    }

    async claimConversation() {
        if (!this.state.selected?.id) {
            return;
        }
        try {
            this.state.lock = await this.inbox.claimConversation(this.state.selected.id);
            this.state.selected.assigned_user_id = [
                this.state.lock.assigned_user_id,
                this.state.lock.assigned_user_name,
            ];
            this.startHeartbeat();
        } catch {
            this.state.lock = await this.inbox.getLockInfo(this.state.selected.id);
            this.notification.add(_t("This conversation could not be assigned to you."), {
                type: "warning",
            });
        }
    }

    async resumeAfterExternalReply() {
        if (!this.state.selected?.id) return;
        try {
            await this.inbox.acquireLock(this.state.selected.id);
            this.state.lock = await this.inbox.getLockInfo(this.state.selected.id);
            this.state.externalReplyDetected = false;
            this.startHeartbeat();
        } catch (error) {
            const reason = error?.data?.message || error?.message ||
                _t("The conversation could not be reopened for replies.");
            this.notification.add(reason, { type: "warning" });
        }
    }

    startHeartbeat() {
        this.stopHeartbeat();
        this.heartbeatTimer = setInterval(async () => {
            if (!this.state.selected?.id) {
                this.stopHeartbeat();
                return;
            }
            try {
                await this.inbox.heartbeat(this.state.selected.id);
                this.state.lock = await this.inbox.getLockInfo(this.state.selected.id);
            } catch {
                this.stopHeartbeat();
                this.state.lock = await this.inbox.getLockInfo(this.state.selected.id);
            }
        }, 30000);
    }

    stopHeartbeat() {
        if (this.heartbeatTimer) {
            clearInterval(this.heartbeatTimer);
            this.heartbeatTimer = null;
        }
    }

    async cleanupLock() {
        this.stopHeartbeat();
        if (this.state?.selected && this.state.lock?.owned_by_me) {
            try {
                await this.inbox.releaseLock(this.state.selected.id);
            } catch {
                // Lease expiry remains the crash-safe fallback.
            }
        }
    }

    async onFileChange(event) {
        const file = event.target.files?.[0];
        event.target.value = "";
        if (!file) {
            return;
        }
        if (file.type.startsWith("video/") || !ALLOWED_FILE_TYPES.includes(file.type)) {
            this.notification.add(_t("Video or unsupported files cannot be sent."), { type: "warning" });
            return;
        }
        if (file.size > MAX_FILE_BYTES) {
            this.notification.add(_t("The file exceeds the 10 MB limit."), { type: "warning" });
            return;
        }
        this.state.attachment = {
            filename: file.name,
            mimetype: file.type,
            content: await this.fileToBase64(file),
            voice_note: false,
        };
    }

    fileToBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    removeAttachment() {
        this.state.attachment = null;
        this.revokeRecordingPreview();
    }

    async startRecording() {
        // Recording (like sending) requires owning the conversation lock —
        // this mirrors the production module and avoids surprising states.
        if (!this.state.lock?.owned_by_me || this.state.recording || this.state.sending) return;
        if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
            this.notification.add(_t("Audio recording is not supported by this browser."), {
                type: "warning",
            });
            return;
        }
        const mimetype = chooseRecorderMimeType((candidate) => MediaRecorder.isTypeSupported(candidate));
        if (!mimetype) {
            this.notification.add(_t("No supported audio recording format is available."), {
                type: "warning",
            });
            return;
        }
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
            const recorder = new MediaRecorder(stream, { mimeType: mimetype, audioBitsPerSecond: 64000 });
            const chunks = [];
            this.cancelCurrentRecording = false;
            this.recordingStream = stream;
            this.mediaRecorder = recorder;
            this.maxRecordingLevel = 0;
            this.state.recordingLevel = 0;
            // Live input-level meter: exposes whether the microphone actually
            // captures sound (silent microphones produce silent recordings).
            try {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                if (AudioCtx && typeof AudioCtx !== "undefined") {
                    this.audioContext = new AudioCtx();
                    this.audioAnalyser = this.audioContext.createAnalyser();
                    this.audioAnalyser.fftSize = 256;
                    this.audioContext.createMediaStreamSource(stream).connect(this.audioAnalyser);
                    this.audioData = new Uint8Array(this.audioAnalyser.frequencyBinCount);
                }
            } catch (_) {
                // Metering is best-effort; recording still proceeds without it.
            }
            recorder.addEventListener("dataavailable", (event) => {
                if (event.data?.size) chunks.push(event.data);
            });
            recorder.addEventListener("stop", async () => {
                this.stopRecordingTimer();
                // Do NOT close the AudioContext here: it shares the same mic
                // stream as the MediaRecorder, and closing it before we build
                // the Blob can truncate/flush the captured data (empty files).
                if (this.cancelCurrentRecording) {
                    this.stopLevelMeter();
                    this.stopRecordingTracks();
                    this.state.recording = false;
                    return;
                }
                const blob = new Blob(chunks, { type: recorder.mimeType || mimetype });
                // Stop the mic tracks and close the level meter only after all
                // buffered data has been collected into the blob.
                this.stopRecordingTracks();
                this.stopLevelMeter();
                this.state.recording = false;
                this.state.recordingLevel = 0;
                if (!blob.size) {
                    this.notification.add(_t("The voice recording was empty."), { type: "warning" });
                    return;
                }
                if (blob.size > MAX_FILE_BYTES) {
                    this.notification.add(_t("The recording exceeds the 10 MB limit."), { type: "warning" });
                    return;
                }
                // Best-effort mic sanity check. The server reference that works
                // records regardless of the measured input level, so a low level
                // must NOT block sending (the analyser can under-report even
                // with a perfectly good mic). Only warn.
                if (this.maxRecordingLevel < 0.01) {
                    this.notification.add(
                        _t("No sound was detected on the microphone. The recording may be silent."),
                        { type: "warning" },
                    );
                }
                this.revokeRecordingPreview();
                this.state.recordingPreviewUrl = URL.createObjectURL(blob);
                this.state.attachment = recordedAudioAttachment(
                    blob, await this.fileToBase64(blob)
                );
            }, { once: true });
            recorder.start(1000);
            this.state.recording = true;
            this.state.recordingSeconds = 0;
            this.recordingTimer = setInterval(() => {
                this.state.recordingSeconds += 1;
                if (this.state.recordingSeconds >= MAX_RECORDING_SECONDS) this.stopRecording();
            }, 1000);
            this.levelTimer = setInterval(() => this.sampleRecordingLevel(), 120);
        } catch (error) {
            this.cleanupRecording();
            const denied = error?.name === "NotAllowedError" || error?.name === "SecurityError";
            this.notification.add(
                denied ? _t("Microphone permission was denied.") : _t("The microphone could not be started."),
                { type: "danger" },
            );
        }
    }

    sampleRecordingLevel() {
        if (!this.audioAnalyser || !this.audioData) return;
        try {
            this.audioAnalyser.getByteFrequencyData(this.audioData);
            // Average the frequency magnitudes → a 0..1-ish loudness estimate.
            let sum = 0;
            for (let i = 0; i < this.audioData.length; i += 1) sum += this.audioData[i];
            const level = sum / this.audioData.length / 255;
            this.state.recordingLevel = level;
            if (level > this.maxRecordingLevel) this.maxRecordingLevel = level;
        } catch (_) {
            // Ignore transient analyser errors.
        }
    }

    stopLevelMeter() {
        if (this.levelTimer) {
            clearInterval(this.levelTimer);
            this.levelTimer = null;
        }
        if (this.audioContext?.state !== "closed") {
            try {
                this.audioContext?.close();
            } catch (_) {
                // best-effort cleanup
            }
        }
        this.audioAnalyser = null;
        this.audioData = null;
    }

    toggleRecording() {
        if (this.state.recording) {
            this.stopRecording();
            return;
        }
        // If a "reply sent from the phone" review banner is showing, acquire
        // the lock again before recording so the voice note can be sent right
        // away (recording never overwrites the phone's reply).
        const resume = this.state.externalReplyDetected
            ? this.resumeAfterExternalReply()
            : Promise.resolve();
        void resume.then(() => this.startRecording());
    }

    stopRecording() {
        if (this.mediaRecorder?.state === "recording") {
            // Flush any buffered audio before stopping so the final chunk is
            // never lost (prevents truncated/empty recordings).
            if (typeof this.mediaRecorder.requestData === "function") {
                try {
                    this.mediaRecorder.requestData();
                } catch (_) {
                    // requestData can throw if the recorder is already stopping.
                }
            }
            this.mediaRecorder.stop();
        }
    }

    cancelRecording() {
        if (!this.state.recording && !this.mediaRecorder) return;
        this.cancelCurrentRecording = true;
        if (this.mediaRecorder?.state === "recording") this.mediaRecorder.stop();
        this.cleanupRecording();
    }

    cleanupRecording() {
        this.stopRecordingTimer();
        this.stopLevelMeter();
        this.stopRecordingTracks();
        this.mediaRecorder = null;
        if (this.state) {
            this.state.recording = false;
            this.state.recordingSeconds = 0;
            this.state.recordingLevel = 0;
        }
    }

    stopRecordingTimer() {
        if (this.recordingTimer) clearInterval(this.recordingTimer);
        this.recordingTimer = null;
    }

    stopRecordingTracks() {
        for (const track of this.recordingStream?.getTracks?.() || []) track.stop();
        this.recordingStream = null;
    }

    revokeRecordingPreview() {
        if (this.state?.recordingPreviewUrl) URL.revokeObjectURL(this.state.recordingPreviewUrl);
        if (this.state) this.state.recordingPreviewUrl = "";
    }

    async sendMessage() {
        if (!this.canSend) {
            return;
        }
        // If a "reply sent from the phone" review banner is showing, acquire
        // the lock again before sending so the message (incl. a voice note)
        // is not rejected by the backend lock check.
        if (this.state.externalReplyDetected) {
            try {
                await this.resumeAfterExternalReply();
            } catch {
                return;
            }
            if (!this.state.lock?.owned_by_me) {
                this.notification.add(
                    _t("This conversation is being handled by another agent."),
                    { type: "warning" },
                );
                return;
            }
        }
        const payload = {
            conversation_id: this.state.selected.id,
            client_idempotency_key: crypto.randomUUID(),
            body: this.state.draft.trim(),
            message_type: this.state.attachment
                ? (this.state.attachment.mimetype.startsWith("image/") ? "image" :
                    this.state.attachment.mimetype.startsWith("audio/") ? "audio" : "document")
                : "text",
            ...this.state.attachment,
        };
        this.state.sending = true;
        try {
            await this.inbox.send(payload);
            this.state.draft = "";
            this.state.attachment = null;
            this.revokeRecordingPreview();
            this.state.messages = await this.inbox.loadMessages(this.state.selected.id);
        } catch (error) {
            const reason = error?.data?.message || error?.message ||
                _t("Message was not queued. Your draft was preserved.");
            this.notification.add(reason, {
                type: "danger",
            });
        } finally {
            this.state.sending = false;
        }
    }

    get emojiList() {
        return EMOJIS;
    }

    toggleEmoji() {
        this.state.showEmoji = !this.state.showEmoji;
    }

    insertEmoji(emoji) {
        this.state.draft = `${this.state.draft}${emoji}`;
        this.state.showEmoji = false;
    }

    async closeConversation() {
        if (!this.state.selected?.id) return;
        try {
            await this.inbox.closeConversation(this.state.selected.id);
            this.state.conversations = this.state.conversations.filter(
                (item) => item.id !== this.state.selected.id
            );
            this.state.selected = null;
            this.state.messages = [];
            this.state.lock = { locked: false, owned_by_me: false };
            this.stopHeartbeat();
        } catch (error) {
            const reason = error?.data?.message || error?.message ||
                _t("This conversation could not be closed.");
            this.notification.add(reason, { type: "danger" });
        }
    }
}

registry.category("actions").add("flousflow_whatsapp.inbox", WhatsappInbox);
