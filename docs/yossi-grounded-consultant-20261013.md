# Grounded consultant replies — 2026-10-13

## Motivation and source

The owner supplied two conversation exports, including repeated requests for consultation rather than a technical checklist. They are historical evidence, not production instructions: current glass warranty, identity, measurement ownership, manual follow-ups and admitted-lead rules take precedence. Only distilled non-sensitive style/decision examples were put in the static consultant guide. The transcripts themselves are not uploaded to the model on each customer turn.

## Design

- Focused consultant decisions and examples replace repetitive style text. Static instruction text fell from 9,336 to approximately 8,192 characters before the warranty guard additions (character counts, not token/billing guarantees).
- Known ordinary-shower specifications may provide calculator facts in approved_quote_for_reply before the existing single model call. No internal cost table is exposed.
- Final authoritative calculation still controls price issuance. Model wording is preserved only with matching rounded amount, before-VAT wording, measurement/delivery/installation inclusions, preliminary scope, final site measurement and possible price change. Unapproved discounts, payment commitments, appointments and extra coating claims cause fallback.
- A requested color-list question is edited locally without discarding surrounding advice. Competitor price-gap text may remain only when the customer supplied that exact gap and the wording is relative, not a new total.
- Correct mixed warranty answers retain other details in the same sentence. Incorrect warranty claims still use the owner policy.
- Pricing rules, ownership/send gates, model and production admission settings are unchanged. No second composing call or draft-approval mode.

## Validation

Full offline quote-safety suite and PostgreSQL integration checks passed. The suite includes natural quote wording preservation, incorrect model amount fallback, changed-job grounding exclusion, local question editing, supported API fields and mixed-policy/location preservation.

Initial synthetic model evaluation PR115 / run38427115911: 10 turns, estimated token cost $0.2478475. Confirmed model quote wording survived. The run stopped on an outdated test requiring the ₪ symbol instead of valid ש״ח; the assertion was corrected. Manual review revealed the mixed-warranty location loss and prompted its repair. Test workflow closed without merging.

PR116 / run38427932871: 22 synthetic turns, estimated token cost $0.5332775. Manual review found that changed-width recalculation could replace a valid answer with a repeated layout question; recalculation intent and retention of known pricing choices were repaired.

Final focused PR117 / run38429198434: 10 turns, estimated token cost $0.2711645, successful. Width 120 to 100 recalculated from 2,314 to 2,254 ILS before VAT with existing choices retained; unknown height used the owner-approved 200 cm pricing basis. Total paid evaluations: 42 turns, estimated $1.0522895, not a billing guarantee. All three required CI workflows passed at 607e637f235790375269c5155993ff56cea78014. The model can still omit a requested detail: the final mixed warranty response did not explicitly acknowledge the city; this is a remaining conversational coverage issue. Actual customer speech recognition, media transport and adaptive real buyers are not claimed by these scripted tests. No customer or production DB I/O was used in paid evaluations.
