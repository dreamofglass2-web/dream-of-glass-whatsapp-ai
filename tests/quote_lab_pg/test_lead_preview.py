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
                callback_time TEXT,notes TEXT,updated_at TIMESTAMPTZ)""")
            cur.execute("""INSERT INTO crm_preview_stage.leads VALUES
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
            cur.execute("""INSERT INTO crm_preview_stage.leads VALUES
                (%s,'עוד לקוח','מקלחון','חדש','','',now())""",(self.phone+'1',))
        result=PostgresLeadPreview(URL).snapshot(limit=1)
        self.assertEqual(len(result['customers']),1);self.assertTrue(result['has_more'])
    def test_real_data_in_fixture_table_fails_closed(self):
        phone='972'+str(uuid4().int%10**10).zfill(10)
        with self.store._transaction() as cur:
            cur.execute("INSERT INTO crm_preview_stage.leads VALUES (%s,'','','חדש','','',now())",(phone,))
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
