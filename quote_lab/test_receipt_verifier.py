"""Signed local fixtures only; no live Meta events, tokens or customer data."""
from dataclasses import replace
import hashlib
import hmac
import json
from pathlib import Path
import tempfile
import unittest

from quote_lab.builder import NamedPanel
from quote_lab.durable_store import DurableQuoteStore, QuoteStoreError
from quote_lab.receipt_verifier import (OutboundBinding, ReceiptError,
                                        verify_status_webhook, apply_signed_fixture)
from quote_lab.simulator import QuoteSimulation, SimulatedApproval

SECRET = b"synthetic-fixture-secret-only"
ACCOUNT = "fixture-waba"
PHONE = "fixture-phone-id"


def payload_for(message_id="fixture-wamid-1", status="delivered", recipient="0000000001"):
    return {"object": "whatsapp_business_account", "entry": [{"id": ACCOUNT, "changes": [{
        "field": "messages", "value": {"messaging_product": "whatsapp",
        "metadata": {"phone_number_id": PHONE}, "statuses": [{"id": message_id,
        "status": status, "timestamp": "1791744523", "recipient_id": recipient}]}}]}]}


def sign(payload):
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return raw, "sha256=" + hmac.new(SECRET, raw, hashlib.sha256).hexdigest()


class SignedReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "signed-fixtures.sqlite3"
        self.store = DurableQuoteStore(self.path)
        self.sim = QuoteSimulation(self.store)
        self.id = "simulation-signed-fixture"
        self.panels = [NamedPanel("door",90,200,"אנטיסן ברונזה")] * 2
        self.draft = self.sim.create(self.id, "פינתי 2 דלתות", self.panels, layout_confirmed=True)
        self.binding = OutboundBinding("fixture-wamid-1", "0000000001", self.id, 1,
                                       self.draft["specification_fingerprint"], "2828.00")

    def tearDown(self):
        self.temp.cleanup()

    def verify(self, payload=None, **changes):
        raw, signature = sign(payload or payload_for())
        options = dict(app_secret=SECRET, account_id=ACCOUNT, phone_number_id=PHONE, bindings=[self.binding])
        options.update(changes)
        return verify_status_webhook(raw, signature, **options)

    def apply(self, payload=None, **changes):
        raw, signature = sign(payload or payload_for())
        options = dict(app_secret=SECRET, account_id=ACCOUNT, phone_number_id=PHONE, bindings=[self.binding])
        options.update(changes)
        return apply_signed_fixture(self.sim, raw, signature, **options)

    def test_valid_signature_and_binding_return_delivery_without_side_effects(self):
        receipt, = self.verify()
        self.assertEqual(receipt.binding, self.binding)
        self.assertEqual(receipt.status, "delivered")
        self.assertEqual(self.store.latest(self.id)["state"], "draft")

    def test_tampered_bytes_wrong_signature_and_wrong_secret_are_rejected(self):
        raw, signature = sign(payload_for())
        for body, sig, secret in [(raw + b" ", signature, SECRET),
                                  (raw, "sha256=" + "0" * 64, SECRET),
                                  (raw, signature, b"different-fixture-secret"),
                                  (raw, "", SECRET), (raw, signature, b"")]:
            with self.subTest(signature=sig), self.assertRaises(ReceiptError):
                verify_status_webhook(body, sig, app_secret=secret, account_id=ACCOUNT,
                                       phone_number_id=PHONE, bindings=[self.binding])
        self.assertEqual(self.store.latest(self.id)["state"], "draft")

    def test_sent_failed_deleted_do_not_prove_delivery(self):
        for status in ("sent", "failed", "deleted"):
            self.assertEqual(self.apply(payload_for(status=status)), [])
        self.assertEqual(self.store.latest(self.id)["state"], "draft")

    def test_other_accounts_numbers_and_unknown_messages_are_ignored(self):
        other_account = payload_for(); other_account["entry"][0]["id"] = "another-waba"
        other_phone = payload_for(); other_phone["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = "other-phone"
        for payload in (other_account, other_phone, payload_for(message_id="unknown-wamid")):
            self.assertEqual(self.apply(payload), [])
        self.assertEqual(self.store.latest(self.id)["state"], "draft")

    def test_wrong_recipient_is_rejected_even_with_valid_signature(self):
        with self.assertRaises(ReceiptError):
            self.apply(payload_for(recipient="0000000002"))
        self.assertEqual(self.store.latest(self.id)["state"], "draft")

    def test_duplicate_statuses_are_deduplicated(self):
        payload = payload_for()
        statuses = payload["entry"][0]["changes"][0]["value"]["statuses"]
        statuses.append(statuses[0].copy())
        self.assertEqual(len(self.verify(payload)), 1)
        self.assertEqual(len(self.apply(payload)), 1)
        self.assertEqual(self.store.latest(self.id)["state"], "sent")

    def test_replayed_read_and_delivery_never_downgrade_approval(self):
        self.apply(payload_for(status="read"))
        approval = SimulatedApproval(self.id, 1, "sim-approval-signed-fixture",
                                     self.draft["specification_fingerprint"], "2828", True, True)
        self.sim.approve(approval)
        self.store = DurableQuoteStore(self.path)
        self.sim = QuoteSimulation(self.store)
        self.assertEqual(self.apply()[0]["state"], "approved")
        self.assertEqual(self.apply(payload_for(status="read"))[0]["state"], "approved")
        self.assertEqual(len(self.store.history(self.id)), 1)

    def test_current_version_cannot_use_old_outbound_binding(self):
        self.sim.create(self.id, "פינתי 2 דלתות", self.panels,
                         layout_confirmed=True, decoration="frosted_middle")
        with self.assertRaises(QuoteStoreError):
            self.apply()
        self.assertEqual(self.store.latest(self.id)["state"], "draft")
        self.assertIsNone(self.store.latest(self.id)["delivery_ref"])

    def test_binding_fingerprint_and_price_must_match_saved_quote(self):
        for binding in (replace(self.binding, amount="2829.00"),
                        replace(self.binding, specification_fingerprint="a" * 64)):
            with self.assertRaises(QuoteStoreError):
                self.apply(bindings=[binding])
        self.assertEqual(self.store.latest(self.id)["state"], "draft")

    def test_duplicate_bindings_and_invalid_versions_are_rejected(self):
        for bindings in ([self.binding,self.binding], [replace(self.binding,version=True)],
                         [replace(self.binding, amount="NaN")]):
            with self.assertRaises(ReceiptError):
                self.verify(bindings=bindings)

    def test_malformed_and_duplicate_json_are_rejected_after_signature_validation(self):
        for raw in (b'{"object":"whatsapp_business_account","object":"x","entry":[]}',
                    b'{', b'{"object":"whatsapp_business_account","entry":null}',
                    b'[]', b'{"object":"whatsapp_business_account","entry":[1]}'):
            signature = "sha256=" + hmac.new(SECRET,raw,hashlib.sha256).hexdigest()
            with self.assertRaises(ReceiptError):
                verify_status_webhook(raw, signature, app_secret=SECRET, account_id=ACCOUNT,
                                       phone_number_id=PHONE, bindings=[self.binding])

    def test_bad_timestamp_or_unknown_status_is_rejected(self):
        for key, value in [("timestamp","NaN"),("timestamp","0"),("timestamp",123),("status","accepted")]:
            payload=payload_for()
            payload["entry"][0]["changes"][0]["value"]["statuses"][0][key]=value
            with self.assertRaises(ReceiptError):
                self.apply(payload)
        self.assertEqual(self.store.latest(self.id)["state"], "draft")

    def test_invalid_batch_is_checked_before_any_fixture_update(self):
        payload=payload_for()
        statuses=payload["entry"][0]["changes"][0]["value"]["statuses"]
        statuses.append(dict(statuses[0], recipient_id="wrong"))
        with self.assertRaises(ReceiptError):
            self.apply(payload)
        self.assertEqual(self.store.latest(self.id)["state"], "draft")

    def test_fixture_bridge_rejects_production_account_and_message_identity(self):
        for changes in (dict(account_id="2021042791935760"),
                        dict(phone_number_id="456765487527572"),
                        dict(bindings=[replace(self.binding,message_id="wamid.real")])):
            with self.assertRaises(ReceiptError):
                self.apply(**changes)
