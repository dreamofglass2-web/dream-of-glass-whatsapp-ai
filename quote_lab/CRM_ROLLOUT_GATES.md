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

## Signed status payload verification in the lab

`receipt_verifier.py` verifies HMAC-SHA256 over the original request bytes before
parsing JSON. It rejects duplicate JSON keys and inconsistent known message data,
binds provider message IDs to the intended recipient and exact quote revision,
and scopes statuses to the configured WABA and phone number ID. Only delivered
or read yields delivery evidence; sent, failed, deleted and unknown messages do
not. The parser has no network listener, environment access or database mutation.

`apply_signed_fixture` is an explicit lab-only bridge into `QuoteSimulation`:
account/phone/message/quote identities must be fixture/simulation-prefixed.
Saved fingerprint, amount and latest version must match before transitions.
Bad signed batches are fully validated before the first fixture transition.
There is no cross-quote transaction for concurrent batch application; a retry
must use idempotent per-quote transitions. This is not a live receipt endpoint.

Before live integration, separately implement trusted persistent outbound-message
bindings populated only after an authorized send, durable event ingestion/retry,
account-scoped authorization, and real receipt verification with the protected
server-side app secret. No live send permissions or environment changes are made
by this stage. Existing app.py does not import this verifier.

Provider references reviewed: Meta webhook endpoint payload validation
https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/create-webhook-endpoint/
and Meta's WhatsApp Business Platform payload reference
https://www.postman.com/meta/whatsapp-business-platform/folder/tduohwq/webhook-payload-reference.
# Persistent binding and transaction gate (synthetic only)

The in-memory fixture-binding requirement now has a durable lab implementation:
SQLite `quote_lab_bindings` / `quote_lab_receipt_events` and disposable PostgreSQL
`quote_lab_stage.bindings` / `quote_lab_stage.receipt_events`. No production
migration or app.py integration runs. Scope, recipient, provider-style synthetic
message ID, quote version, fingerprint and exact-cent amount are persisted;
foreign keys bind them to quote history. Message IDs and quote versions cannot
be reassigned through the API. Identical registration retries are idempotent.
Binding digests detect accidental corruption, not malicious database access.

The persistent fixture path supersedes the old bridge's per-quote batch limit:
it verifies signatures before DB access, reloads bindings and locks all affected
quote IDs in sorted order before checking the latest revision and saved snapshot.
Receipt evidence and quote state commit atomically in a single transaction.
If any event is stale or a write fails, every transition in the batch rolls back.
Concurrent duplicates commit one event. A crash before commit leaves a draft;
a lost acknowledgment after commit can be retried without duplicate effects.

This completes the isolated persistence/replay/recovery gate before work on the
CRM interface. It does not finish live integration: real outbound bindings must
come from an explicitly authorized sender; access control, durable raw-event
ingestion and retry/quarantine handling, real recipient/account scoping, and
owner go-live approval still apply. The lab intentionally allows one synthetic
message per quote version and only dummy recipient IDs; it is not a production
outbound-attempt or retry model. Rejected stale events roll back and are not
recorded as successful deliveries; no retry worker is activated.
