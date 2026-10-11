# Dedicated CRM reader activation

Code is ready for a separate signed read-only service. It is not started by the bot.
The active bot only gains callback identity metadata; calculator and message flags are unchanged.

1. After callback metadata migration exists, run provision_reader.sql with psql as a database operator. Set CRM_READER_PASSWORD to a new dedicated strong password in the operator environment. The role sees only crm_bridge_source.leads; the view excludes unrelated context keys. The current Render account has CREATE ROLE/CREATE DATABASE rights and must not be used by this reader.
2. Create a separate Python web service from this repository, build `pip install -r requirements.txt`, start `gunicorn 'crm_lab.runtime:create_application()' --bind 0.0.0.0:$PORT --workers 1`. Health path /healthz. Attach a persistent disk at /var/data for the replay ledger.
3. On that reader service set CRM_LIVE_READ_ENABLED=true, CRM_READER_DATABASE_URL (dedicated yossi_crm_reader URL, TLS-verified host, no query), CRM_BRIDGE_KEY_HEX (fresh random 32 bytes encoded as 64 lowercase hex), CRM_REPLAY_PATH=/var/data/replays.sqlite. CRM_DB_CA_PATH defaults to the OS CA bundle; supply the trusted Render database CA file if required. TLS hostname and chain verification must pass; never replace verify-full with require/disable.
4. On the private CRM Site set CRM_LIVE_READ_ENABLED=true, CRM_BRIDGE_ORIGIN=https://<dedicated-reader-host>, matching CRM_BRIDGE_KEY_HEX, CRM_LIVE_OWNER_ID equal to the private owner's authenticated ID. Never put provider/database passwords in the Site or browser. Scope is fixed to glass-leads-v1.
5. In CRM אמיתי click source Refresh. Compare source counts, one selected saved conversation and callback ID. Verify wrong owner, wrong key, replay, failed second page and new callback after completion. No customer messages are needed for these checks.

The tools available in this session support read-only PostgreSQL queries, but not role provisioning or remote shell execution. Sites connector eligibility discovery is unavailable. No production passwords were read or copied. No paid reader service/disk was silently created without a working dedicated reader role.

Existing callbacks without IDs remain explicitly legacy and cannot be marked complete by customer identity alone. New save_callback writes a UUID per source inbound/time generation in the same transaction. Repeated save of the same generation keeps its ID; a new customer inbound, changed requested time or callback after closure receives a new ID. CRM completion stays local and binds to that request ID; it does not update source status or stop/send bot messages. Old individually untimed messages stay untimed.

Still unverified: hosted external reads and visitor-owned production snapshot intake, until the above infrastructure is configured. Browser QA is unavailable in this environment. The fixture CRM's installation/archive/delete workflow is separate from the live reader; live source records are never hard-deleted or rewritten by these routes.
