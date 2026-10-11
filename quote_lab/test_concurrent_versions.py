"""Real local SQLite contention and rollback tests; no network or production DB."""
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

from quote_lab.durable_store import DurableQuoteStore, QuoteStoreError


class ConcurrentVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "versions.sqlite3"
        self.store = DurableQuoteStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_parallel_creations_are_contiguous_and_durable(self):
        ready = Barrier(12)
        def save(index):
            store = DurableQuoteStore(self.path)
            ready.wait(timeout=10)
            return store.create_draft("quote", f"spec-{index}", "2644", "test")
        with ThreadPoolExecutor(max_workers=12) as pool:
            versions = list(pool.map(save, range(12)))
        self.assertEqual(sorted(versions), list(range(1, 13)))
        history = DurableQuoteStore(self.path).history("quote")
        self.assertEqual(len(history), 12)
        self.assertEqual(len({row["specification"] for row in history}), 12)
        self.assertTrue(all(row["state"] == "draft" for row in history))

    def test_transition_rechecks_latest_after_waiting_for_writer(self):
        self.store.create_draft("quote", "old", "2644", "test")
        writer = sqlite3.connect(self.path)
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("""INSERT INTO quote_lab_versions
            (quote_id,version,specification,price_before_vat,catalog_version)
            VALUES ('quote',2,'new','2884','test')""")
        attempted_lock = Event()
        store = self.store
        original_connect = store._connect
        def tracked_connect():
            connection = original_connect()
            connection.set_trace_callback(
                lambda statement: attempted_lock.set()
                if statement == "BEGIN IMMEDIATE" else None)
            return connection
        store._connect = tracked_connect
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(store.mark_sent, "quote", 1, "test-delivery")
                try:
                    self.assertTrue(attempted_lock.wait(timeout=3))
                finally:
                    writer.commit()
                with self.assertRaises(QuoteStoreError):
                    result.result(timeout=10)
        finally:
            writer.close()
        self.assertEqual([row["state"] for row in store.history("quote")], ["draft", "draft"])
        self.assertIsNone(store.history("quote")[0]["delivery_ref"])

    def test_rejected_transition_rolls_back_and_releases_lock(self):
        self.store.create_draft("quote", "first", "2644", "test")
        with self.assertRaises(QuoteStoreError):
            self.store.mark_approved("quote", 1, "first", "2644", "unverified")
        self.assertEqual(self.store.create_draft("quote", "next", "2884", "test"), 2)
        self.assertEqual(self.store.latest("quote")["state"], "draft")
