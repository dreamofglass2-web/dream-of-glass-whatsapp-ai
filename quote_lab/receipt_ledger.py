"""Persistent synthetic outbound bindings and atomic receipt application.

SQLite lab only. No environment, sender, HTTP endpoint or real customer IDs.
ReceiptLedger is shared with the explicitly disposable PostgreSQL adapter.
"""
from contextlib import contextmanager
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import sqlite3

from quote_lab.durable_store import DurableQuoteStore, QuoteStoreError, prepare_draft
from quote_lab.receipt_verifier import OutboundBinding, ReceiptError, verify_status_webhook
from quote_lab.simulator import QuoteSimulation
from quote_lab.workflow import restore_offline_quote


def fixture_scope(account_id, phone_number_id):
    if not all(isinstance(value, str) and value.startswith("fixture-")
               and value.removeprefix("fixture-").strip()
               for value in (account_id, phone_number_id)):
        raise ReceiptError("Synthetic account and phone scope required")


def fixture_binding(binding):
    if (not isinstance(binding, OutboundBinding)
            or not isinstance(binding.message_id, str)
            or not binding.message_id.startswith("fixture-wamid-")
            or not binding.message_id.removeprefix("fixture-wamid-").strip()
            or not isinstance(binding.quote_id, str)
            or not binding.quote_id.startswith("simulation-")
            or not isinstance(binding.recipient_id, str)
            or not re.fullmatch(r"000[0-9]{6,17}", binding.recipient_id)
            or type(binding.version) is not int or binding.version <= 0
            or not isinstance(binding.specification_fingerprint, str)
            or not re.fullmatch(r"[0-9a-f]{64}", binding.specification_fingerprint)):
        raise ReceiptError("Synthetic message, recipient and exact quote binding required")
    try:
        value = Decimal(binding.amount)
        if (not value.is_finite() or value <= 0 or value > Decimal("9999999999.99")
                or value != value.quantize(Decimal("0.01"))):
            raise ReceiptError("Binding amount must be positive exact cents")
    except (TypeError, ValueError, InvalidOperation):
        raise ReceiptError("Invalid synthetic binding amount") from None
    return OutboundBinding(binding.message_id, binding.recipient_id, binding.quote_id,
                           binding.version, binding.specification_fingerprint, format(value, ".2f"))


