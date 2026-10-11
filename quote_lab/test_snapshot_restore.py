"""Offline CRM integration: complete snapshots, revisions, rollback and restart."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from quote_lab.builder import NamedPanel
from quote_lab.durable_store import DurableQuoteStore, QuoteStoreError
from quote_lab.workflow import create_offline_quote, restore_offline_quote


class SnapshotRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "isolated-crm.sqlite3"
        self.store = DurableQuoteStore(self.path)
        self.panels = [NamedPanel("door", 90, 200, "אנטיסן ברונזה")] * 2

    def tearDown(self):
        self.temp.cleanup()

    def create(self, quote_id="test-lead", panels=None, **changes):
        return create_offline_quote(self.store, quote_id, "פינתי 2 דלתות",
                                    panels or self.panels, layout_confirmed=True, **changes)

    def restart(self):
        self.store = DurableQuoteStore(self.path)
        return restore_offline_quote(self.store, "test-lead")

    def test_full_record_and_customer_text_survive_restart(self):
        draft = self.create(decoration="frosted_middle")
        self.assertEqual(self.restart(), draft)
        payload = self.store.snapshot("test-lead")["snapshot"]
        self.assertEqual(len(payload["specification"]["panels"]), 2)
        self.assertEqual(payload["specification"]["decoration"], "frosted_middle")
        self.assertEqual(payload["customer_preview_text"].count("חלבי באמצע"), 1)
        self.assertIn("3,098.00", payload["customer_preview_text"])
        for internal in ["glass_supplier_cost", "hardware_supplier", "864.00", "314.00"]:
            self.assertNotIn(internal, payload["customer_preview_text"])
        self.assertFalse(draft["can_send_whatsapp"])

    def test_sales_changes_preserve_history_without_inheriting_approval(self):
        versions = [self.create()]
        self.store.mark_sent("test-lead", 1, "test-delivered-original")
        self.store.mark_approved("test-lead", 1, versions[0]["specification_fingerprint"],
                                 "2828.00", "test-approval-original")
        glass = [NamedPanel("door", 90, 200, "אקסטרה קליר")] * 2
        versions.append(self.create(panels=glass))
        versions.append(self.create(panels=glass, handle_style="ידית מגבת"))
        versions.append(self.create(panels=glass, handle_style="ידית מגבת",
                                    decoration="frosted_stripes"))
        versions.append(self.create(panels=glass, handle_style="ידית מגבת",
                                    decoration="frosted_stripes", demolition_and_disposal=True))
        self.assertEqual([v["price_before_vat"] for v in versions],
                         ["2828.00", "2756.00", "2856.00", "3126.00", "3376.00"])
        self.assertEqual(self.restart(), versions[-1])
        for index, draft in enumerate(versions, 1):
            stored = self.store.snapshot("test-lead", index)
            self.assertEqual(stored["snapshot"]["customer_preview_text"], draft["customer_preview_text"])
            if index > 1:
                self.assertEqual(stored["state"], "draft")
                self.assertIsNone(stored["delivery_ref"])
                self.assertIsNone(stored["approval_ref"])
        with self.assertRaises(QuoteStoreError):
            self.store.mark_approved("test-lead", 5, versions[0]["specification_fingerprint"],
                                     "2828", "test-approval-original")

    def test_sent_and_approved_records_cannot_restore_as_unsent(self):
        draft = self.create()
        self.store.mark_sent("test-lead", 1, "test-delivery")
        with self.assertRaises(QuoteStoreError):
            self.restart()
        self.store.mark_approved("test-lead", 1, draft["specification_fingerprint"],
                                 draft["price_before_vat"], "test-approval")
        with self.assertRaises(QuoteStoreError):
            self.restart()
        self.assertEqual(self.store.snapshot("test-lead")["state"], "approved")

    def test_legacy_database_upgrade_preserves_metadata_and_requires_recalculation(self):
        path = Path(self.temp.name) / "legacy.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TABLE quote_lab_versions (
                quote_id TEXT NOT NULL, version INTEGER NOT NULL, specification TEXT NOT NULL,
                price_before_vat TEXT NOT NULL, catalog_version TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'draft', delivery_ref TEXT, approval_ref TEXT,
                PRIMARY KEY (quote_id,version))""")
            db.execute("INSERT INTO quote_lab_versions VALUES ('legacy',1,'spec','2644','v1','approved','delivery','approval')")
        upgraded = DurableQuoteStore(path)
        self.assertEqual(upgraded.latest("legacy")["state"], "approved")
        self.assertEqual(upgraded.latest("legacy")["approval_ref"], "approval")
        with self.assertRaises(QuoteStoreError):
            restore_offline_quote(upgraded, "legacy")
        new = create_offline_quote(upgraded, "legacy", "פינתי 2 דלתות", self.panels,
                                   layout_confirmed=True)
        self.assertEqual(new["version"], 2)
        self.assertEqual(restore_offline_quote(upgraded, "legacy"), new)

    def test_snapshot_write_failure_rolls_back_revision_and_recovers(self):
        original = self.create()
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TRIGGER simulated_disk_failure BEFORE INSERT ON quote_lab_snapshots
                BEGIN SELECT RAISE(ABORT, 'test snapshot storage failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.create(decoration="frosted_stripes")
        self.assertEqual(len(self.store.history("test-lead")), 1)
        self.assertEqual(self.restart(), original)
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER simulated_disk_failure")
        recovered = self.create(decoration="frosted_stripes")
        self.assertEqual(recovered["version"], 2)
        self.assertEqual(self.restart(), recovered)

    def tamper(self, change, *, rehash=False):
        with sqlite3.connect(self.path) as db:
            payload, = db.execute("SELECT payload_json FROM quote_lab_snapshots").fetchone()
            snapshot = json.loads(payload)
            change(snapshot)
            payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if rehash:
                db.execute("UPDATE quote_lab_snapshots SET payload_json=?,payload_sha256=?",
                           (payload, hashlib.sha256(payload.encode()).hexdigest()))
            else:
                db.execute("UPDATE quote_lab_snapshots SET payload_json=?", (payload,))

    def test_snapshot_corruption_is_rejected(self):
        self.create()
        self.tamper(lambda s: s.update(customer_preview_text="tampered text"))
        with self.assertRaises(QuoteStoreError):
            self.restart()

    def test_rehashed_wrong_customer_text_is_rejected(self):
        self.create()
        self.tamper(lambda s: s.update(customer_preview_text="incorrect quote"), rehash=True)
        with self.assertRaises(QuoteStoreError):
            self.restart()

    def test_rehashed_calculation_mutation_is_rejected(self):
        self.create()
        self.tamper(lambda s: s["calculation"].update(price_before_vat="1.00"), rehash=True)
        with self.assertRaises(QuoteStoreError):
            self.restart()

    def test_metadata_tampering_and_stale_catalog_are_rejected(self):
        self.create()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE quote_lab_versions SET price_before_vat='1.00'")
        with self.assertRaises(QuoteStoreError):
            self.restart()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE quote_lab_versions SET price_before_vat='2828.00',catalog_version='old'")
        with self.assertRaises(QuoteStoreError):
            self.restart()

    def test_mismatched_snapshot_cannot_be_written(self):
        self.create()
        snapshot = self.store.snapshot("test-lead")["snapshot"]
        with self.assertRaises(QuoteStoreError):
            self.store.create_draft("other", "wrong-fingerprint", "2828.00", "catalog", snapshot=snapshot)
        self.assertIsNone(self.store.latest("other"))

    def test_parallel_full_snapshots_remain_bound_to_their_versions(self):
        ready = Barrier(8)
        def create(index):
            ready.wait(timeout=10)
            return self.create(decoration="frosted_stripes" if index % 2 else "none")
        with ThreadPoolExecutor(max_workers=8) as pool:
            records = list(pool.map(create, range(8)))
        self.assertEqual(sorted(r["version"] for r in records), list(range(1, 9)))
        for record in records:
            saved = self.store.snapshot("test-lead", record["version"])
            self.assertEqual(saved["specification"], record["specification_fingerprint"])
            self.assertEqual(saved["snapshot"]["customer_preview_text"], record["customer_preview_text"])
        latest = max(records, key=lambda r: r["version"])
        self.assertEqual(self.restart(), latest)
