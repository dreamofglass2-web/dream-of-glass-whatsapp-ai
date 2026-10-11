import os,unittest
from quote_lab.postgres_store import PostgresQuoteStore
from callback_store import save_callback_record
class CallbackIdentityTests(unittest.TestCase):
    def setUp(self):
        self.store=PostgresQuoteStore(os.environ['QUOTE_LAB_TEST_DATABASE_URL'])
        with self.store._transaction() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS glass_leads(phone TEXT PRIMARY KEY,status TEXT,callback_time TEXT,
              name TEXT DEFAULT '',product TEXT DEFAULT '',notes TEXT DEFAULT '',created_at TIMESTAMPTZ DEFAULT now(),
              conversation JSONB DEFAULT '[]',context JSONB DEFAULT '{}',manual_followup_completed_at TIMESTAMPTZ,
              last_inbound_at TIMESTAMPTZ,updated_at TIMESTAMPTZ,callback_request_id TEXT,
              callback_requested_at TIMESTAMPTZ,callback_request_inbound_at TIMESTAMPTZ)''')
            c.execute("DELETE FROM glass_leads WHERE phone='0000000999'")
            c.execute("INSERT INTO glass_leads(phone,status,last_inbound_at) VALUES('0000000999','חדש','2026-10-11T17:00:00Z')")
    def save(self,time='מחר'):
        with self.store._transaction() as c:return save_callback_record(c,'0000000999',time)
    def test_duplicate_save_keeps_id_but_new_inbound_or_request_opens_new_id(self):
        first=self.save();self.assertEqual(first,self.save())
        with self.store._transaction() as c:c.execute("UPDATE glass_leads SET last_inbound_at=last_inbound_at+interval '1 minute' WHERE phone='0000000999'")
        second=self.save();self.assertNotEqual(first,second);self.assertEqual(second,self.save())
        self.assertNotEqual(second,self.save('היום'))
    def test_new_request_after_completion_has_new_identity_and_rollback_is_atomic(self):
        first=self.save()
        with self.store._transaction() as c:c.execute("UPDATE glass_leads SET status='בטיפול',callback_time='' WHERE phone='0000000999'")
        self.assertNotEqual(first,self.save())
        before=self.save()
        with self.assertRaises(RuntimeError):
            with self.store._transaction() as c:save_callback_record(c,'0000000999','שעה אחרת');raise RuntimeError('simulated failure')
        self.assertEqual(before,self.save())

    def test_dedicated_reader_reads_only_the_sanitized_view(self):
        import psycopg2
        from crm_lab.read_source import ReadOnlyLeadSource
        with self.store._transaction() as c:
            c.execute("INSERT INTO glass_leads(phone,name,product,status,callback_time,notes,updated_at,last_inbound_at,context) VALUES('972501234567','לקוח בדיקה','מקלחון','חדש','','',now(),now(),'{\"private_marker\":\"hidden\",\"validated_quote\":{}}') ON CONFLICT(phone) DO NOTHING")
            c.execute('CREATE SCHEMA IF NOT EXISTS crm_bridge_source')
            c.execute("CREATE OR REPLACE VIEW crm_bridge_source.leads AS SELECT phone,name,product,status,callback_time,notes,updated_at,created_at,last_inbound_at,manual_followup_completed_at,callback_request_id,callback_requested_at,conversation,jsonb_build_object('validated_quote',context->'validated_quote') AS context FROM glass_leads WHERE phone='972501234567'")
            c.execute('GRANT USAGE ON SCHEMA crm_bridge_source TO yossi_crm_reader')
            c.execute('GRANT SELECT ON crm_bridge_source.leads TO yossi_crm_reader')
        params={k:self.store._parameters[k] for k in ['host','dbname','user','password','connect_timeout']};params.update(user='yossi_crm_reader',password='disposable-test-only',sslmode='verify-full',connect_timeout=5)
        # Loopback CI PostgreSQL has no TLS certificate. The source configuration
        # must still demand verified TLS; patch only the test connection function.
        original=psycopg2.connect
        from unittest.mock import patch
        def fixture_connection(**kwargs):
            self.assertEqual(kwargs['sslmode'],'verify-full');kwargs['sslmode']='disable';return original(**kwargs)
        with patch('psycopg2.connect',side_effect=fixture_connection):
            source=ReadOnlyLeadSource(live_parameters=params,live_enabled=True)
            result=source.detail(phone='972501234567');self.assertFalse(result['synthetic']);self.assertNotIn('hidden',str(result))
            self.assertEqual(source.page(limit=100)['customers'][0]['source_phone'],'972501234567')
        params['sslmode']='disable'
        connection=original(**params)
        try:
            with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
                with connection:
                    with connection.cursor() as c:c.execute('SELECT * FROM public.glass_leads')
        finally:connection.close()
