from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import WhatsAppCommon


@tagged("post_install", "-at_install", "flousflow_whatsapp")
class TestNumberSecurity(WhatsAppCommon):
    def test_team_member_can_read_allowed_number(self):
        visible = self.Number.with_user(self.agent).search([("id", "=", self.number.id)])
        self.assertEqual(visible, self.number)

    def test_direct_deny_wins_over_team_membership(self):
        self.NumberMember.create(
            {
                "number_id": self.number.id,
                "user_id": self.agent.id,
                "access_mode": "deny",
            }
        )
        visible = self.Number.with_user(self.agent).search([("id", "=", self.number.id)])
        self.assertFalse(visible)

    def test_direct_allow_grants_number_outside_team(self):
        outsider_team = self.Team.create(
            {"name": "Collections", "company_id": self.company.id}
        )
        allowed_number = self.Number.create(
            {
                "name": "Collections Number",
                "phone_number": "+201000000003",
                "company_id": self.company.id,
                "primary_team_id": outsider_team.id,
            }
        )
        self.NumberMember.create(
            {
                "number_id": allowed_number.id,
                "user_id": self.agent.id,
                "access_mode": "allow",
            }
        )
        visible = self.Number.with_user(self.agent).search([("id", "=", allowed_number.id)])
        self.assertEqual(visible, allowed_number)

    def test_cross_company_number_is_hidden(self):
        visible = self.Number.with_user(self.agent).search([("id", "=", self.other_number.id)])
        self.assertFalse(visible)

    def test_phone_is_normalized_and_unique_per_company(self):
        self.assertEqual(self.number.phone_normalized, "+201000000001")
        with self.assertRaises(ValidationError):
            self.Number.create(
                {
                    "name": "Duplicate Number",
                    "phone_number": "0020 100 000 0001",
                    "company_id": self.company.id,
                    "primary_team_id": self.team.id,
                }
            )

    def test_team_company_must_match_number_company(self):
        with self.assertRaises(ValidationError):
            self.Number.create(
                {
                    "name": "Invalid Company Number",
                    "phone_number": "+201000000004",
                    "company_id": self.company.id,
                    "primary_team_id": self.other_team.id,
                }
            )

    def test_attachment_limit_cannot_exceed_global_cap(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "flousflow_whatsapp.attachment_global_cap_mb", "10"
        )
        with self.assertRaises(ValidationError):
            self.number.write({"attachment_limit_mb": 11})

    def test_denied_user_cannot_write_number_by_known_id(self):
        self.NumberMember.create(
            {
                "number_id": self.number.id,
                "user_id": self.agent.id,
                "access_mode": "deny",
            }
        )
        with self.assertRaises(Exception):
            self.number.with_user(self.agent).write({"name": "Forbidden"})
