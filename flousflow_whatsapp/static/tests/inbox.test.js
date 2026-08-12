import { describe, expect, test } from "@odoo/hoot";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { mountWithCleanup, mockService } from "@web/../tests/web_test_helpers";
import { WhatsappInbox } from "../src/inbox/inbox";

defineMailModels();

const conversation = {
    id: 7, name: "WA/2026/0007", partner_id: [4, "Ahmed Customer"],
    customer_phone_normalized: "+201000000000", assigned_user_id: [9, "Agent"],
    number_id: [2, "Sales Main"], team_id: [3, "Sales"], state: "open", sla_state: "ok",
};

function setupInbox(lock, claimedLock = { ...lock, locked: true, owned_by_me: true, assigned_user_id: 9, assigned_user_name: "Agent" }, messages = null, selectedConversation = conversation) {
    mockService("flousflowWhatsappInbox", {
        loadConversations: async () => [selectedConversation],
        loadMessages: async () => messages || [{ id: 1, direction: "inbound", message_type: "text", body: "Hello", state: "received" }],
        acquireLock: async () => true,
        claimConversation: async () => claimedLock,
        getLockInfo: async () => lock,
        heartbeat: async () => true,
        releaseLock: async () => true,
        send: async () => 1,
        openLead: async () => ({}),
        loadDocumentActions: async () => [],
        openDocumentWizard: async () => ({}),
    });
}

describe.current.tags("desktop");

test("non-owner sees lock owner and disabled composer", async () => {
    setupInbox({ locked: true, owned_by_me: false, owner_name: "Ahmed Agent" });
    await mountWithCleanup(WhatsappInbox);
    expect(".o_ff_wa_lock_banner").toHaveText(/Ahmed Agent/);
    expect(".o_ff_wa_composer textarea").toHaveAttribute("disabled");
});

test("lock owner can compose", async () => {
    setupInbox({ locked: true, owned_by_me: true, owner_name: "Current Agent" });
    await mountWithCleanup(WhatsappInbox);
    expect(".o_ff_wa_lock_banner").toHaveCount(0);
    expect(".o_ff_wa_composer textarea").not.toHaveAttribute("disabled");
});

test("file picker omits video types", async () => {
    setupInbox({ locked: true, owned_by_me: true });
    await mountWithCleanup(WhatsappInbox);
    const accept = document.querySelector(".o_ff_wa_composer input[type=file]").getAttribute("accept");
    expect(accept).not.toInclude("video");
    expect(accept).toInclude("application/pdf");
});

test("audio attachment renders an inline player", async () => {
    setupInbox(
        { locked: true, owned_by_me: true },
        undefined,
        [{
            id: 11, direction: "inbound", message_type: "audio", body: false,
            attachment_id: [1157, "voice.ogg"], attachment_mimetype: "audio/ogg; codecs=opus",
            state: "received",
        }],
    );
    await mountWithCleanup(WhatsappInbox);
    expect("audio.o_ff_wa_audio").toHaveAttribute("src", "/web/content/1157?download=false");
    expect("audio.o_ff_wa_audio").toHaveAttribute("controls");
});

test("image and document attachments are rendered instead of placeholders", async () => {
    setupInbox(
        { locked: true, owned_by_me: true }, undefined,
        [
            { id: 21, direction: "inbound", message_type: "image", attachment_id: [210, "photo.jpg"], attachment_name: "photo.jpg", state: "received" },
            { id: 22, direction: "outbound", source: "odoo", message_type: "document", attachment_id: [220, "quote.pdf"], attachment_name: "quote.pdf", attachment_size: 2048, state: "delivered" },
        ],
    );
    await mountWithCleanup(WhatsappInbox);
    expect("img.o_ff_wa_image").toHaveAttribute("src", "/web/content/210?download=false");
    expect(".o_ff_wa_document").toHaveText(/quote.pdf/);
    expect(".o_ff_wa_document a[title='Download']").toHaveAttribute("href", "/web/content/220?download=true");
});

test("read receipts and direct phone replies are clearly distinguished", async () => {
    setupInbox(
        { locked: true, owned_by_me: true }, undefined,
        [
            { id: 31, direction: "outbound", source: "odoo", message_type: "text", body: "Odoo", state: "read" },
            { id: 32, direction: "outbound", source: "whatsapp_device", message_type: "text", body: "Phone", state: "sent" },
        ],
    );
    await mountWithCleanup(WhatsappInbox);
    expect(".o_ff_wa_receipt.read").toHaveText(/Read/);
    expect(".badge.text-bg-secondary").toHaveText(/Sent from WhatsApp phone/);
});

test("lock owner has a microphone recording action", async () => {
    setupInbox({ locked: true, owned_by_me: true });
    await mountWithCleanup(WhatsappInbox);
    expect(".o_ff_wa_record_button").toHaveCount(1);
    expect(".o_ff_wa_record_button").not.toHaveAttribute("disabled");
});

test("unassigned conversation can be claimed before replying", async () => {
    setupInbox({ locked: false, owned_by_me: false, assigned_user_id: false });
    await mountWithCleanup(WhatsappInbox);
    expect(".o_ff_wa_claim_banner").toHaveCount(1);
    expect(".o_ff_wa_composer textarea").toHaveAttribute("disabled");
    await document.querySelector(".o_ff_wa_claim_banner button").click();
    expect(".o_ff_wa_claim_banner").toHaveCount(0);
    expect(".o_ff_wa_composer textarea").not.toHaveAttribute("disabled");
});

test("new lead requires ownership of the conversation", async () => {
    setupInbox({ locked: false, owned_by_me: false, assigned_user_id: false });
    await mountWithCleanup(WhatsappInbox);
    expect("button[title='Assign the conversation to yourself first']").toHaveAttribute("disabled");
});

test("a conversation already linked to CRM is visibly marked and opens the existing lead", async () => {
    setupInbox(
        { locked: false, owned_by_me: false, assigned_user_id: false },
        undefined,
        null,
        { ...conversation, lead_id: [42, "WhatsApp Lead"] },
    );
    await mountWithCleanup(WhatsappInbox);
    expect(".o_ff_wa_thread header button.btn-outline-primary").toHaveText(/Open Lead/);
    expect(".o_ff_wa_thread header button.btn-outline-primary").not.toHaveAttribute("disabled");
});
