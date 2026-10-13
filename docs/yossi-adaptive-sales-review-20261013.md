# Yossi adaptive sales review — 2026-10-13

## Outcome

Keep the current gpt-6-astra sales model. In the observed sample it handled customer experience, practical recommendations and trust concerns better than gpt-4.1-mini. This is not a ranking of all lower-cost models. Deploy the consultation and pricing-boundary repairs after required checks. Readiness is limited to the exercised ordinary shower journeys; this is not proof of error-free handling of every buyer or product.

## Acceptance criteria

- Discover project context and experience/needs before premature technical or price-only replies, unless the customer declines consultation.
- Use the customer's stated experience, including a satisfied previous owner, rather than inventing pain.
- Preserve known specifications and do not treat old-product descriptions as a new selection.
- Give a relevant recommendation and explain why it fits expressed needs, with final site checks.
- Calculate every shower amount using the authoritative engine; before VAT, with inclusions and preliminary/site-measurement scope.
- Acknowledge a customer-stated competitor gap without inventing a new discounted total or disparaging suppliers.
- Respect thinking, joint decisions, no-calls and price-only boundaries.
- No unsupported appointments, documents, warranty or safety promises.

## Root causes and changes

The final customer reply is not simply the model reply. Inspection revealed that natural discovery wording was being replaced by a fixed question; pending price intent could be lost to a model false flag; natural requests such as “תן הצעה” were not recognized; a calculated quote after providing city could be rejected despite complete specifications; and acknowledging a stated price gap could be overwritten by a bare total.

The fix preserves safe natural discovery wording, retains pending customer price intent, recognizes natural offer requests, treats a model quote action only as an intent signal before authoritative calculation, and permits clearly relative customer-evidenced gaps. Known choices survive nontechnical consultation, with exceptions for explicit changes and new jobs. Exact catalog wording aliases are normalized. A strict 17-field JSON schema enforces configuration/glass/finish catalog values and field types within the existing single model call. Sliding configurations are included in the output catalog. Specialist, owner handoff and outbound authorization remain in place.

Current arithmetic: glass + hardware + 1,300 ILS, no 150 buffer or minimum floor, half-up to whole ILS. Issued historical offers are preserved.

## Evidence

210 offline regression tests passed, with both PostgreSQL integration workflows. New tests cover natural wording preservation, pending price flags, experience/current-choice separation, catalog aliases, competitor gap acknowledgement, and city/natural-offer transitions.

Paid observed transcripts in this work: 196 synthetic customer turns and 194 calls with returned usage, across initial comparison and repeated checks. Astra token estimate: $3.157474. Mini estimate ignoring caching: $0.227513. Combined observed estimate: $3.384987. These are not invoices and do not account for unobserved provider retries or calls without usage. Mini rate reference: https://developers.openai.com/api/docs/models/gpt-4.1-mini (2026-10-13: $0.40 input / $0.10 cached / $1.60 output per million). Astra estimates use existing runtime cache-aware usage accounting.

- Initial comparison: run38446297025, Astra job115465460427. 38 recorded turns; stopped by the conservative test budget, not a demonstrated production API failure. Revealed good raw model quotes overwritten by a generic missing-spec question.
- Mini follow-up: run38446847135, job115467356478. 38 turns; five empty/unreadable-output failures in the production parser, repeated known questions and ungrounded claims. A green workflow did not constitute sales acceptance.
- First repaired Astra sample: run38447452071, job115469416731. 24 turns; exposed price-gap text being stripped.
- Strict-contract sample: run38448951516, Astra job115474578860 / Mini job115474578620. Revealed remaining offer-intent/city-transition failures; Astra stopped on the conservative budget near the end. Those turns are not counted as a model-quality runtime fault.
- Final revised intent check: run38449963384. Astra job115478018104: 24 turns, no observed runtime failure, relevant experience discovery and recommendations, 1,964 ILS calculated quote, preserved 400 ILS competitor-gap response, respectful deliberation. Mini job115478018432: 21 turns, one runtime failure and weaker/unbacked recommendations, including linking matte hardware to service concerns.

Six reactive profiles were used initially; final checks focused on price-first, beginner, prior bad service, and rushed/price-only buyers. Manual transcript review was not blinded or statistically powered. Rule-based buyer branching can misinterpret mixed questions and generate artificial repeated prompts; the reusable driver now prioritizes the current question. Specialist handoff, real audio transcription, media transport, production DB and actual customer acceptance were not exercised by these paid transcripts.

## Repeatable testing

tools/yossi_adaptive_sales_tests.py and the manual-only “Yossi adaptive sales acceptance” workflow preserve an opt-in bounded harness. Use a dedicated test key. No WhatsApp/DB credentials are supplied; outbound customer HTTP is blocked. The reusable harness reports runtime failures as failures, then requires manual sales-quality review against the criteria above. No automatic paid runs or customer sends were enabled.

A broader live-customer release requires evidence from a limited operational pilot, including other products and real media, rather than treating these synthetic conversations as a universal guarantee.
