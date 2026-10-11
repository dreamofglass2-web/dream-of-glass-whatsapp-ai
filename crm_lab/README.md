# Isolated read-only lead preview

This prepares field/status mapping for the private CRM, without connecting it to
production. app.py does not import this package. No sender, secret/environment
lookup, customer import, production database write or Render setting is added.
An inactive authenticated WSGI bridge is prepared separately; it is not mounted
in app.py and no listener is started. See BRIDGE_REVIEW.md.

`preview_leads` accepts only explicit synthetic rows with dummy 000-prefixed
phones. It preserves source timestamps and stable phone-derived identities,
rejects duplicates instead of merging, and marks incomplete fields and legacy
callback text for manual review. Context and conversations are not exported.
Unknown or closed statuses never imply confirmed delivery, approval, an installed
job or a fabricated quote version. Inactive leads are marked archived explicitly.

`PostgresLeadPreview` uses the existing explicit loopback `quote_lab_test` target
guard and a limited role. It opens a REPEATABLE READ, READ ONLY transaction and
checks that PostgreSQL enforces that mode. It selects only from the synthetic
`crm_preview_stage.leads` fixture table. Its constructor creates no tables and
reads no environment variables. Real glass_leads/Render is never queried.
The test fixture setup is separate from the read-only adapter.

Exports are limited to 300 rows and include `has_more`; a bounded preview is not a
complete migration or synchronization. The new reader supports bounded keyset pages; no worker or schedule exists.
The test table contains the same selected fields as the existing lead schema,
but is not the production table. The existing Site continues with its own demo.

Tests: `python -m unittest discover -s crm_lab -p 'test_*.py' -v` plus the required
disposable PostgreSQL workflow. Existing quote regressions run in the same CI.

Before live activation: approve the exact field list and private read-only bridge,
configure a dedicated least-privilege source reader without changing the active
calculator, authenticate source and destination server-side, add complete bounded
pagination/freshness handling, and keep source records separate from editable
demo records. Never expose DB credentials to the browser or accept visitor-chosen
source/account identifiers. Real quote history must come from verified saved
versions rather than legacy lead statuses. Owner approval is still required for
live customer-data integration and for any customer messaging.

## Prepared bridge

`bridge.py` authenticates GET /v1/leads using an explicit server-only HMAC key,
raw request target, timestamp, nonce and empty-body digest. Freshness is bounded
by 300 seconds. ReplayStore atomically persists used nonces for 601 seconds;
retries require a fresh nonce. Responses bind their signature to request nonce
and source scope. Cursors are signed, scope-bound and expire after 300 seconds.
Queries reject duplicate/unknown fields and limit pages to 300 rows and 1 MB.
A source or replay-store failure fails closed with a redacted error. No cache.

`ReadOnlyLeadSource` defaults to disabled. Tests use only the guarded loopback
fixture database. The separately prepared production branch requires explicit
parameters, verified TLS, a limited role and READ ONLY transactions; it reads
seven fixed public.glass_leads columns and never writes. Nothing configures or
invokes that branch here. No production DB was contacted. The Site has no bridge
consumer yet, and still contains only editable synthetic records.

Each page is a fresh snapshot, not a frozen multi-page export: concurrent inserts
before the cursor can be missed. A later consumer must stage a complete generation,
retain its previous successful generation after failures, and reconcile freshness
before activation. Phone identity assumes the source's unique phone key. Replay
storage must be durable and shared by all bridge instances; independent replica
SQLite files are insufficient. Keys must be separate per source, server-only,
and transmitted over HTTPS. Provisioning the reader, deployment, secrets and
Site activation remain explicit owner-approved production work.
