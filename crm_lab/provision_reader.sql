-- Operator-only setup; never executed by app.py or the CRM. Run after callback columns exist.
-- psql reads the dedicated password from its environment; it never prints the value.
\getenv reader_password CRM_READER_PASSWORD
BEGIN;
CREATE ROLE yossi_crm_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE yossi_crm_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE yossi_crm_reader PASSWORD :'reader_password';
ALTER ROLE yossi_crm_reader SET default_transaction_read_only='on';
ALTER ROLE yossi_crm_reader SET statement_timeout='5s';
CREATE SCHEMA IF NOT EXISTS crm_bridge_source;
CREATE OR REPLACE VIEW crm_bridge_source.leads AS
 SELECT phone,name,product,status,callback_time,notes,updated_at,created_at,last_inbound_at,
 manual_followup_completed_at,callback_request_id,callback_requested_at,conversation,
 jsonb_build_object('validated_quote',context->'validated_quote') AS context FROM public.glass_leads;
REVOKE ALL ON SCHEMA crm_bridge_source FROM PUBLIC;
REVOKE ALL ON crm_bridge_source.leads FROM PUBLIC;
GRANT USAGE ON SCHEMA crm_bridge_source TO yossi_crm_reader;
GRANT SELECT ON crm_bridge_source.leads TO yossi_crm_reader;
SELECT format('GRANT CONNECT ON DATABASE %I TO yossi_crm_reader',current_database())\gexec
COMMIT;
