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

Focused rerun PR116 is reviewed before final release. Actual customer speech recognition, media transport and adaptive real buyers are not claimed by these scripted tests. No customer or production DB I/O was used in paid evaluations.
