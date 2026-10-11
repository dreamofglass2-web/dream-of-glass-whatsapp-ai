"""Disposable localhost PostgreSQL quote integration only.

Requires an explicit URL for database quote_lab_test on loopback. No environment
fallback, live Render connection, WhatsApp sender, or production migration.
"""
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import hashlib
import json
from urllib.parse import urlsplit, unquote

from quote_lab.durable_store import QuoteStoreError, prepare_draft


def test_database_parameters(url):
    """Reject remote/prod targets before importing a driver or opening a socket."""
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in ("postgres", "postgresql")
                or parsed.hostname not in ("localhost", "127.0.0.1")
                or unquote(parsed.path) != "/quote_lab_test"
                or parsed.query or parsed.fragment or not parsed.username):
            raise ValueError
        return {"host": "127.0.0.1", "hostaddr": "127.0.0.1",
                "port": parsed.port or 5432, "dbname": "quote_lab_test",
                "user": unquote(parsed.username), "password": unquote(parsed.password or ""),
                "connect_timeout": 5, "application_name": "quote_lab_disposable_test"}
    except (TypeError, ValueError, AttributeError):
        raise QuoteStoreError("Explicit loopback quote_lab_test PostgreSQL URL required") from None


class PostgresQuoteStore:
    def __init__(self, test_database_url):
        self._parameters = test_database_parameters(test_database_url)
        # Import lazily: pure offline lab and target validation need no DB dependency.
        import psycopg2
        from psycopg2.extras import RealDictCursor
        self._driver = psycopg2
        self._cursor_factory = RealDictCursor
        with self._transaction() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(7819462011)")
            cur.execute("CREATE SCHEMA IF NOT EXISTS quote_lab_stage")
            cur.execute("""CREATE TABLE IF NOT EXISTS quote_lab_stage.versions (
                quote_id TEXT NOT NULL CHECK (btrim(quote_id) <> ''),
                version INTEGER NOT NULL CHECK (version > 0),
                specification TEXT NOT NULL CHECK (btrim(specification) <> ''),
                price_before_vat NUMERIC(12,2) NOT NULL CHECK (
                    price_before_vat > 0 AND price_before_vat <> 'NaN'::numeric),
                catalog_version TEXT NOT NULL CHECK (btrim(catalog_version) <> ''),
                state TEXT NOT NULL DEFAULT 'draft' CHECK (state IN ('draft','sent','approved')),
                delivery_ref TEXT UNIQUE CHECK (btrim(delivery_ref) <> ''),
                approval_ref TEXT UNIQUE CHECK (btrim(approval_ref) <> ''),
                PRIMARY KEY (quote_id,version),
                CHECK ((state='draft' AND delivery_ref IS NULL AND approval_ref IS NULL)
                    OR (state='sent' AND delivery_ref IS NOT NULL AND approval_ref IS NULL)
                    OR (state='approved' AND delivery_ref IS NOT NULL AND approval_ref IS NOT NULL))
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS quote_lab_stage.snapshots (
                quote_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                PRIMARY KEY (quote_id,version),
                FOREIGN KEY (quote_id,version) REFERENCES quote_lab_stage.versions(quote_id,version)
            )""")

    @contextmanager
    def _transaction(self):
        connection = self._driver.connect(**self._parameters)
        try:
            connection.set_session(isolation_level="READ COMMITTED")
            with connection:
                with connection.cursor(cursor_factory=self._cursor_factory) as cur:
                    cur.execute("SET LOCAL statement_timeout = '10s'")
                    cur.execute("SET LOCAL lock_timeout = '5s'")
                    cur.execute("""SELECT current_database() AS name, rolsuper, rolcreatedb, rolcreaterole
                        FROM pg_roles WHERE rolname=current_user""")
                    target = cur.fetchone()
                    if (target["name"] != "quote_lab_test" or target["rolsuper"]
                            or target["rolcreatedb"] or target["rolcreaterole"]):
                        raise QuoteStoreError("Disposable test database and limited role required")
                    yield cur
        finally:
            connection.close()

    @staticmethod
    def _lock(cur, quote_id):
        # All writers for this quote use the same transaction-scoped lock.
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    ("quote_lab_stage:" + quote_id,))

    @staticmethod
    def _record(row):
        if row is None:
            return None
        result = dict(row)
        result["price_before_vat"] = format(result["price_before_vat"], ".2f")
        return result

    def create_draft(self, quote_id, specification, amount, catalog_version, *, snapshot=None):
        value, payload = prepare_draft(quote_id, specification, amount, catalog_version, snapshot)
        if value > Decimal("9999999999.99") or value != value.quantize(Decimal("0.01")):
            raise QuoteStoreError("PostgreSQL quote amount must fit exact cents")
        with self._transaction() as cur:
            self._lock(cur, quote_id)
            cur.execute("SELECT COALESCE(MAX(version),0)+1 AS next FROM quote_lab_stage.versions WHERE quote_id=%s",
                        (quote_id,))
            revision = cur.fetchone()["next"]
            cur.execute("""INSERT INTO quote_lab_stage.versions
                (quote_id,version,specification,price_before_vat,catalog_version)
                VALUES (%s,%s,%s,%s,%s)""", (quote_id, revision, specification, value, catalog_version))
            if payload is not None:
                cur.execute("""INSERT INTO quote_lab_stage.snapshots
                    (quote_id,version,payload_json,payload_sha256) VALUES (%s,%s,%s,%s)""",
                    (quote_id, revision, payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()))
        return revision

    def _transition(self, quote_id, version, target, *, delivery_ref=None,
                    approval_ref=None, specification=None, amount=None):
        try:
            with self._transaction() as cur:
                self._lock(cur, quote_id)
                cur.execute("SELECT * FROM quote_lab_stage.versions WHERE quote_id=%s ORDER BY version DESC LIMIT 1",
                            (quote_id,))
                row = cur.fetchone()
                if row is None or row["version"] != version:
                    raise QuoteStoreError("Cannot modify a previous or missing quote version")
                if target == "sent":
                    if row["state"] != "draft" or not isinstance(delivery_ref, str) or not delivery_ref.strip():
                        raise QuoteStoreError("Verified delivery reference required")
                    cur.execute("""UPDATE quote_lab_stage.versions SET state='sent',delivery_ref=%s
                        WHERE quote_id=%s AND version=%s RETURNING *""", (delivery_ref, quote_id, version))
                elif target == "approved":
                    if row["state"] != "sent" or not isinstance(approval_ref, str) or not approval_ref.strip():
                        raise QuoteStoreError("Explicit approval of delivered quote required")
                    try:
                        approved_amount = Decimal(str(amount))
                    except (TypeError, InvalidOperation):
                        raise QuoteStoreError("Invalid approved amount") from None
                    if (not approved_amount.is_finite() or row["specification"] != specification
                            or row["price_before_vat"] != approved_amount):
                        raise QuoteStoreError("Approval must match exact sent price and specification")
                    cur.execute("""UPDATE quote_lab_stage.versions SET state='approved',approval_ref=%s
                        WHERE quote_id=%s AND version=%s RETURNING *""", (approval_ref, quote_id, version))
                else:
                    raise QuoteStoreError("Unsupported transition")
                result = self._record(cur.fetchone())
        except self._driver.IntegrityError:
            raise QuoteStoreError("Delivery or approval evidence already used or invalid") from None
        return result

    def mark_sent(self, quote_id, version, delivery_ref):
        return self._transition(quote_id, version, "sent", delivery_ref=delivery_ref)

    def mark_approved(self, quote_id, version, specification, amount, approval_ref):
        return self._transition(quote_id, version, "approved", specification=specification,
                                amount=amount, approval_ref=approval_ref)

    def latest(self, quote_id):
        with self._transaction() as cur:
            cur.execute("SELECT * FROM quote_lab_stage.versions WHERE quote_id=%s ORDER BY version DESC LIMIT 1",
                        (quote_id,))
            return self._record(cur.fetchone())

    def history(self, quote_id):
        with self._transaction() as cur:
            cur.execute("SELECT * FROM quote_lab_stage.versions WHERE quote_id=%s ORDER BY version", (quote_id,))
            return [self._record(row) for row in cur.fetchall()]

    def snapshot(self, quote_id, version=None):
        with self._transaction() as cur:
            cur.execute("""SELECT v.*, s.payload_json, s.payload_sha256
                FROM quote_lab_stage.versions v LEFT JOIN quote_lab_stage.snapshots s
                  ON s.quote_id=v.quote_id AND s.version=v.version
                WHERE v.quote_id=%s AND (%s IS NULL OR v.version=%s)
                ORDER BY v.version DESC LIMIT 1""", (quote_id, version, version))
            row = cur.fetchone()
        if row is None or row["payload_json"] is None:
            raise QuoteStoreError("Full snapshot unavailable; recalculate a new draft")
        if hashlib.sha256(row["payload_json"].encode("utf-8")).hexdigest() != row["payload_sha256"]:
            raise QuoteStoreError("Stored snapshot integrity check failed")
        result = self._record(row)
        try:
            result["snapshot"] = json.loads(result.pop("payload_json"))
        except (TypeError, ValueError):
            raise QuoteStoreError("Unreadable stored snapshot") from None
        return result
