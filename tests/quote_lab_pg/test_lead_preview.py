import os
import unittest
from uuid import uuid4
from quote_lab.postgres_store import PostgresQuoteStore
from crm_lab.postgres_preview import PostgresLeadPreview
from crm_lab.lead_preview import LeadPreviewError

URL=os.environ.get('QUOTE_LAB_TEST_DATABASE_URL')
if not URL:raise RuntimeError('Explicit disposable PostgreSQL URL required')
class PostgresLeadPreviewTests(unittest.TestCase):
    def setUp(self):
        self.store=PostgresQuoteStore(URL)
        self.phone='000'+str(uuid4().int%10**10).zfill(10)
        with self.store._transaction() as cur:
            cur.execute('CREATE SCHEMA IF NOT EXISTS crm_preview_stage')
            cur.execute("""CREATE TABLE IF NOT EXISTS crm_preview_stage.leads (
                phone TEXT PRIMARY KEY,name TEXT,product TEXT,status TEXT,
                callback_time TEXT,notes TEXT,updated_at TIMESTAMPTZ,
                callback_request_id TEXT,callback_requested_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),last_inbound_at TIMESTAMPTZ,manual_followup_completed_at TIMESTAMPTZ,
                conversation JSONB NOT NULL DEFAULT '[]'::jsonb,context JSONB NOT NULL DEFAULT '{}'::jsonb)""")
            cur.execute("""INSERT INTO crm_preview_stage.leads (phone,name,product,status,callback_time,notes,updated_at) VALUES
                (%s,'לקוח בדיקה','מקלחון','נסגר','מחר','הערה',now())""",(self.phone,))
    def test_read_only_snapshot_retains_fields_without_inventing_approval(self):
        result=PostgresLeadPreview(URL).snapshot()
        c=next(c for c in result['customers'] if c['source_phone']==self.phone)
        self.assertIsNone(c['stage']);self.assertFalse(c['verified_approval'])
        self.assertEqual(c['quote_versions'],[]);self.assertEqual(c['tasks_created'],0)
        with self.store._transaction() as cur:
            cur.execute('SELECT status,notes FROM crm_preview_stage.leads WHERE phone=%s',(self.phone,))
            self.assertEqual(dict(cur.fetchone()),{'status':'נסגר','notes':'הערה'})
    def test_bounded_export_marks_more_rows(self):
        with self.store._transaction() as cur:
            cur.execute("""INSERT INTO crm_preview_stage.leads (phone,name,product,status,callback_time,notes,updated_at) VALUES
                (%s,'עוד לקוח','מקלחון','חדש','','',now())""",(self.phone+'1',))
        result=PostgresLeadPreview(URL).snapshot(limit=1)
        self.assertEqual(len(result['customers']),1);self.assertTrue(result['has_more'])
    def test_real_data_in_fixture_table_fails_closed(self):
        phone='972'+str(uuid4().int%10**10).zfill(10)
        with self.store._transaction() as cur:
            cur.execute("INSERT INTO crm_preview_stage.leads (phone,name,product,status,callback_time,notes,updated_at) VALUES (%s,'','','חדש','','',now())",(phone,))
        try:
            with self.assertRaises(LeadPreviewError):PostgresLeadPreview(URL).snapshot()
        finally:
            with self.store._transaction() as cur:cur.execute('DELETE FROM crm_preview_stage.leads WHERE phone=%s',(phone,))

    def test_keyset_pages_cover_fixture_once_without_writes(self):
        from crm_lab.read_source import ReadOnlyLeadSource
        with self.store._transaction() as cur:
            cur.execute('SELECT phone FROM crm_preview_stage.leads ORDER BY phone')
            expected=[row['phone'] for row in cur.fetchall()]
        reader=ReadOnlyLeadSource(test_database_url=URL)
        after='';phones=[]
        for _ in range(len(expected)+1):
            page=reader.page(limit=1,after=after)
            phones.extend(c['source_phone'] for c in page['customers'])
            self.assertEqual(page['snapshot_scope'],'single_page')
            self.assertFalse(page['live_connection_enabled'])
            self.assertTrue(all(not c['verified_approval'] for c in page['customers']))
            if page['next_after'] is None:break
            after=page['next_after']
        self.assertEqual(phones,expected)
        with self.store._transaction() as cur:
            cur.execute('SELECT phone FROM crm_preview_stage.leads ORDER BY phone')
            self.assertEqual([row['phone'] for row in cur.fetchall()],expected)

    def test_saved_customer_detail_is_read_only_and_does_not_export_full_context(self):
        from crm_lab.read_source import ReadOnlyLeadSource
        import json
        history=[{'role':'user','content':'תחזור אליי'},{'role':'assistant','content':'מתי נוח?'}]
        context={'private_marker':'must-not-export','validated_quote':{'issued':True,'approved':True,'amount_ils_pre_vat':2828}}
        with self.store._transaction() as cur:
            cur.execute('UPDATE crm_preview_stage.leads SET conversation=%s,context=%s,status=%s WHERE phone=%s',
                        (json.dumps(history),json.dumps(context),'ממתין לחזרה',self.phone))
        result=ReadOnlyLeadSource(test_database_url=URL).detail(phone=self.phone)
        self.assertEqual([m['content'] for m in result['conversation']],['תחזור אליי','מתי נוח?'])
        self.assertEqual(result['legacy_quote']['amount_cents'],282800)
        self.assertFalse(result['legacy_quote']['verified_approval']);self.assertIsNone(result['callback']['request_id'])
        self.assertNotIn('must-not-export',str(result))
        with self.store._transaction() as cur:
            cur.execute('SELECT conversation,context FROM crm_preview_stage.leads WHERE phone=%s',(self.phone,))
            row=cur.fetchone();self.assertEqual(row['conversation'],history);self.assertEqual(row['context'],context)

    def test_followup_timestamps_are_exported_read_only_without_inventing_a_job(self):
        from crm_lab.read_source import ReadOnlyLeadSource
        with self.store._transaction() as cur:
            cur.execute("UPDATE crm_preview_stage.leads SET last_inbound_at='2026-10-10T18:00:00Z',manual_followup_completed_at='2026-10-11T18:01:00Z' WHERE phone=%s",(self.phone,))
        source=ReadOnlyLeadSource(test_database_url=URL)
        customer=source.detail(phone=self.phone)['customer']
        self.assertEqual(customer['last_inbound_at'],'2026-10-10T18:00:00+00:00')
        self.assertEqual(customer['manual_followup_completed_at'],'2026-10-11T18:01:00+00:00')
        self.assertEqual(customer['tasks_created'],0)

    def test_lead_creation_timestamp_is_preserved_independently_of_updates(self):
        from crm_lab.read_source import ReadOnlyLeadSource
        with self.store._transaction() as cur:
            cur.execute("UPDATE crm_preview_stage.leads SET created_at='2026-10-10T17:00:00Z',updated_at='2026-10-11T21:00:00Z' WHERE phone=%s",(self.phone,))
        c=ReadOnlyLeadSource(test_database_url=URL).detail(phone=self.phone)['customer']
        self.assertEqual(c['source_created_at'],'2026-10-10T17:00:00+00:00')
        self.assertNotEqual(c['source_created_at'],c['source_updated_at'])
