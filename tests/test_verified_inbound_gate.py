"""Inbound authorization tests. All delivery and database functions are mocked."""
import os
import json
import hmac
import unittest
from unittest.mock import patch
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test-only")
import app as yossi


class VerifiedInboundGateTests(unittest.TestCase):
    def setUp(self):
        self.client = yossi.app.test_client()
        self.payload = {"entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": str(yossi.PHONE_NUMBER_ID)},
            "messages": [{"id": "wamid.TEST", "from": "972501234567",
                          "type": "text", "text": {"body": "שלום"}}]
        }}]}]}

    def signed_post(self, secret="offline-test-app-secret"):
        raw = json.dumps(self.payload, ensure_ascii=False).encode("utf-8")
        signature = "sha256=" + hmac.new(secret.encode(), raw, "sha256").hexdigest()
        with patch.object(yossi, "APP_SECRET", secret):
            return self.client.post("/webhook", data=raw, content_type="application/json",
                                    headers={"X-Hub-Signature-256": signature})

    def test_reject_missing_app_secret(self):
        with patch.object(yossi, "APP_SECRET", ""), patch.object(yossi, "ensure_worker_started") as worker:
            self.assertEqual(self.client.post("/webhook", json=self.payload).status_code, 503)
            worker.assert_not_called()

    def test_reject_unsigned_webhook(self):
        with patch.object(yossi, "APP_SECRET", "offline-test-app-secret"), \
             patch.object(yossi, "ensure_worker_started") as worker:
            self.assertEqual(self.client.post("/webhook", json=self.payload).status_code, 403)
            worker.assert_not_called()

    def test_wrong_business_number_is_ignored(self):
        self.payload["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = "another-number"
        with patch.object(yossi, "ensure_worker_started"), \
             patch.object(yossi, "verified_business_lead") as allowed, \
             patch.object(yossi, "queue_message") as queued:
            response = self.signed_post()
            self.assertEqual(response.status_code, 200)
            allowed.assert_not_called()
            queued.assert_not_called()

    def test_unknown_sender_is_ignored(self):
        with patch.object(yossi, "ensure_worker_started"), \
             patch.object(yossi, "verified_business_lead", return_value=False), \
             patch.object(yossi, "queue_message") as queued:
            self.assertEqual(self.signed_post().status_code, 200)
            queued.assert_not_called()

    def test_verified_meta_sender_is_queued_but_never_sent_from_webhook(self):
        with patch.object(yossi, "ensure_worker_started"), \
             patch.object(yossi, "verified_business_lead", return_value=True), \
             patch.object(yossi, "queue_message") as queued, \
             patch.object(yossi, "send_whatsapp") as sent:
            self.assertEqual(self.signed_post().status_code, 200)
            queued.assert_called_once_with("972501234567", "שלום", "wamid.TEST")
            sent.assert_not_called()

    def test_signed_click_to_whatsapp_ad_referral_is_recorded(self):
        self.payload["entry"][0]["changes"][0]["value"]["messages"][0]["referral"] = {
            "source_type": "ad", "source_id": "meta-ad-123"}
        with patch.object(yossi, "ensure_worker_started"), \
             patch.object(yossi, "persist_verified_whatsapp_ad", return_value=True) as persist, \
             patch.object(yossi, "verified_business_lead", return_value=True), \
             patch.object(yossi, "queue_message") as queued:
            self.assertEqual(self.signed_post().status_code, 200)
            persist.assert_called_once()
            queued.assert_called_once()

    def test_private_whatsapp_has_no_ad_provenance(self):
        with patch.object(yossi, "ensure_worker_started"), \
             patch.object(yossi, "persist_verified_whatsapp_ad") as persist, \
             patch.object(yossi, "verified_business_lead", return_value=False), \
             patch.object(yossi, "queue_message") as queued:
            self.assertEqual(self.signed_post().status_code, 200)
            persist.assert_not_called()
            queued.assert_not_called()

    def test_reject_referral_without_ad_identifier(self):
        with patch.object(yossi, "db_connection") as connect:
            self.assertFalse(yossi.persist_verified_whatsapp_ad(
                "972501234567", {"referral": {"source_type": "ad", "source_id": ""}}))
            connect.assert_not_called()

    def test_simulation_number_needs_explicit_distinct_id_and_allowlist(self):
        with patch.object(yossi, 'SIMULATION_PHONE_NUMBER_ID', ''), \
             patch.object(yossi, 'SIMULATION_ALLOWED_SENDERS', frozenset({'972501234567'})):
            self.assertFalse(yossi.simulation_channel_configured())
        with patch.object(yossi, 'SIMULATION_PHONE_NUMBER_ID', str(yossi.PHONE_NUMBER_ID)), \
             patch.object(yossi, 'SIMULATION_ALLOWED_SENDERS', frozenset({'972501234567'})):
            self.assertFalse(yossi.simulation_channel_configured())

    def test_only_explicit_test_sender_enters_simulation(self):
        self.payload['entry'][0]['changes'][0]['value']['metadata']['phone_number_id'] = 'test-meta-number-id'
        with patch.object(yossi, 'SIMULATION_PHONE_NUMBER_ID', 'test-meta-number-id'), \
             patch.object(yossi, 'SIMULATION_ALLOWED_SENDERS', frozenset({'972501234567'})), \
             patch.object(yossi, 'ensure_worker_started'), \
             patch.object(yossi, 'register_simulation_inbound', side_effect=lambda p: p == '972501234567') as register, \
             patch.object(yossi, 'verified_business_lead', return_value=True), \
             patch.object(yossi, 'queue_message') as queue:
            self.assertEqual(self.signed_post().status_code, 200)
            register.assert_called_once_with('972501234567')
            queue.assert_called_once()
            self.payload['entry'][0]['changes'][0]['value']['messages'][0]['from'] = '972509999999'
            self.assertEqual(self.signed_post().status_code, 200)
            queue.assert_called_once()

    def test_business_number_does_not_register_simulation(self):
        with patch.object(yossi, 'SIMULATION_PHONE_NUMBER_ID', 'test-meta-number-id'), \
             patch.object(yossi, 'SIMULATION_ALLOWED_SENDERS', frozenset({'972501234567'})), \
             patch.object(yossi, 'ensure_worker_started'), \
             patch.object(yossi, 'register_simulation_inbound') as register, \
             patch.object(yossi, 'clear_simulation_for_business_inbound') as clear, \
             patch.object(yossi, 'verified_business_lead', return_value=True), \
             patch.object(yossi, 'queue_message'):
            self.assertEqual(self.signed_post().status_code, 200)
            register.assert_not_called()
            clear.assert_called_once_with('972501234567')

    def test_database_failure_is_fail_closed(self):
        with patch.object(yossi, "ensure_db", side_effect=RuntimeError("unavailable")):
            self.assertFalse(yossi.verified_business_lead("972501234567"))

    def test_non_mobile_numbers_are_blocked(self):
        with patch.object(yossi, "db_connection") as connection:
            self.assertFalse(yossi.verified_business_lead("12025550123"))
            connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
