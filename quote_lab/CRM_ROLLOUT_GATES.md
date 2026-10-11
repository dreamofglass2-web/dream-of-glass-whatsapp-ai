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
