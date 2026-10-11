# Quote CRM rollout gates (design only)

Existing CRM has `glass_leads` and outbound attempts. The live database has no quote-version table at the time of inspection. `design_only_postgres_quotes.sql` is **not** imported or applied.

Before any production use:

1. Review table and retention policy with the owner; perform migration separately with backup and rollback plan.
2. Integrate verified quote calculation, spec fingerprint and customer-safe message snapshot. Never expose vendor costs.
3. A draft alone is not an offer that was delivered. Mark *sent* only on confirmed delivery evidence, not merely a successful API request.
4. Mark *approved* only when customer explicitly accepts the exact delivered price and specification. A changed spec creates a new version.
5. Lock quote revisions transactionally to avoid races. Reject state transitions on old versions.
6. Keep business auto reply and follow-ups disabled. Do not connect the universal calculator to live WhatsApp until owner accepts the full test suite and explicitly approves go-live.

This document is a release design, not proof of successful integration or production-ready migration.

## Offline concurrency validation

The SQLite lab explicitly begins `BEGIN IMMEDIATE` before reading the latest
version for draft allocation and state transitions. Tests exercise simultaneous
writers, a transition waiting behind a new revision, and rollback after rejected
approval. This validates the local ledger only. A future PostgreSQL adapter must
implement equivalent per-quote locking and pass these scenarios in a separate
test database; no production migration has been run.

## Full snapshot persistence in the isolated SQLite lab

Each new workflow draft atomically saves its specification, internal calculation,
customer-safe preview text and payload digest in `quote_lab_snapshots`, alongside
its version metadata. A failed snapshot insert rolls back the revision insert.
The companion table upgrade is local-only and preserves legacy version history.
Metadata-only legacy records require a new calculation; no snapshot is invented.

`restore_offline_quote(store, quote_id)` restores only the latest unsent draft,
verifies the snapshot digest, specification fingerprint, catalog and price,
recalculates offline and checks the exact stored preview text. Sent/approved
history remains available for local inspection and cannot be restored as unsent.
The digest detects accidental corruption, not a substitute for database access
controls or a trusted delivery-verification adapter.

This remains SQLite-only integration. No Postgres adapter, deployment database
migration or live WhatsApp delivery-receipt integration has been activated.

## Disposable PostgreSQL adapter gate

`PostgresQuoteStore` is test-only: it accepts an explicit PostgreSQL URL with a
loopback host and exact database name `quote_lab_test`, overrides the connection
address to 127.0.0.1, and rejects query-string redirection, superusers and roles
that can create databases/roles. It never reads `DATABASE_URL` or connects to Render.
It writes only `quote_lab_stage` in the disposable database, using a limited role.

The `quote-lab-postgres.yml` workflow provisions a fresh PostgreSQL 16 container
and limited login per CI run. No production secrets or URLs are used. Required
integration tests fail if the explicit test URL is missing rather than skipping.

Allocation and state transitions acquire the same per-quote transaction advisory
lock before reading latest state, under READ COMMITTED. Exact-cent amounts,
unique delivery/approval evidence, status constraints and snapshot foreign keys
are enforced. Metadata and full snapshots commit together. Connections are
explicitly closed on success and failure. A disconnected writer rolls back its
partial draft; confirmed latest drafts can be restored through the same workflow
used with SQLite. Test evidence is synthetic and does not prove real delivery.

References: PostgreSQL 16 transaction advisory lock functions
https://www.postgresql.org/docs/16/functions-admin.html and Psycopg transaction
and connection lifecycle https://www.psycopg.org/docs/usage.html.

This passes a disposable database gate only; live CRM migration, tenant access,
verified Meta receipt ingestion, rollout/rollback and owner go-live approval
remain separate requirements. The design-only production SQL is not executed.
