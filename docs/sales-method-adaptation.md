# Consultation method adapted from customer-supplied book photographs

Source: supplied excerpts of מאסטר במכירות, שחר קאיקוב. These are selected photographed pages, some cropped, not a complete copy of the book. The implementation paraphrases principles; it does not put book pages, biographies or long scripts into model requests.

| Supplied section | Runtime adaptation |
| --- | --- |
| What selling is, pp.19–21 | Help the customer make an informed choice and understand value. |
| Questions, pp.45–49 | Lead with an accessible, relevant question; follow the answer rather than reciting a checklist. |
| Purchase motive, pp.51–52 | Use the customer's stated practical priorities; do not diagnose motives from keywords. |
| Stages, pp.59–77; script, pp.102–110 | Greeting, discovery, tailored recommendation, informed decision. Adapt to short WhatsApp turns; answer direct questions without forcing a long interview. |
| Rapport, pp.78–83 | Warm, attentive language and accurate reflection. No fake shared background, friendships or identity. Physical posture/voice instructions do not apply to a text bot. |
| Desired outcome and professional confidence, pp.90–100 | Explain a useful outcome in plain language and convey verified competence. Do not invent credentials or guarantees. |
| Objections, pp.112–138 | Acknowledge, clarify what is missing, address it, check understanding. Budget, trust, technical fit, deliberation and joint decisions require different approaches. |
| Alternatives, pp.148–154 | Compare known scope, service and warranty without attacking competitors or repeating comparisons already answered. |
| Decision maker, pp.201–205 | Respect joint decisions and ask neutrally when relevant. Do not presume the payer, speaker, spouse or dominant participant controls the decision. |

Business facts, calculator approval, consent, handoff and the owner-only measurement stage remain authoritative. The method never authorizes false scarcity, pressure, shaming, unsupported engineering, fake discounts or scheduling promises. Customer corrections take priority over old context.

Cost design: one stable compact policy and existing cache boundary; local focus selection with no additional model call; bounded older customer evidence (six excerpts, 180 characters each) and no duplicated recent transcript; compact JSON serialization; API usage grouped by a hashed conversation identifier and customer turn. Character counts are not billed token counts. Cache-aware estimates remain unknown when usage details are missing.

Validation distinguishes infrastructure tests from real sales quality. Offline scripted responses validate request construction and guards, not model persuasiveness. Fresh ordinary-customer test conversations must be reviewed for helpfulness, repetition, accuracy and actual token usage before claiming improvement in conversion or cost.
