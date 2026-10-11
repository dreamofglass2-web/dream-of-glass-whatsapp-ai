"""Run the same durable receipt contract against real disposable PostgreSQL."""
import os
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
import unittest
import psycopg2

from quote_lab.postgres_receipt_store import PostgresReceiptStore
from quote_lab.durable_store import QuoteStoreError
from quote_lab.test_receipt_ledger import ReceiptLedgerContract


URL = os.environ.get("QUOTE_LAB_TEST_DATABASE_URL")
if not URL:
    raise RuntimeError("Explicit disposable QUOTE_LAB_TEST_DATABASE_URL required; no tests skipped")


class PostgresReceiptLedgerTests(ReceiptLedgerContract, unittest.TestCase):
    def setUp(self):
        self.factory = lambda: PostgresReceiptStore(URL)
        self.store = self.factory()
        self.fixture_setup()

    def test_real_disconnect_after_quote_update_rolls_back_event_and_state(self):
        self.register()
        original = self.store._receipt_transaction
        event_table = self.store._events
        class DisconnectingCursor:
            def __init__(self, cursor): self.cursor = cursor
            def execute(self, sql, params=()):
                if "INSERT INTO " + event_table in sql:
                    self.cursor.connection.close()
                    raise psycopg2.OperationalError("synthetic disconnect before receipt commit")
                return self.cursor.execute(sql,params)
            def fetchone(self): return self.cursor.fetchone()
            def fetchall(self): return self.cursor.fetchall()
        @contextmanager
        def disconnected():
            with original() as cur: yield DisconnectingCursor(cur)
        self.store._receipt_transaction = disconnected
        try:
            with self.assertRaises(psycopg2.Error): self.apply()
        finally:
            self.store._receipt_transaction = original
        again = self.factory()
        self.assertEqual(again.latest(self.identity)["state"],"draft")
        self.assertEqual(again.fixture_event_history(self.message_id),[])
        self.assertEqual(self.apply(store=again)[0]["state"],"sent")
        self.assertEqual(len(again.fixture_event_history(self.message_id)),1)

    def test_waiting_receipt_rechecks_revision_after_writer_commits(self):
        self.register()
        worker = self.factory()
        original = worker._receipt_transaction
        started = Event()
        pids = []
        @contextmanager
        def tracked():
            with original() as cur:
                cur.execute("SELECT pg_backend_pid() AS pid")
                pids.append(cur.fetchone()["pid"])
                started.set()
                yield cur
        worker._receipt_transaction = tracked
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.store._transaction() as cur:
                self.store._lock(cur,self.identity)
                cur.execute("""INSERT INTO quote_lab_stage.versions
                    (quote_id,version,specification,price_before_vat,catalog_version)
                    VALUES (%s,2,'synthetic-new-spec',3098,'test')""",(self.identity,))
                pending = pool.submit(self.apply,store=worker)
                self.assertTrue(started.wait(timeout=3))
                deadline = time.monotonic()+3
                while True:
                    cur.execute("""SELECT count(*) AS waiting FROM pg_locks
                        WHERE pid=%s AND locktype='advisory' AND NOT granted""",(pids[0],))
                    if cur.fetchone()["waiting"]: break
                    if time.monotonic()>=deadline: self.fail("Receipt did not wait for revision lock")
                    time.sleep(0.01)
            with self.assertRaises(QuoteStoreError): pending.result(timeout=10)
        self.assertEqual([row["state"] for row in self.store.history(self.identity)],["draft","draft"])
        self.assertEqual(self.store.fixture_event_history(self.message_id),[])
