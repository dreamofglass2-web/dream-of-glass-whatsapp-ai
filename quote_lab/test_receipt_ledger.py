"""Persistent fixture binding contract, exercised on SQLite and disposable PG."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import tempfile
import subprocess
import sys
from threading import Barrier
import unittest
from uuid import uuid4

from quote_lab.builder import NamedPanel
from quote_lab.durable_store import QuoteStoreError
from quote_lab.receipt_ledger import PersistentReceiptStore
from quote_lab.receipt_verifier import OutboundBinding, ReceiptError
from quote_lab.simulator import QuoteSimulation, SimulatedApproval
from quote_lab.test_receipt_verifier import ACCOUNT, PHONE, SECRET, payload_for, sign


class ReceiptLedgerContract:
    def fixture_setup(self):
        self.identity = "simulation-persistent-" + uuid4().hex
        self.message_id = "fixture-wamid-" + uuid4().hex
        self.panels = [NamedPanel("door",90,200,"אנטיסן ברונזה")] * 2
        self.sim = QuoteSimulation(self.store)
        self.draft = self.sim.create(self.identity, "פינתי 2 דלתות", self.panels, layout_confirmed=True)
        self.binding = OutboundBinding(self.message_id, "0000000001", self.identity, 1,
                                       self.draft["specification_fingerprint"], "2828.00")

    def register(self, binding=None, **changes):
        options = dict(account_id=ACCOUNT, phone_number_id=PHONE)
        options.update(changes)
        return self.store.register_fixture_binding(binding or self.binding, **options)

    def apply(self, payload=None, store=None, **changes):
        raw, signature = sign(payload or payload_for(self.message_id))
        options = dict(app_secret=SECRET, account_id=ACCOUNT, phone_number_id=PHONE)
        options.update(changes)
        return (store or self.store).apply_persisted_fixture(raw, signature, **options)

    def test_binding_survives_reconnect_without_marking_delivery(self):
        self.register()
        again = self.factory()
        self.assertEqual(again.saved_fixture_bindings(account_id=ACCOUNT,phone_number_id=PHONE)
                         .count(self.binding), 1)
        self.assertEqual(again.latest(self.identity)["state"], "draft")
        self.assertIsNone(again.latest(self.identity)["delivery_ref"])
        self.assertEqual(self.apply(store=again)[0]["state"], "sent")
        self.assertEqual(len(again.fixture_event_history(self.message_id)), 1)

    def test_no_saved_binding_unknown_message_or_other_scope_has_no_effect(self):
        self.assertEqual(self.apply(), [])
        self.register()
        self.assertEqual(self.apply(payload_for("fixture-wamid-unknown")), [])
        self.assertEqual(self.apply(account_id="fixture-other"), [])
        self.assertEqual(self.apply(phone_number_id="fixture-other-phone"), [])
        self.assertEqual(self.store.latest(self.identity)["state"], "draft")
        self.assertEqual(self.store.fixture_event_history(self.message_id), [])

    def test_duplicate_registration_is_immutable_even_after_delivery_and_revision(self):
        self.assertEqual(self.register(), self.binding)
        self.assertEqual(self.register(replace(self.binding, amount="2828")), self.binding)
        self.apply()
        self.sim.create(self.identity, "פינתי 2 דלתות", self.panels,
                        layout_confirmed=True, decoration="frosted_middle")
        self.assertEqual(self.register(), self.binding)
        for change in (dict(recipient_id="0000000002"), dict(amount="2829"),
                       dict(specification_fingerprint="a" * 64), dict(version=2),
                       dict(message_id="fixture-wamid-another")):
            with self.assertRaises(ReceiptError):
                self.register(replace(self.binding, **change))
        for change in (dict(account_id="fixture-other"),dict(phone_number_id="fixture-other-phone")):
            with self.assertRaises(ReceiptError): self.register(**change)

    def test_old_missing_or_mismatched_quote_binding_is_rejected(self):
        for binding in (replace(self.binding, quote_id=self.identity + "-missing"),
                        replace(self.binding, specification_fingerprint="a" * 64),
                        replace(self.binding, amount="2829"), replace(self.binding, version=2)):
            with self.assertRaises(QuoteStoreError): self.register(binding)
        self.sim.create(self.identity,"פינתי 2 דלתות",self.panels,
                        layout_confirmed=True,decoration="frosted_middle")
        with self.assertRaises(QuoteStoreError): self.register()
        self.assertEqual(self.store.fixture_event_history(self.message_id), [])

    def test_real_ids_invalid_prices_and_boolean_versions_rejected(self):
        for changes in (dict(message_id="wamid.real"),dict(recipient_id="972501234567"),
                        dict(quote_id="customer-real"),dict(version=True),dict(version=0),
                        dict(amount="NaN"),dict(amount="2828.001"),dict(amount="Infinity")):
            with self.assertRaises(ReceiptError): self.register(replace(self.binding, **changes))
        for scope in (dict(account_id="12345"),dict(phone_number_id="12345")):
            with self.assertRaises(ReceiptError): self.register(**scope)

    def test_exact_duplicate_event_and_reordered_statuses_preserve_approval(self):
        self.register()
        read = payload_for(self.message_id,status="read")
        statuses = read["entry"][0]["changes"][0]["value"]["statuses"]
        statuses.append(statuses[0].copy())
        self.assertEqual(len(self.apply(read)), 1)
        approved = self.sim.approve(SimulatedApproval(self.identity,1,"sim-approval-" + uuid4().hex,
                                  self.binding.specification_fingerprint,"2828",True,True))
        again = self.factory()
        self.assertEqual(self.apply(read,store=again)[0], approved)
        self.assertEqual(self.apply(store=again)[0], approved)
        self.assertEqual(self.apply(store=again)[0], approved)
        self.assertEqual(len(again.fixture_event_history(self.message_id)), 2)
        self.assertEqual(len(again.history(self.identity)), 1)

    def test_non_delivery_statuses_never_create_receipt_or_transition(self):
        self.register()
        for status in ("sent","failed","deleted"):
            self.assertEqual(self.apply(payload_for(self.message_id,status=status)), [])
        self.assertEqual(self.store.latest(self.identity)["state"], "draft")
        self.assertEqual(self.store.fixture_event_history(self.message_id), [])

    def test_stale_delivery_and_replay_cannot_touch_new_draft(self):
        self.register(); self.apply()
        self.sim.create(self.identity,"פינתי 2 דלתות",self.panels,
                        layout_confirmed=True,decoration="frosted_middle")
        again = self.factory()
        for status in ("delivered","read"):
            with self.assertRaises(QuoteStoreError):
                self.apply(payload_for(self.message_id,status=status),store=again)
        self.assertEqual([row["state"] for row in again.history(self.identity)], ["sent","draft"])
        self.assertIsNone(again.latest(self.identity)["delivery_ref"])
        self.assertEqual(len(again.fixture_event_history(self.message_id)), 1)

    def test_wrong_recipient_or_signature_leaves_no_partial_update(self):
        self.register()
        with self.assertRaises(ReceiptError): self.apply(payload_for(self.message_id,recipient="0000000002"))
        raw,signature = sign(payload_for(self.message_id))
        with self.assertRaises(ReceiptError):
            self.store.apply_persisted_fixture(raw+b" ",signature,app_secret=SECRET,
                                               account_id=ACCOUNT,phone_number_id=PHONE)
        self.assertEqual(self.store.latest(self.identity)["state"], "draft")
        self.assertEqual(self.store.fixture_event_history(self.message_id), [])

    def test_interrupted_event_insert_rolls_back_transition_and_retry_recovers(self):
        self.register()
        original = self.store._receipt_transaction
        class InterruptingCursor:
            def __init__(self, cursor): self.cursor = cursor
            def execute(cursor_self, sql, params=()):
                if "INSERT INTO " + self.store._events in sql:
                    raise RuntimeError("synthetic failure after quote update before event insert")
                return cursor_self.cursor.execute(sql, params)
            def fetchone(self): return self.cursor.fetchone()
            def fetchall(self): return self.cursor.fetchall()
        @contextmanager
        def interrupted():
            with original() as cur: yield InterruptingCursor(cur)
        self.store._receipt_transaction = interrupted
        try:
            with self.assertRaises(RuntimeError): self.apply()
        finally:
            self.store._receipt_transaction = original
        again = self.factory()
        self.assertEqual(again.latest(self.identity)["state"], "draft")
        self.assertEqual(again.fixture_event_history(self.message_id), [])
        self.assertEqual(self.apply(store=again)[0]["state"], "sent")
        self.assertEqual(len(again.fixture_event_history(self.message_id)), 1)

    def test_multi_quote_batch_rolls_back_when_later_quote_is_stale(self):
        self.register()
        other_id = self.identity + "-other"
        other = self.sim.create(other_id,"פינתי 2 דלתות",self.panels,layout_confirmed=True)
        other_message = self.message_id + "-other"
        self.register(OutboundBinding(other_message,"0000000001",other_id,1,
                                      other["specification_fingerprint"],"2828"))
        self.sim.create(other_id,"פינתי 2 דלתות",self.panels,layout_confirmed=True,decoration="frosted_middle")
        payload = payload_for(self.message_id)
        payload["entry"][0]["changes"][0]["value"]["statuses"].extend(
            payload_for(other_message)["entry"][0]["changes"][0]["value"]["statuses"])
        with self.assertRaises(QuoteStoreError): self.apply(payload)
        self.assertEqual(self.store.latest(self.identity)["state"], "draft")
        self.assertEqual(self.store.fixture_event_history(self.message_id), [])
        self.assertEqual(self.store.latest(other_id)["state"], "draft")

    def test_binding_corruption_and_snapshot_corruption_reject_receipts(self):
        self.register()
        with self.store._receipt_transaction() as cur:
            self.store._sql(cur,f"UPDATE {self.store._bindings} SET recipient_id=? WHERE message_id=?",
                            ("0000000002",self.message_id))
        with self.assertRaises(ReceiptError): self.apply()
        with self.store._receipt_transaction() as cur:
            self.store._sql(cur,f"UPDATE {self.store._bindings} SET recipient_id=? WHERE message_id=?",
                            ("0000000001",self.message_id))
            self.store._sql(cur,f"UPDATE {self.store._snapshots} SET payload_json='{{}}' WHERE quote_id=?",
                            (self.identity,))
        with self.assertRaises(QuoteStoreError): self.apply()
        self.assertEqual(self.store.latest(self.identity)["state"], "draft")

    def test_concurrent_duplicate_receipts_commit_one_event(self):
        self.register()
        workers = [self.factory() for _ in range(6)]
        ready = Barrier(6)
        def apply(store):
            ready.wait(timeout=10)
            return self.apply(store=store)[0]
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(apply,workers))
        self.assertTrue(all(row == results[0] for row in results))
        self.assertEqual(results[0]["state"],"sent")
        self.assertEqual(len(self.store.fixture_event_history(self.message_id)),1)

    def test_message_cannot_be_reassigned_to_another_quote(self):
        self.register()
        other_id = self.identity + "-reassignment"
        other = self.sim.create(other_id,"פינתי 2 דלתות",self.panels,layout_confirmed=True)
        with self.assertRaises(ReceiptError):
            self.register(replace(self.binding,quote_id=other_id,
                                  specification_fingerprint=other["specification_fingerprint"]))
        self.assertEqual(self.store.latest(other_id)["state"],"draft")

    def test_concurrent_identical_registration_is_idempotent(self):
        workers = [self.factory() for _ in range(4)]
        ready = Barrier(4)
        def register(store):
            ready.wait(timeout=10)
            return store.register_fixture_binding(self.binding,account_id=ACCOUNT,phone_number_id=PHONE)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(register,workers))
        self.assertTrue(all(binding == self.binding for binding in results))
        self.assertEqual(self.store.latest(self.identity)["state"],"draft")


class SQLiteReceiptLedgerTests(ReceiptLedgerContract, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "persistent-receipts.sqlite3"
        self.factory = lambda: PersistentReceiptStore(self.path)
        self.store = self.factory()
        self.fixture_setup()

    def test_fresh_process_uses_only_persisted_binding(self):
        self.register()
        script = """
import sys
from quote_lab.receipt_ledger import PersistentReceiptStore
from quote_lab.test_receipt_verifier import ACCOUNT,PHONE,SECRET,payload_for,sign
store=PersistentReceiptStore(sys.argv[1])
raw,signature=sign(payload_for(sys.argv[2]))
assert store.apply_persisted_fixture(raw,signature,app_secret=SECRET,
    account_id=ACCOUNT,phone_number_id=PHONE)[0]['state']=='sent'
"""
        result = subprocess.run([sys.executable,"-c",script,str(self.path),self.message_id],
                                cwd=Path(__file__).resolve().parent.parent,
                                capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.store.latest(self.identity)["state"],"sent")
        self.assertEqual(len(self.store.fixture_event_history(self.message_id)),1)
