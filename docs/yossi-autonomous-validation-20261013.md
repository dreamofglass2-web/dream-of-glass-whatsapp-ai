# Yossi autonomous consultation validation — 2026-10-13

Production remains autonomous for explicitly admitted simulation contacts; broad business auto-reply stays disabled. No owner-approval/draft mode was introduced.

## Owner-confirmed policy

- No warranty on glass. Shower hardware 7 years; installation 1 year.
- When no measured shower height is available, an initial quote may use 200 cm. Explain final on-site measurement and possible price changes.
- Normal introduction: Yossi from Dream of Glass; truthful digital identity on request.
- Customer-facing quote wording: accurate or preliminary, rather than verified.

## Fixed conversation and runtime gaps

- Mixed warranty questions preserve the product/location request.
- Source CRM retains the inbound that triggers escalation.
- Model input includes supported role/content fields only; CRM timestamps remain in storage.
- Ordinary calculable quote does not automatically escalate from model uncertainty; professional/unknown payment and business-policy requests still pause.
- Issued quotes clear the pending-price flag. Negotiation and deliberation retain the model's consultation rather than a generic calculator message.
- Callback opt-out recognises 'לא רוצה שתחזרו אליי'.
- Indirect visual requests use approved catalog entries; unavailable or mismatched examples are described honestly.
- Negative photo requests suppress catalog and handle images.
- Prompt guidance covers needs before technical selection, optional site photos, no repeated known facts, a new-room context check, and no requests to measure a shower head to progress with initial pricing.

## Evaluation record

- PR111: production consultation and fixed offline regressions.
- Test-only PR112 / run38418768436: 42 real model turns across 10 synthetic scenarios, token estimate $1.03028. HTTP customer delivery blocked, production database disconnected. Initial manual review found post-quote overwrite and callback opt-out gaps; neither is marked accepted merely because the workflow succeeded.
- Test-only PR113: focused real-model retest of discount, injection-price and busy-customer conversations; results will be recorded after review.
- Fixed offline cases validate API fields for every model-bound history and cover media rejection, media failure, owner pause/return and known quote state.

## Practical limits

Real-model tests use scripted customers and fake storage/delivery, not adaptive real buyers or a complete WhatsApp transport test. 'audio_ambiguity' exercises a transcription-shaped text error, not speech recognition. Catalog images are synthetic metadata and are never downloaded or sent to people. Existing dedicated audio/admission and PostgreSQL suites cover their respective seams. A pilot still needs real voice/image and signed owner-control checks, monitoring, and conversion/error review. Passing tests does not guarantee all possible conversations or zero errors.
