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
