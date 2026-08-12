/** @odoo-module **/

import { registry } from "@web/core/registry";

export const whatsappInboxService = {
    dependencies: ["orm"],
    start(env, { orm }) {
        return {
            loadNumbers() {
                return orm.searchRead(
                    "flousflow.whatsapp.number",
                    [["allow_inbound", "=", true], ["active", "=", true]],
                    ["name", "state"],
                    { order: "name" }
                );
            },
            loadConversations() {
                return orm.searchRead(
                    "flousflow.whatsapp.conversation",
                    [["state", "not in", ["closed", "spam", "blocked"]]],
                    [
                        "name", "customer_display_name", "partner_id", "customer_phone_normalized", "assigned_user_id",
                        "state", "sla_state", "last_message_at", "number_id", "team_id", "lead_id",
                        "unread_count", "customer_typing",
                    ],
                    { limit: 100, order: "last_message_at desc, id desc" }
                );
            },
            async loadMessages(conversationId) {
                // Descending order + limit keeps the NEWEST 200 messages
                // (ascending + limit would return the OLDEST 200 and hide the
                // latest ones once a conversation exceeds 200 msgs). The result
                // is reversed back to ascending so the UI renders oldest→newest.
                const messages = await orm.searchRead(
                    "flousflow.whatsapp.message",
                    [["conversation_id", "=", conversationId]],
                    [
                        "direction", "source", "message_type", "body", "attachment_id",
                        "author_user_id", "state", "create_date", "attachment_name",
                        "attachment_mimetype", "attachment_size",
                        "voice_note", "service_window_override",
                    ],
                    { limit: 200, order: "create_date desc, id desc" }
                );
                return messages.reverse();
            },
            getLockInfo(conversationId) {
                return orm.call(
                    "flousflow.whatsapp.conversation", "get_write_lock_info", [[conversationId]]
                );
            },
            acquireLock(conversationId) {
                return orm.call(
                    "flousflow.whatsapp.conversation", "acquire_write_lock", [[conversationId]]
                );
            },
            claimConversation(conversationId) {
                return orm.call(
                    "flousflow.whatsapp.conversation",
                    "claim_and_acquire_write_lock",
                    [[conversationId]]
                );
            },
            heartbeat(conversationId) {
                return orm.call(
                    "flousflow.whatsapp.conversation", "heartbeat_write_lock", [[conversationId]]
                );
            },
            releaseLock(conversationId) {
                return orm.call(
                    "flousflow.whatsapp.conversation", "release_write_lock", [[conversationId], "close"]
                );
            },
            send(payload) {
                return orm.call("flousflow.whatsapp.message", "queue_outbound", [payload]);
            },
            markSeen(conversationId) {
                return orm.call(
                    "flousflow.whatsapp.conversation", "mark_seen", [[conversationId]]
                );
            },
            closeConversation(conversationId) {
                return orm.call(
                    "flousflow.whatsapp.conversation", "action_close_from_inbox", [[conversationId]]
                );
            },
            openLead(conversationId) {
                return orm.call(
                    "flousflow.whatsapp.conversation", "action_open_lead_wizard", [[conversationId]]
                );
            },
            loadDocumentActions(conversationId) {
                return orm.call(
                    "flousflow.whatsapp.conversation", "get_document_actions", [[conversationId]]
                );
            },
            openDocumentWizard(conversationId, providerKey) {
                return orm.call(
                    "flousflow.whatsapp.conversation",
                    "action_open_document_wizard",
                    [[conversationId], providerKey]
                );
            },
        };
    },
};

registry.category("services").add("flousflowWhatsappInbox", whatsappInboxService);
