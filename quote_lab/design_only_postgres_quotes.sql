-- DESIGN ONLY. NOT EXECUTED ON PRODUCTION DATABASE.
-- Yossi quote version records, independent of glass_leads.context JSON.
-- Application migrations and explicit owner rollout approval are required.
-- Do not treat calculated drafts as sent or customer-approved offers.

CREATE TABLE IF NOT EXISTS yossi_quote_versions (
    quote_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    lead_phone TEXT NOT NULL,
    specification_sha256 TEXT NOT NULL,
    specification_snapshot JSONB NOT NULL,
    catalog_version TEXT NOT NULL,
    amount_before_vat NUMERIC(12,2) NOT NULL CHECK (amount_before_vat > 0),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','sent','approved')),
    verified_delivery_reference TEXT,
    explicit_customer_approval_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ,
    approved_at TIMESTAMPTZ,
    PRIMARY KEY (quote_id,version),
    CONSTRAINT quote_status_evidence CHECK (
        (status='draft' AND verified_delivery_reference IS NULL AND
         explicit_customer_approval_reference IS NULL AND sent_at IS NULL AND approved_at IS NULL)
        OR
        (status='sent' AND verified_delivery_reference IS NOT NULL AND
         explicit_customer_approval_reference IS NULL AND sent_at IS NOT NULL AND approved_at IS NULL)
        OR
        (status='approved' AND verified_delivery_reference IS NOT NULL AND
         explicit_customer_approval_reference IS NOT NULL AND sent_at IS NOT NULL AND approved_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_yossi_quote_delivery_reference
    ON yossi_quote_versions(verified_delivery_reference)
    WHERE verified_delivery_reference IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_yossi_quote_lead_created
    ON yossi_quote_versions(lead_phone, created_at DESC);

-- Application MUST transition statuses within a transaction, after
-- independently checking the verified delivery receipt or explicit approval.
-- Application MUST reject transitions on non-latest quote versions and must
-- recompute the spec hash from canonicalized customer-approved fields.
-- Never expose specification cost internals in customer-facing messages.
-- This file is not wired to any automatic migration tooling.
