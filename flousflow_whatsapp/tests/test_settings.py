from odoo.tools.safe_eval import safe_eval
from odoo.tests.common import TransactionCase


class TestWhatsappSettings(TransactionCase):
    def test_settings_action_opens_whatsapp_app(self):
        action = self.env.ref("flousflow_whatsapp.action_whatsapp_settings")
        self.assertEqual(action.res_model, "res.config.settings")
        self.assertEqual(action.view_mode, "form")
        self.assertEqual(safe_eval(action.context).get("module"), "flousflow_whatsapp")

    def test_settings_menu_is_linked_to_action(self):
        menu = self.env.ref("flousflow_whatsapp.menu_whatsapp_settings")
        action = self.env.ref("flousflow_whatsapp.action_whatsapp_settings")
        self.assertEqual(menu.action, action)

    def test_settings_view_has_named_whatsapp_app(self):
        view = self.env.ref("flousflow_whatsapp.res_config_settings_view_form_whatsapp")
        self.assertIn('name="flousflow_whatsapp"', view.arch)
        self.assertIn('id="whatsapp_connector_url_setting"', view.arch)
