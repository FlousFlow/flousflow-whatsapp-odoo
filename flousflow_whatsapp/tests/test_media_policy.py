from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import WhatsAppCommon


@tagged("post_install", "-at_install", "flousflow_whatsapp")
class TestWhatsappMediaPolicy(WhatsAppCommon):
    def test_video_mime_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["flousflow.whatsapp.media.policy"].validate(
                "clip.mp4", "video/mp4", 1024, b"\x00\x00\x00\x18ftypmp42"
            )

    def test_video_signature_with_pdf_name_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["flousflow.whatsapp.media.policy"].validate(
                "invoice.pdf", "application/pdf", 1024, b"\x00\x00\x00\x18ftypmp42"
            )

    def test_ten_megabyte_pdf_is_allowed(self):
        self.assertTrue(self.env["flousflow.whatsapp.media.policy"].validate(
            "invoice.pdf", "application/pdf", 10 * 1024 * 1024, b"%PDF-1.7", 10
        ))

    def test_file_over_limit_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["flousflow.whatsapp.media.policy"].validate(
                "invoice.pdf", "application/pdf", 10 * 1024 * 1024 + 1, b"%PDF", 10
            )

    def test_browser_recorded_audio_webm_is_allowed(self):
        audio_webm = b"\x1aE\xdf\xa3" + b"\x00" * 32 + b"\x83\x81\x02"
        self.assertTrue(self.env["flousflow.whatsapp.media.policy"].validate(
            "voice.webm", "audio/webm;codecs=opus", len(audio_webm), audio_webm
        ))

    def test_video_track_hidden_as_audio_webm_is_rejected(self):
        video_webm = b"\x1aE\xdf\xa3" + b"\x00" * 32 + b"\x83\x81\x01"
        with self.assertRaises(ValidationError):
            self.env["flousflow.whatsapp.media.policy"].validate(
                "voice.webm", "audio/webm", len(video_webm), video_webm
            )

    def test_browser_recorded_audio_mp4_is_allowed(self):
        audio_mp4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32 + b"hdlr" + b"\x00" * 8 + b"soun"
        self.assertTrue(self.env["flousflow.whatsapp.media.policy"].validate(
            "voice.m4a", "audio/mp4", len(audio_mp4), audio_mp4
        ))

    def test_video_track_hidden_as_audio_mp4_is_rejected(self):
        video_mp4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32 + b"hdlr" + b"\x00" * 8 + b"vide"
        with self.assertRaises(ValidationError):
            self.env["flousflow.whatsapp.media.policy"].validate(
                "voice.m4a", "audio/mp4", len(video_mp4), video_mp4
            )