def binding_digest(binding, account_id, phone_number_id):
    payload = json.dumps([account_id, phone_number_id, asdict(binding)],
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


class ReceiptLedger:
    """Backend-neutral ledger operations. All writes share quote revision locks."""

    def _sql(self, cur, sql, values=()):
        cur.execute(sql.replace("?", self._parameter), values)

    def _init_receipts(self):
        with self._receipt_transaction() as cur:
            self._receipt_schema_lock(cur)
            self._sql(cur, f"""CREATE TABLE IF NOT EXISTS {self._bindings} (
                message_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                phone_number_id TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                quote_id TEXT NOT NULL,
                version INTEGER NOT NULL CHECK (version > 0),
                specification_fingerprint TEXT NOT NULL,
                amount TEXT NOT NULL,
                binding_sha256 TEXT NOT NULL,
                UNIQUE (quote_id,version),
                FOREIGN KEY (quote_id,version) REFERENCES {self._versions}(quote_id,version)
            )""")
            self._sql(cur, f"""CREATE TABLE IF NOT EXISTS {self._events} (
                event_key TEXT PRIMARY KEY,
                message_id TEXT NOT NULL REFERENCES {self._bindings}(message_id),
                status TEXT NOT NULL CHECK (status IN ('delivered','read')),
                provider_timestamp TEXT NOT NULL
            )""")

    def _decode_binding(self, row):
        binding = fixture_binding(OutboundBinding(*(row[name] for name in (
            "message_id", "recipient_id", "quote_id", "version", "specification_fingerprint", "amount"))))
        fixture_scope(row["account_id"], row["phone_number_id"])
        if binding_digest(binding, row["account_id"], row["phone_number_id"]) != row["binding_sha256"]:
            raise ReceiptError("Saved outbound binding integrity check failed")
        return binding

    def _bound_quote(self, cur, binding):
        self._sql(cur, f"SELECT * FROM {self._versions} WHERE quote_id=? ORDER BY version DESC LIMIT 1",
                  (binding.quote_id,))
        row = cur.fetchone()
        if (row is None or row["version"] != binding.version
                or row["specification"] != binding.specification_fingerprint
                or Decimal(row["price_before_vat"]) != Decimal(binding.amount)):
            raise QuoteStoreError("Binding references an old, missing or different quote")
        self._sql(cur, f"SELECT * FROM {self._snapshots} WHERE quote_id=? AND version=?",
                  (binding.quote_id, binding.version))
        snapshot = cur.fetchone()
        if (snapshot is None or hashlib.sha256(snapshot["payload_json"].encode()).hexdigest()
                != snapshot["payload_sha256"]):
            raise QuoteStoreError("Full intact quote snapshot required")
        try:
            prepare_draft(binding.quote_id, row["specification"], binding.amount,
                          row["catalog_version"], json.loads(snapshot["payload_json"]))
        except (TypeError, ValueError) as error:
            raise QuoteStoreError("Saved quote snapshot differs from outbound binding") from error
        result = dict(row)
        result["price_before_vat"] = format(Decimal(result["price_before_vat"]), ".2f")
        return result

    def register_fixture_binding(self, binding, *, account_id, phone_number_id):
        """Persist one immutable synthetic outbound message per quote version.

        Registering is not delivery evidence or send permission. An identical
        retry is allowed; any reassignment of a message or version is rejected.
        """
        fixture_scope(account_id, phone_number_id)
        binding = fixture_binding(binding)
        digest = binding_digest(binding, account_id, phone_number_id)
        with self._receipt_transaction() as cur:
            self._receipt_quote_lock(cur, binding.quote_id)
            self._sql(cur, f"SELECT * FROM {self._bindings} WHERE message_id=? OR (quote_id=? AND version=?)",
                      (binding.message_id, binding.quote_id, binding.version))
            existing = cur.fetchone()
            if existing is not None:
                if (self._decode_binding(existing) != binding
                        or existing["account_id"] != account_id
                        or existing["phone_number_id"] != phone_number_id):
                    raise ReceiptError("Outbound message or quote version already has an immutable binding")
                return binding
            # The offline workflow recalculates and validates the customer preview.
            # Quote lock is already held, so a concurrent revision cannot pass it.
            restore_offline_quote(self, binding.quote_id)
            row = self._bound_quote(cur, binding)
            if row["state"] != "draft":
                raise QuoteStoreError("Only an unsent synthetic draft can acquire a binding")
            try:
                self._sql(cur, f"""INSERT INTO {self._bindings}
                    (message_id,account_id,phone_number_id,recipient_id,quote_id,version,
                     specification_fingerprint,amount,binding_sha256) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (binding.message_id, account_id, phone_number_id, binding.recipient_id,
                     binding.quote_id, binding.version, binding.specification_fingerprint, binding.amount, digest))
            except self._receipt_integrity_error as error:
                raise ReceiptError("Outbound message or quote version already bound") from error
        return binding

    def saved_fixture_bindings(self, *, account_id, phone_number_id):
        fixture_scope(account_id, phone_number_id)
        with self._receipt_transaction() as cur:
            return self._scoped_bindings(cur, account_id, phone_number_id)

    def _scoped_bindings(self, cur, account_id, phone_number_id):
        self._sql(cur, f"SELECT * FROM {self._bindings} WHERE account_id=? AND phone_number_id=? ORDER BY message_id",
                  (account_id, phone_number_id))
        return [self._decode_binding(row) for row in cur.fetchall()]

    def apply_persisted_fixture(self, raw_body, signature, *, app_secret, account_id, phone_number_id):
        """Verify using persisted bindings, then atomically commit the whole batch.

        Quote transitions and the duplicate-event ledger use the same transaction.
        Any stale binding, integrity failure or interrupted insert rolls back all
        transitions. Reconnect and retry requires no caller-held binding objects.
        """
        fixture_scope(account_id, phone_number_id)
        # Authenticate bytes before opening a database connection.
        verify_status_webhook(raw_body, signature, app_secret=app_secret,
                              account_id=account_id, phone_number_id=phone_number_id, bindings=[])
        with self._receipt_transaction() as cur:
            bindings = self._scoped_bindings(cur, account_id, phone_number_id)
            receipts = verify_status_webhook(raw_body, signature, app_secret=app_secret,
                                             account_id=account_id, phone_number_id=phone_number_id,
                                             bindings=bindings)
            # Stable lock ordering prevents deadlocks on multi-quote batches.
            for quote_id in sorted({receipt.binding.quote_id for receipt in receipts}):
                self._receipt_quote_lock(cur, quote_id)
            results = []
            for receipt in receipts:
                binding = receipt.binding
                row = self._bound_quote(cur, binding)
                delivery_ref = QuoteSimulation._message_id(row)
                if row["state"] == "draft":
                    self._sql(cur, f"UPDATE {self._versions} SET state='sent',delivery_ref=? WHERE quote_id=? AND version=?",
                              (delivery_ref, binding.quote_id, binding.version))
                    row.update(state="sent", delivery_ref=delivery_ref)
                elif row["state"] not in ("sent", "approved") or row["delivery_ref"] != delivery_ref:
                    raise QuoteStoreError("Quote has inconsistent delivery evidence")
                event_key = hashlib.sha256(json.dumps([account_id, phone_number_id,
                    binding.message_id, receipt.status, receipt.timestamp], separators=(",", ":")).encode()).hexdigest()
                self._sql(cur, f"""INSERT INTO {self._events}
                    (event_key,message_id,status,provider_timestamp) VALUES (?,?,?,?)
                    ON CONFLICT (event_key) DO NOTHING""",
                    (event_key, binding.message_id, receipt.status, receipt.timestamp))
                results.append(row)
        return results

    def fixture_event_history(self, message_id):
        with self._receipt_transaction() as cur:
            self._sql(cur, f"SELECT * FROM {self._events} WHERE message_id=? ORDER BY provider_timestamp,status",
                      (message_id,))
            return [dict(row) for row in cur.fetchall()]


class PersistentReceiptStore(ReceiptLedger, DurableQuoteStore):
    def __init__(self, path):
        super().__init__(path)
        self._parameter = "?"
        self._versions, self._snapshots = "quote_lab_versions", "quote_lab_snapshots"
        self._bindings, self._events = "quote_lab_bindings", "quote_lab_receipt_events"
        self._receipt_integrity_error = sqlite3.IntegrityError
        self._init_receipts()

    @contextmanager
    def _receipt_transaction(self):
        db = self._connect()
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                yield db.cursor()
        finally:
            db.close()

    @staticmethod
    def _receipt_schema_lock(cur):
        pass  # BEGIN IMMEDIATE serializes schema and quote writers.

    @staticmethod
    def _receipt_quote_lock(cur, quote_id):
        pass  # Same BEGIN IMMEDIATE lock used by DurableQuoteStore revisions.
