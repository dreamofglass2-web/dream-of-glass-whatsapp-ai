"""Required real PostgreSQL tests on disposable loopback quote_lab_test only."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import os
import time
import unittest
from threading import Barrier, Event
from uuid import uuid4

import psycopg2

from quote_lab.builder import NamedPanel
from quote_lab.durable_store import QuoteStoreError
from quote_lab.postgres_store import PostgresQuoteStore
from quote_lab.workflow import create_offline_quote, restore_offline_quote
from quote_lab.simulator import QuoteSimulation, SimulatedDelivery, SimulatedApproval, run_owner_simulation

URL = os.environ.get("QUOTE_LAB_TEST_DATABASE_URL")
if not URL:
    raise RuntimeError("Explicit disposable QUOTE_LAB_TEST_DATABASE_URL required; no tests skipped")


class PostgresQuoteIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.store = PostgresQuoteStore(URL)
        self.quote_id = "synthetic-" + uuid4().hex
        self.panels = [NamedPanel("door", 90, 200, "אנטיסן ברונזה")] * 2

    def create(self, **changes):
        return create_offline_quote(self.store, self.quote_id, "פינתי 2 דלתות", self.panels,
                                    layout_confirmed=True, **changes)

    def test_complete_draft_reopens_and_matches_owner_price(self):
        draft = self.create()
        again = PostgresQuoteStore(URL)
        self.assertEqual(restore_offline_quote(again, self.quote_id), draft)
        self.assertEqual(draft["price_before_vat"], "2828.00")
        self.assertFalse(draft["can_send_whatsapp"])
        self.assertFalse(draft["can_approve"])
        four = [NamedPanel("fixed",40,200,"שקופה")] * 2 + [NamedPanel("door",40,200,"שקופה")] * 2
        reference = create_offline_quote(again, self.quote_id + "-four", "פינתי 2 קבועים + 2 דלתות",
                                         four, layout_confirmed=True)
        self.assertEqual(reference["price_before_vat"], "2644.00")
        self.assertEqual(restore_offline_quote(again, self.quote_id + "-four"), reference)

    def test_sales_changes_and_exact_approval_preserve_history(self):
        old = self.create()
        self.store.mark_sent(self.quote_id, 1, "sim-delivery-" + uuid4().hex)
        for spec, amount in [("wrong", "2828"), (old["specification_fingerprint"], "2829"),
                             (old["specification_fingerprint"], "NaN")]:
            with self.assertRaises(QuoteStoreError):
                self.store.mark_approved(self.quote_id, 1, spec, amount, "sim-approval-" + uuid4().hex)
        approved = self.store.mark_approved(self.quote_id, 1, old["specification_fingerprint"],
                                            "2828", "sim-approval-" + uuid4().hex)
        self.assertEqual(approved["state"], "approved")
        with self.assertRaises(QuoteStoreError):
            restore_offline_quote(self.store, self.quote_id)
        records = [old, self.create(handle_style="ידית מגבת"),
                   self.create(handle_style="ידית מגבת", decoration="frosted_middle"),
                   self.create(handle_style="ידית מגבת", decoration="frosted_middle",
                               demolition_and_disposal=True)]
        self.assertEqual([r["price_before_vat"] for r in records], ["2828.00","2928.00","3198.00","3448.00"])
        self.assertEqual(restore_offline_quote(PostgresQuoteStore(URL), self.quote_id), records[-1])
        for record in records:
            snapshot = self.store.snapshot(self.quote_id, record["version"])
            self.assertEqual(snapshot["snapshot"]["customer_preview_text"], record["customer_preview_text"])
            if record["version"] > 1:
                self.assertEqual(snapshot["state"], "draft")
                self.assertIsNone(snapshot["delivery_ref"])
                self.assertIsNone(snapshot["approval_ref"])
        with self.assertRaises(QuoteStoreError):
            self.store.mark_sent(self.quote_id, 1, "sim-stale-" + uuid4().hex)

    def test_cannot_approve_unsent_or_missing_delivery(self):
        draft = self.create()
        with self.assertRaises(QuoteStoreError):
            self.store.mark_sent(self.quote_id, 1, "   ")
        with self.assertRaises(QuoteStoreError):
            self.store.mark_approved(self.quote_id, 1, draft["specification_fingerprint"],
                                     "2828", "sim-approval")
        self.assertEqual(self.store.latest(self.quote_id)["state"], "draft")

    def test_unique_delivery_and_approval_references(self):
        original = self.create()
        other_id = self.quote_id + "-other"
        other = create_offline_quote(self.store, other_id, "פינתי 2 דלתות", self.panels, layout_confirmed=True)
        delivery = "sim-delivery-" + uuid4().hex
        approval = "sim-approval-" + uuid4().hex
        self.store.mark_sent(self.quote_id, 1, delivery)
        with self.assertRaises(QuoteStoreError):
            self.store.mark_sent(other_id, 1, delivery)
        self.assertEqual(self.store.latest(other_id)["state"], "draft")
        self.store.mark_sent(other_id, 1, "sim-delivery-" + uuid4().hex)
        self.store.mark_approved(self.quote_id, 1, original["specification_fingerprint"], "2828", approval)
        with self.assertRaises(QuoteStoreError):
            self.store.mark_approved(other_id, 1, other["specification_fingerprint"], "2828", approval)
        self.assertEqual(self.store.latest(other_id)["state"], "sent")

    def test_parallel_revisions_bind_each_snapshot(self):
        ready = Barrier(12)
        def save(index):
            ready.wait(timeout=10)
            return self.create(decoration="frosted_stripes" if index % 2 else "none")
        with ThreadPoolExecutor(max_workers=12) as pool:
            records = list(pool.map(save, range(12)))
        self.assertEqual(sorted(r["version"] for r in records), list(range(1,13)))
        for record in records:
            saved = self.store.snapshot(self.quote_id, record["version"])
            self.assertEqual(saved["specification"], record["specification_fingerprint"])
            self.assertEqual(saved["snapshot"]["customer_preview_text"], record["customer_preview_text"])
        self.assertEqual(restore_offline_quote(self.store, self.quote_id), max(records, key=lambda r: r["version"]))

    def test_waiting_transition_rechecks_latest_after_revision_commits(self):
        self.create()
        waiting_pid = []
        started = Event()
        other = PostgresQuoteStore(URL)
        original = other._transaction
        @contextmanager
        def tracked():
            with original() as cur:
                cur.execute("SELECT pg_backend_pid() AS pid")
                waiting_pid.append(cur.fetchone()["pid"])
                started.set()
                yield cur
        other._transaction = tracked
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.store._transaction() as cur:
                self.store._lock(cur, self.quote_id)
                # A new metadata revision held uncommitted behind this quote lock.
                cur.execute("""INSERT INTO quote_lab_stage.versions
                    (quote_id,version,specification,price_before_vat,catalog_version)
                    VALUES (%s,2,'changed',3098,'test')""", (self.quote_id,))
                future = pool.submit(other.mark_sent, self.quote_id, 1, "sim-delivery-" + uuid4().hex)
                self.assertTrue(started.wait(timeout=3))
                # Confirm the transition is waiting on our lock before committing.
                deadline = time.monotonic() + 3
                while True:
                    cur.execute("""SELECT count(*) AS waiting FROM pg_locks
                        WHERE pid=%s AND locktype='advisory' AND NOT granted""", (waiting_pid[0],))
                    if cur.fetchone()["waiting"]:
                        break
                    if time.monotonic() >= deadline:
                        self.fail("Transition did not wait for the quote revision lock")
                    time.sleep(0.01)
            with self.assertRaises(QuoteStoreError):
                future.result(timeout=10)
        self.assertEqual([r["state"] for r in self.store.history(self.quote_id)], ["draft","draft"])

    def test_disconnection_rolls_back_partial_revision_and_recovers(self):
        first = self.create()
        original = self.store._transaction
        class DisconnectingCursor:
            def __init__(self, cursor): self.cursor = cursor
            def execute(self, sql, parameters=None):
                if "INSERT INTO quote_lab_stage.snapshots" in sql:
                    self.cursor.connection.close()
                    raise psycopg2.OperationalError("synthetic disconnect before snapshot write")
                return self.cursor.execute(sql, parameters)
            def fetchone(self): return self.cursor.fetchone()
        @contextmanager
        def disconnected():
            with original() as cur:
                yield DisconnectingCursor(cur)
        self.store._transaction = disconnected
        try:
            with self.assertRaises(psycopg2.Error):
                self.create(decoration="frosted_middle")
        finally:
            self.store._transaction = original
        self.assertEqual(self.store.history(self.quote_id)[-1]["version"], 1)
        self.assertEqual(restore_offline_quote(PostgresQuoteStore(URL), self.quote_id), first)
        self.assertEqual(self.create(decoration="frosted_middle")["version"], 2)

    def test_snapshot_corruption_refuses_restoration(self):
        self.create()
        with self.store._transaction() as cur:
            cur.execute("UPDATE quote_lab_stage.snapshots SET payload_json='{}' WHERE quote_id=%s", (self.quote_id,))
        with self.assertRaises(QuoteStoreError):
            restore_offline_quote(self.store, self.quote_id)

    def test_subcent_amounts_are_not_silently_rounded(self):
        with self.assertRaises(QuoteStoreError):
            self.store.create_draft(self.quote_id, "spec", "2644.001", "test")
        self.assertIsNone(self.store.latest(self.quote_id))

    def test_superuser_connection_is_refused(self):
        with self.assertRaises(QuoteStoreError):
            PostgresQuoteStore("postgresql://tester:disposable-test-only@127.0.0.1:5432/quote_lab_test")

    def test_full_owner_simulation_runs_on_real_postgres(self):
        result = run_owner_simulation(self.store, quote_id="simulation-pg-" + uuid4().hex)
        self.assertEqual(result["real_messages_sent"], 0)
        self.assertEqual([r["price_before_vat"] for r in result["versions"]],
                         ["2828.00", "3098.00", "3198.00", "3448.00"])
        self.assertEqual([r["state"] for r in result["versions"]], ["approved","draft","draft","draft"])
        self.assertEqual(len(result["checks"]), 7)

    def test_simulated_receipt_and_approval_replay_after_reconnect(self):
        identity = "simulation-pg-replay-" + uuid4().hex
        simulator = QuoteSimulation(self.store)
        draft = simulator.create(identity, "פינתי 2 דלתות", self.panels, layout_confirmed=True)
        queued = simulator.queue_preview(identity, 1)
        delivery = SimulatedDelivery(identity, 1, queued["message_id"], "delivered")
        simulator.delivery(delivery)
        approval = SimulatedApproval(identity, 1, "sim-approval-" + uuid4().hex,
                                      draft["specification_fingerprint"], "2828", True, True)
        approved = simulator.approve(approval)
        again = QuoteSimulation(PostgresQuoteStore(URL))
        self.assertEqual(again.delivery(delivery), approved)
        self.assertEqual(again.approve(approval), approved)
        self.assertEqual(len(self.store.history(identity)), 1)

    def test_public_schema_remains_untouched(self):
        with self.store._transaction() as cur:
            cur.execute("SELECT count(*) AS count FROM information_schema.tables WHERE table_schema='public'")
            self.assertEqual(cur.fetchone()["count"], 0)
