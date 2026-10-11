"""Synthetic delivery and explicit approval acceptance tests; no customer messages."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from quote_lab.builder import NamedPanel
from quote_lab.durable_store import DurableQuoteStore, QuoteStoreError
from quote_lab.simulator import QuoteSimulation, SimulatedDelivery, SimulatedApproval, run_owner_simulation
from quote_lab.workflow import restore_offline_quote


class QuoteSimulationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "simulation.sqlite3"
        self.store = DurableQuoteStore(self.path)
        self.sim = QuoteSimulation(self.store)
        self.id = "simulation-unit-case"
        self.panels = [NamedPanel("door", 90, 200, "אנטיסן ברונזה")] * 2
        self.draft = self.sim.create(self.id, "פינתי 2 דלתות", self.panels, layout_confirmed=True)
        queued = self.sim.queue_preview(self.id, 1)
        self.delivery = SimulatedDelivery(self.id, 1, queued["message_id"], "delivered")
        self.approval = SimulatedApproval(self.id, 1, "sim-approval-unit-case",
                                          self.draft["specification_fingerprint"], "2828", True, True)

    def tearDown(self):
        self.temp.cleanup()

    def test_transport_acceptance_failure_and_sent_leave_draft_unapproved(self):
        for status in ("queued", "accepted", "sent", "failed"):
            row = self.sim.delivery(replace(self.delivery, status=status))
            self.assertEqual(row["state"], "draft")
            self.assertIsNone(row["delivery_ref"])
            with self.assertRaises(QuoteStoreError):
                self.sim.approve(self.approval)
        self.assertEqual(self.store.latest(self.id)["state"], "draft")

    def test_delivery_must_bind_to_exact_quote_message_and_known_status(self):
        for event in (replace(self.delivery, message_id="real-whatsapp-id"),
                      replace(self.delivery, message_id="sim-message-unrelated"),
                      replace(self.delivery, status="unknown"),
                      replace(self.delivery, version=2),
                      replace(self.delivery, quote_id="actual-customer")):
            with self.subTest(event=event), self.assertRaises(QuoteStoreError):
                self.sim.delivery(event)
        self.assertEqual(self.store.latest(self.id)["state"], "draft")

    def test_read_receipt_is_sufficient_and_repeat_is_idempotent_after_reconnect(self):
        sent = self.sim.delivery(replace(self.delivery, status="read"))
        self.assertEqual(sent["state"], "sent")
        reconnect = QuoteSimulation(DurableQuoteStore(self.path))
        self.assertEqual(reconnect.delivery(self.delivery), sent)
        approved = reconnect.approve(self.approval)
        self.assertEqual(approved["state"], "approved")
        self.assertEqual(reconnect.approve(self.approval), approved)
        self.assertEqual(reconnect.delivery(self.delivery), approved)
        self.assertEqual(len(self.store.history(self.id)), 1)

    def test_explicit_price_and_specification_are_both_required(self):
        self.sim.delivery(self.delivery)
        for event in (replace(self.approval, accepts_price=False),
                      replace(self.approval, accepts_specification=False),
                      replace(self.approval, accepts_price="yes"),
                      replace(self.approval, amount="2829"),
                      replace(self.approval, amount="NaN"),
                      replace(self.approval, specification_fingerprint="another-spec"),
                      replace(self.approval, event_id="real-customer-approval"),
                      replace(self.approval, event_id="sim-approval-")):
            with self.subTest(event=event), self.assertRaises(QuoteStoreError):
                self.sim.approve(event)
        self.assertEqual(self.store.latest(self.id)["state"], "sent")
        self.assertIsNone(self.store.latest(self.id)["approval_ref"])

    def test_changed_design_blocks_old_evidence_and_starts_new_draft(self):
        self.sim.delivery(self.delivery)
        self.sim.approve(self.approval)
        latest = self.sim.create(self.id, "פינתי 2 דלתות", self.panels,
                                 layout_confirmed=True, decoration="frosted_middle")
        self.assertEqual(latest["price_before_vat"], "3098.00")
        for action in (lambda: self.sim.delivery(self.delivery), lambda: self.sim.approve(self.approval),
                       lambda: self.sim.queue_preview(self.id, 1),
                       lambda: self.sim.approve(replace(self.approval, version=2))):
            with self.assertRaises(QuoteStoreError):
                action()
        self.assertEqual(self.store.latest(self.id)["state"], "draft")
        self.assertIsNone(self.store.latest(self.id)["approval_ref"])
        self.assertEqual(restore_offline_quote(DurableQuoteStore(self.path), self.id), latest)

    def test_queue_preview_is_not_sending_or_delivery(self):
        queued = self.sim.queue_preview(self.id, 1)
        self.assertFalse(queued["send_authorized"])
        self.assertEqual(queued["transport"], "simulated_only")
        self.assertEqual(queued["text"], self.draft["customer_preview_text"])
        self.assertEqual(self.store.latest(self.id)["state"], "draft")

    def test_real_quote_identity_and_untyped_events_are_rejected(self):
        with self.assertRaises(QuoteStoreError):
            self.sim.create("972000000000", "פינתי 2 דלתות", self.panels, layout_confirmed=True)
        with self.assertRaises(QuoteStoreError):
            self.sim.delivery({"status": "delivered"})
        with self.assertRaises(QuoteStoreError):
            self.sim.approve("אני מאשר")
        self.assertEqual(len(self.store.history(self.id)), 1)

    def test_owner_review_example_matches_actual_run_and_hides_internal_costs(self):
        result = run_owner_simulation(self.store)
        sample = json.loads((Path(__file__).parent / "owner_simulation_example.json").read_text())
        self.assertEqual(result, sample)
        self.assertEqual(result["real_messages_sent"], 0)
        self.assertEqual([r["state"] for r in result["versions"]], ["approved","draft","draft","draft"])
        self.assertEqual([r["price_before_vat"] for r in result["versions"]],
                         ["2828.00","3098.00","3198.00","3448.00"])
        for forbidden in ("glass_supplier_cost", "hardware_supplier_base_cost", "עלות ספק"):
            self.assertNotIn(forbidden, json.dumps(result, ensure_ascii=False))
