from odoo import api, models, _
from odoo.exceptions import ValidationError


ALLOWED_MIMETYPES = {
    "image/jpeg",
    "image/png",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp4",
    "audio/webm",
}
WEBM_SIGNATURE = b"\x1aE\xdf\xa3"
WEBM_VIDEO_TRACK = b"\x83\x81\x01"
WEBM_AUDIO_TRACK = b"\x83\x81\x02"
MP4_FILE_TYPE = b"ftyp"
MP4_VIDEO_HANDLER = b"vide"
MP4_AUDIO_HANDLER = b"soun"


class FlousflowWhatsappMediaPolicy(models.AbstractModel):
    _name = "flousflow.whatsapp.media.policy"
    _description = "Flous Flow WhatsApp Media Policy"

    @api.model
    def validate(self, filename, mimetype, size, sample=b"", limit_mb=10):
        normalized_mimetype = (mimetype or "").lower().split(";", 1)[0].strip()
        sample = sample or b""
        if normalized_mimetype.startswith("video/"):
            raise ValidationError(_("Video files are not allowed in WhatsApp conversations."))
        is_mp4 = MP4_FILE_TYPE in sample[:64]
        if normalized_mimetype == "audio/webm":
            if (
                not sample.startswith(WEBM_SIGNATURE)
                or WEBM_VIDEO_TRACK in sample
                or WEBM_AUDIO_TRACK not in sample
            ):
                raise ValidationError(_("The WebM file is not a valid audio-only recording."))
        elif normalized_mimetype == "audio/mp4":
            if (
                not is_mp4
                or MP4_VIDEO_HANDLER in sample
                or MP4_AUDIO_HANDLER not in sample
            ):
                raise ValidationError(_("The MP4 file is not a valid audio-only recording."))
        elif WEBM_SIGNATURE in sample or is_mp4:
            raise ValidationError(_("Video files are not allowed in WhatsApp conversations."))
        if normalized_mimetype not in ALLOWED_MIMETYPES:
            raise ValidationError(_("This file type is not allowed in WhatsApp conversations."))
        if size < 0 or size > max(1, int(limit_mb or 10)) * 1024 * 1024:
            raise ValidationError(_("The file exceeds the allowed WhatsApp attachment size."))
        return True
