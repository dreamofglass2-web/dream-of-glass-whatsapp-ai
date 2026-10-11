"""Isolated durable quote ledger using a local SQLite file.

No CRM, WhatsApp, production Postgres or network connection. Test-only.
A production adapter would require explicit rollout and delivery receipt verification.
"""
import sqlite3
from decimal import Decimal, InvalidOperation


class QuoteStoreError(ValueError):
    pass


class DurableQuoteStore:
    def __init__(self, path):
        self.path = str(path)
        if self.path == ":memory:":
            raise QuoteStoreError("Persistent file path required for durable quote storage")
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS quote_lab_versions (
                quote_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                specification TEXT NOT NULL,
                price_before_vat TEXT NOT NULL,
                catalog_version TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'draft',
                delivery_ref TEXT,
                approval_ref TEXT,
                PRIMARY KEY (quote_id, version)
            )""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_quote_lab_delivery_ref
                ON quote_lab_versions(delivery_ref) WHERE delivery_ref IS NOT NULL""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_quote_lab_approval_ref
                ON quote_lab_versions(approval_ref) WHERE approval_ref IS NOT NULL""")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level="IMMEDIATE")
        db.row_factory = sqlite3.Row
        return db

    def create_draft(self, quote_id, specification, amount, catalog_version):
        if not isinstance(quote_id, str) or not quote_id.strip() or not isinstance(specification, str) or not specification.strip() or not isinstance(catalog_version, str) or not catalog_version.strip():
            raise QuoteStoreError("Missing quote identity, specification or catalog version")
        try:
            value = Decimal(str(amount))
        except (TypeError, InvalidOperation):
            raise QuoteStoreError("Invalid amount") from None
        if not value.is_finite() or value <= 0:
            raise QuoteStoreError("Amount must be positive and finite")
        with self._connect() as db:
            # Lock before reading latest revision; sqlite begins implicitly only on writes.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT COALESCE(MAX(version), 0) FROM quote_lab_versions WHERE quote_id = ?",
                             (quote_id,)).fetchone()
            revision = row[0] + 1
            db.execute("""INSERT INTO quote_lab_versions
                (quote_id, version, specification, price_before_vat, catalog_version)
                VALUES (?, ?, ?, ?, ?)""",
                (quote_id, revision, specification, str(value), catalog_version))
        return revision

    def _transition(self, quote_id, version, target, *, delivery_ref=None,
                    approval_ref=None, specification=None, amount=None):
        with self._connect() as db:
            # Lock before reading latest revision; sqlite begins implicitly only on writes.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT * FROM quote_lab_versions
                WHERE quote_id=? ORDER BY version DESC LIMIT 1""", (quote_id,)).fetchone()
            if row is None or row["version"] != version:
                raise QuoteStoreError("Cannot modify a previous or missing quote version")
            if target == "sent":
                if row["state"] != "draft" or not isinstance(delivery_ref, str) or not delivery_ref.strip():
                    raise QuoteStoreError("Verified delivery reference required")
                try:
                    db.execute("""UPDATE quote_lab_versions SET state='sent', delivery_ref=?
                        WHERE quote_id=? AND version=?""", (delivery_ref, quote_id, version))
                except sqlite3.IntegrityError as error:
                    raise QuoteStoreError("Delivery evidence already used for another quote") from error
            elif target == "approved":
                if row["state"] != "sent" or not isinstance(approval_ref, str) or not approval_ref.strip():
                    raise QuoteStoreError("Explicit approval of delivered quote required")
                try:
                    approved_amount = Decimal(str(amount))
                except (TypeError, InvalidOperation):
                    raise QuoteStoreError("Invalid approved amount") from None
                if not approved_amount.is_finite() or row["specification"] != specification or Decimal(row["price_before_vat"]) != approved_amount:
                    raise QuoteStoreError("Approval must match exact sent price and specification")
                try:
                    db.execute("""UPDATE quote_lab_versions SET state='approved', approval_ref=?
                        WHERE quote_id=? AND version=?""", (approval_ref, quote_id, version))
                except sqlite3.IntegrityError as error:
                    raise QuoteStoreError("Approval evidence already used for another quote") from error
            else:
                raise QuoteStoreError("Unsupported transition")
        return self.latest(quote_id)

    def mark_sent(self, quote_id, version, delivery_ref):
        return self._transition(quote_id, version, "sent", delivery_ref=delivery_ref)

    def mark_approved(self, quote_id, version, specification, amount, approval_ref):
        return self._transition(quote_id, version, "approved",
                                specification=specification, amount=amount,
                                approval_ref=approval_ref)

    def latest(self, quote_id):
        with self._connect() as db:
            row = db.execute("""SELECT * FROM quote_lab_versions
                WHERE quote_id=? ORDER BY version DESC LIMIT 1""", (quote_id,)).fetchone()
        return dict(row) if row is not None else None

    def history(self, quote_id):
        with self._connect() as db:
            rows = db.execute("""SELECT * FROM quote_lab_versions
                WHERE quote_id=? ORDER BY version""", (quote_id,)).fetchall()
        return [dict(row) for row in rows]
