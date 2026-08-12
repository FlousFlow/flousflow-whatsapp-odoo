from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from .common import WhatsAppCommon


@tagged("post_install", "-at_install", "flousflow_whatsapp")
class TestWhatsappPresenceIntervals(WhatsAppCommon):
    def setUp(self):
        super().setUp()
        self.Interval = self.env["flousflow.whatsapp.presence.interval"]
        self.Interval.search([("user_id", "in", [self.agent.id, self.agent_b.id])]).unlink()

    def test_online_to_away_closes_online_interval(self):
        started_at = fields.Datetime.now() - timedelta(minutes=12)
        ended_at = started_at + timedelta(minutes=12)

        self.Interval.record_transition(self.agent, "online", started_at)
        self.Interval.record_transition(self.agent, "away", ended_at)

        online = self.Interval.search(
            [("user_id", "=", self.agent.id), ("status", "=", "online")]
        )
        self.assertEqual(len(online), 1)
        self.assertEqual(online.duration_seconds, 720)
        self.assertEqual(online.online_seconds, 720)

    def test_repeated_same_status_does_not_split_interval(self):
        started_at = fields.Datetime.now() - timedelta(minutes=3)
        self.Interval.record_transition(self.agent, "online", started_at)
        self.Interval.record_transition(
            self.agent, "online", started_at + timedelta(minutes=1)
        )
        open_intervals = self.Interval.search(
            [("user_id", "=", self.agent.id), ("ended_at", "=", False)]
        )
        self.assertEqual(len(open_intervals), 1)
        self.assertEqual(open_intervals.started_at, started_at)

    def test_manual_busy_status_is_recorded(self):
        self._set_presence(self.agent, "online")
        self.agent.manual_im_status = "busy"
        current = self.Interval.search(
            [("user_id", "=", self.agent.id), ("ended_at", "=", False)]
        )
        self.assertEqual(current.status, "busy")

    def test_profile_online_immediately_refreshes_effective_presence(self):
        self.agent.manual_im_status = "offline"
        self.assertEqual(self.agent.im_status, "offline")

        # Odoo's profile dropdown writes False when the user selects Online.
        self.agent.manual_im_status = False

        current = self.Interval.search(
            [("user_id", "=", self.agent.id), ("ended_at", "=", False)]
        )
        self.assertEqual(self.agent.im_status, "online")
        self.assertEqual(current.status, "online")
        self.assertEqual(current.source, "presence")

    def test_hr_employee_exposes_operational_online_seconds(self):
        employee = self.env["hr.employee"].create(
            {
                "name": "WhatsApp Employee",
                "user_id": self.agent.id,
                "company_id": self.company.id,
            }
        )
        started_at = fields.Datetime.now() - timedelta(minutes=5)
        self.Interval.record_transition(self.agent, "online", started_at)
        self.Interval.record_transition(
            self.agent, "offline", started_at + timedelta(minutes=5)
        )
        employee.invalidate_recordset(["whatsapp_online_seconds"])
        self.assertEqual(employee.whatsapp_online_seconds, 300)
