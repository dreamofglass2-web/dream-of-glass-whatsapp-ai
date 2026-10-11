# Isolated read-only lead preview

This prepares field/status mapping for the private CRM, without connecting it to
production. app.py does not import this package. No sender, secret/environment
lookup, HTTP bridge, customer import, database write or Render setting is added.

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
complete migration or synchronization. No pagination worker or schedule exists.
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
