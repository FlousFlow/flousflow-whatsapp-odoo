from werkzeug.utils import redirect

from odoo import http
from odoo.http import request


class FlousflowWhatsappInboxController(http.Controller):
    @http.route("/flousflow/whatsapp/inbox", type="http", auth="user")
    def open_inbox(self):
        """Leave stale debug bundles before executing the inbox client action."""
        action = request.env.ref("flousflow_whatsapp.action_whatsapp_inbox")
        return redirect(f"/odoo/action-{action.id}?debug=0", code=303)
