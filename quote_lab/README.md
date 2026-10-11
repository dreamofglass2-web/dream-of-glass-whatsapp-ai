# Universal quote lab — isolated V1

This is a **test-only** price calculator and is intentionally NOT imported by the live `app.py` or wired to CRM, webhooks, or WhatsApp. Its outputs are draft calculations for review, never customer quotes.

## Owner-approved pricing and rules

- Glass 8 mm vendor cost (ILS/m², ex VAT): clear 150; extra-clear, gray Antisun, Pipita, milky, acid 220; bronze Antisun 240; Galina clear and acid clear 380. Cutting, tempering, holes, polishing included in vendor prices.
- All hardware rates use the 17 existing supplier-cost entries in the approved business inventory. Standard kit templates are a starting point and **not physical certification**.
- Sliding kits are 600 and 1200 ILS vendor cost ex VAT and **include all hardware**. Adding duplicate components to a kit is rejected.
- Quote calculation ex VAT: max(2000, glass supplier cost + hardware retail charge + 1500 + 150). 1500 appears **only once**; 150 is owner-approved contingency. Special hardware finishes use 10% surcharge on hardware. No promise of net profit.
- Removal with disposal is an optional 250 ILS add-on ex VAT only when expressly requested.
- Glass panels priced individually using exact rectangular area; supplier has no minimum area. A step notch has 0 cutting surcharge, billed on **full rectangular blank** but requires verified dimensions. Other nonrectangular glass requires measurement / owner review.
- Typical hinges 2 per ordinary door; 2 wall-glass corner brackets per fixed wall panel. Selection still requires weight, dimensions, fitting feasibility and manufacturer verification. The basic template BOMs are preliminary.
- First quote may be based on estimated measurements with final installation subject to verification. There is no promised quote expiration.
- Only a future CRM workflow, implemented with send confirmation and customer explicit price + specification approval, can mark a quote `sent` or `approved`.

## Out of scope pending rules and approval

Physical pane-to-door mapping, hinge loads and bracing criteria, magnet/seal length and package pricing, structural/custom installations, production-grade fitting validator, durable versioned quote persistence, API integration with the agent, and guaranteed quote-delivery state are not implemented. Unsupported configurations are rejected instead of guessed.

Run offline tests with `python -m unittest discover -s quote_lab -p 'test_*.py' -v`.

### Whole-shower decoration API (offline v2)

Pass `decoration="frosted_stripes"` or `"frosted_middle"` to `Draft`,
`price_proposed_layout`, `create_offline_quote` and the matching preview call.
The design applies to every glass panel at 75 ILS/m² once. Legacy pane tags
are normalized to the same design; conflicting designs are rejected.
`none` adds no design unless a legacy pane tag selects one. To remove a design,
clear both the shower selection and all legacy pane tags.

The customer preview names the design once for the whole shower. Its canonical
fingerprint includes the shower design. The offline catalog version was bumped:
older saved drafts must be recalculated into a new version before previewing.
Existing delivery/approval evidence must never be inherited by that new draft.
No production database migration or WhatsApp integration is performed.

Verified examples before VAT: 80/80 with four clear panels = 2644 ILS,
with either design = 2884 ILS; 90/90 bronze with two doors = 2828 ILS,
with either design = 3098 ILS. Panel splits in tests are illustrative.

### Restart-safe isolated CRM drafts

`create_offline_quote` now returns `customer_preview_text` and persists all
quote content atomically. `restore_offline_quote(store, quote_id)` reconstructs
the current draft after restart without losing specification or customer text.
`store.snapshot(quote_id, version)` reads historical content for local review;
it does not authorize sending. Internal calculation costs stay out of the
customer preview. No live CRM connection is made.

Offline arithmetic comparison with the current `app.py` calculator source
(`test_live_calculator_comparison.py`, without importing or executing the app):

| Case | Current calculator source | Offline calculator | Difference |
| --- | ---: | ---: | ---: |
| 80/80 clear, two fixed + two doors | 2644 | 2644 | 0 |
| 90/90 bronze, two doors | 2828 | 2828 | 0 |
| 90/90 bronze + whole-shower frosted design | 2828 | 3098 | +270 |
| 90/90 bronze + explicitly requested removal | 2828 | 3078 | +250 |
| 90/90 bronze + towel handles | 2928 | 2928 | 0 |

All amounts are ILS before VAT. The current calculator function does not apply
the new design/removal input fields; these differences are expected additions
in the lab, not live price changes. This is a source-level calculation comparison,
not proof that a customer received a price or a measurement was approved.

### Disposable PostgreSQL integration

Run `.github/workflows/quote-lab-postgres.yml` to exercise the real adapter against
an ephemeral PostgreSQL 16 container. It uses a limited role, the loopback-only
`quote_lab_test` database, and a dedicated `quote_lab_stage` schema. To run manually
against an equivalent disposable setup, explicitly set
`QUOTE_LAB_TEST_DATABASE_URL` and run:

```sh
python -m unittest discover -s tests/quote_lab_pg -p 'test_*.py' -v
```

`PostgresQuoteStore(test_database_url)` implements the same create/latest/history,
snapshot, sent/approved interface as the SQLite lab store, so the existing quote
creation and restart workflow can use it unchanged. No application import or live
connection is added. Real integration tests cover exact owner prices, changes,
parallel snapshots, a stale transition waiting behind a new version, duplicate
receipt/approval references, partial-write disconnect, restore and corruption.

### Full synthetic delivery/approval simulation

Run `python -m quote_lab.simulator` for the complete owner review scenario in a
temporary SQLite database. See `OWNER_SIMULATION_REVIEW.md` for Hebrew customer
previews and `owner_simulation_example.json` for the reproducible results.

`QuoteSimulation` binds synthetic message IDs to the exact quote ID, revision,
fingerprint and amount. Queued/accepted/sent/failed transport events never mark a
quote delivered. Synthetic delivered/read receipts can transition a current draft;
approval requires both explicit price and specification acceptance. Receipt and
approval replay is idempotent, including after reconnect. New versions reject old
events and never inherit evidence. Only simulation-prefixed identities and typed
synthetic events are supported. There is no natural-language consent parser.

The same scenario and reconnect/replay tests run on the disposable PostgreSQL
CI database. These are artificial events, not a WhatsApp transport, Meta webhook
verification, CRM production integration, or customer/go-live permission.
