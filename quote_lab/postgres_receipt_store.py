"""Synthetic receipt ledger on the guarded disposable PostgreSQL database only."""
from quote_lab.postgres_store import PostgresQuoteStore
from quote_lab.receipt_ledger import ReceiptLedger


class PostgresReceiptStore(ReceiptLedger, PostgresQuoteStore):
    def __init__(self, test_database_url):
        super().__init__(test_database_url)
        self._parameter = "%s"
        self._versions, self._snapshots = "quote_lab_stage.versions", "quote_lab_stage.snapshots"
        self._bindings, self._events = "quote_lab_stage.bindings", "quote_lab_stage.receipt_events"
        self._receipt_integrity_error = self._driver.IntegrityError
        self._init_receipts()

    def _receipt_transaction(self):
        return self._transaction()

    @staticmethod
    def _receipt_schema_lock(cur):
        cur.execute("SELECT pg_advisory_xact_lock(7819462011)")

    def _receipt_quote_lock(self, cur, quote_id):
        self._lock(cur, quote_id)
