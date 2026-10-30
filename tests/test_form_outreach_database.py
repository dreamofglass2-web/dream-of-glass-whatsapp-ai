"""Disposable PostgreSQL only; HTTP is always replaced with mocks."""
import json, os, unittest, uuid
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
import psycopg2
import app as yossi
import form_outreach as f
import business_pilot
from handoff_store import write_state
from handoff_state import new_state

def connect():
    return psycopg2.connect(os.environ['DATABASE_URL'],sslmode='disable',connect_timeout=5)

class FormOutreachDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.campaign='TEST_FORM_'+uuid.uuid4().hex
        self.start=datetime.now(timezone.utc)-timedelta(days=3)
        self.env={'BUSINESS_PILOT_ID':self.campaign,'BUSINESS_PILOT_START_AT':self.start.isoformat(),'BUSINESS_PILOT_LIMIT':'3','FORM_OUTREACH_ENABLED':'true','FORM_OUTREACH_FORM_IDS':'4321'}
        self.phones=['9725'+str(80000000+int(uuid.uuid4().hex[:6],16)+i) for i in range(8)]
        self.ids=['TEST_FORM_'+uuid.uuid4().hex for _ in self.phones]
        self.patchers=[patch.dict(os.environ,self.env),patch.object(yossi,'db_connection',side_effect=connect)]
        for p in self.patchers:p.start()
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patchers)])
        yossi._db_ready=False;yossi.ensure_db()
        with connect() as conn, conn.cursor() as cur:
            cur.execute('''CREATE TABLE IF NOT EXISTS meta_leadgen_events (
                lead_id TEXT PRIMARY KEY,page_id TEXT,form_id TEXT,meta_created_time BIGINT,
                state TEXT,received_at TIMESTAMPTZ NOT NULL DEFAULT now(),details JSONB,details_fetched_at TIMESTAMPTZ)''')
            for phone,lead_id in zip(self.phones,self.ids):
                cur.execute('INSERT INTO glass_leads(phone,context) VALUES(%s,%s::jsonb)',(phone,json.dumps({'meta_leads':{lead_id:{'source':'meta_instant_form'}}})))
                cur.execute("INSERT INTO meta_leadgen_events(lead_id,page_id,form_id,meta_created_time,state) VALUES(%s,'478369542034629','4321',%s,'details_saved')",(lead_id,int(datetime.now(timezone.utc).timestamp())))
        self.addCleanup(self.cleanup)
        self.http=Mock();self.http.post.return_value.status_code=200
        self.http.post.return_value.json.return_value={'messages':[{'id':'wamid.fake-isolated-test'}]}
        self.approval=patch.object(f,'template_approved',return_value=True);self.approval.start();self.addCleanup(self.approval.stop)
    def cleanup(self):
        with connect() as conn, conn.cursor() as cur:
            cur.execute('DELETE FROM yossi_form_outreach WHERE campaign_id=%s',(self.campaign,))
            cur.execute('DELETE FROM yossi_pilot_members WHERE campaign_id=%s',(self.campaign,))
            cur.execute('DELETE FROM yossi_pilot_campaigns WHERE id=%s',(self.campaign,))
            cur.execute('DELETE FROM yossi_handoffs WHERE phone=ANY(%s)',(self.phones,))
            cur.execute('DELETE FROM glass_leads WHERE phone=ANY(%s)',(self.phones,))
            cur.execute('DELETE FROM meta_leadgen_events WHERE lead_id=ANY(%s)',(self.ids,))
        yossi._db_ready=False
    def enqueue(self,i):
        with connect() as conn, conn.cursor() as cur:return f.enqueue(cur,f.configuration(),self.ids[i],self.phones[i])
    def dispatch(self,hours=True):
        return f.dispatch(connect,self.http,'fake-token',f.BUSINESS_NUMBER_ID,lambda:hours,Mock())
    def rows(self,query,args=()):
        with connect() as conn,conn.cursor() as cur:
            cur.execute(query,args);return cur.fetchall()
    def test_parallel_form_and_inbound_share_exactly_three_slots(self):
        def admit(i):
            if i%2==0:return self.enqueue(i)
            with connect() as conn,conn.cursor() as cur:
                cur.execute("UPDATE glass_leads SET context='{\"whatsapp_referral\":{\"source\":\"meta_whatsapp_direct_inbound\"}}'::jsonb WHERE phone=%s",(self.phones[i],))
                return business_pilot.admit(cur,f.configuration()[0],self.phones[i],str(int(datetime.now(timezone.utc).timestamp())))
        with ThreadPoolExecutor(max_workers=8) as pool:result=list(pool.map(admit,range(8)))
        self.assertEqual(sum(result),3)
        self.assertEqual(self.rows('SELECT count(*) FROM yossi_pilot_members WHERE campaign_id=%s',(self.campaign,))[0][0],3)
    def test_duplicate_form_and_restarts_send_once_without_fake_inbound(self):
        self.assertTrue(self.enqueue(0));self.assertFalse(self.enqueue(0))
        # Remove other candidates to isolate one actual recipient.
        with connect() as conn,conn.cursor() as cur:cur.execute("UPDATE meta_leadgen_events SET form_id='other' WHERE lead_id=ANY(%s)",(self.ids[1:],))
        self.assertTrue(self.dispatch());self.assertFalse(self.dispatch())
        self.http.post.assert_called_once()
        last,history=self.rows('SELECT last_inbound_at,conversation FROM glass_leads WHERE phone=%s',(self.phones[0],))[0]
        self.assertIsNone(last);self.assertEqual(history[0]['content'],f.BODY)
        self.assertEqual(self.http.post.call_args.kwargs['json']['type'],'template')
        self.assertIsNone(self.rows('SELECT first_inbound_at FROM yossi_pilot_members WHERE campaign_id=%s',(self.campaign,))[0][0])
    def test_owner_inbound_optout_old_and_unapproved_form_are_excluded(self):
        with connect() as conn,conn.cursor() as cur:
            write_state(cur,self.phones[0],dict(new_state(),owner='operator'))
            cur.execute('UPDATE glass_leads SET last_inbound_at=now() WHERE phone=%s',(self.phones[1],))
            cur.execute("UPDATE glass_leads SET context=context||'{\"no_followups\":true}'::jsonb WHERE phone=%s",(self.phones[2],))
            cur.execute("UPDATE glass_leads SET created_at='2019-01-01' WHERE phone=%s",(self.phones[3],))
            cur.execute("UPDATE meta_leadgen_events SET form_id='other' WHERE lead_id=%s",(self.ids[4],))
        for i in range(5):self.assertFalse(self.enqueue(i))
        self.assertEqual(self.rows('SELECT count(*) FROM yossi_pilot_members WHERE campaign_id=%s',(self.campaign,))[0][0],0)
    def test_reply_or_takeover_after_enqueue_cancels_before_provider(self):
        self.enqueue(0)
        with connect() as conn,conn.cursor() as cur:
            cur.execute('UPDATE glass_leads SET last_inbound_at=now() WHERE phone=%s',(self.phones[0],))
            cur.execute("UPDATE meta_leadgen_events SET form_id='other' WHERE lead_id=ANY(%s)",(self.ids[1:],))
        self.assertFalse(self.dispatch());self.http.post.assert_not_called()
        self.assertEqual(self.rows('SELECT status FROM yossi_form_outreach WHERE campaign_id=%s',(self.campaign,))[0][0],'canceled')
    def test_night_waits_and_provider_timeout_never_retries(self):
        self.enqueue(0)
        with connect() as conn,conn.cursor() as cur:cur.execute("UPDATE meta_leadgen_events SET form_id='other' WHERE lead_id=ANY(%s)",(self.ids[1:],))
        self.assertFalse(self.dispatch(False));self.http.post.assert_not_called()
        self.http.post.side_effect=TimeoutError('mock provider timeout')
        self.assertFalse(self.dispatch());self.assertFalse(self.dispatch())
        self.http.post.assert_called_once()
        self.assertEqual(self.rows('SELECT status FROM yossi_form_outreach WHERE campaign_id=%s',(self.campaign,))[0][0],'uncertain')

    def test_all_forms_still_requires_our_verified_business_page(self):
        with patch.dict(os.environ,{'FORM_OUTREACH_FORM_IDS':'*'}):
            with connect() as conn,conn.cursor() as cur:
                cur.execute("UPDATE meta_leadgen_events SET form_id='new-form' WHERE lead_id=ANY(%s)",(self.ids[:2],))
                cur.execute("UPDATE meta_leadgen_events SET page_id='another-business' WHERE lead_id=%s",(self.ids[1],))
            self.assertTrue(self.enqueue(0));self.assertFalse(self.enqueue(1))

    def test_owner_takeover_after_form_reservation_prevents_opening(self):
        self.enqueue(0)
        with connect() as conn,conn.cursor() as cur:
            write_state(cur,self.phones[0],dict(new_state(),owner='operator',revision=1))
            cur.execute("UPDATE meta_leadgen_events SET form_id='other' WHERE lead_id=ANY(%s)",(self.ids[1:],))
        self.assertFalse(self.dispatch());self.http.post.assert_not_called()

    def test_weekend_expired_inbound_gets_one_template_without_faking_a_new_window(self):
        with connect() as conn,conn.cursor() as cur:
            cur.execute("UPDATE glass_leads SET created_at=now()-interval '2 days',last_inbound_at=now()-interval '25 hours' WHERE phone=%s",(self.phones[0],))
            cur.execute("UPDATE meta_leadgen_events SET received_at=now()-interval '2 days',meta_created_time=extract(epoch from now()-interval '2 days')::bigint WHERE lead_id=%s",(self.ids[0],))
            cur.execute("UPDATE meta_leadgen_events SET form_id='other' WHERE lead_id=ANY(%s)",(self.ids[1:],))
        self.assertFalse(self.dispatch(False));self.http.post.assert_not_called()
        self.assertTrue(self.dispatch());self.assertFalse(self.dispatch())
        self.http.post.assert_called_once()
        inbound,history=self.rows('SELECT last_inbound_at,conversation FROM glass_leads WHERE phone=%s',(self.phones[0],))[0]
        self.assertLess(inbound,datetime.now(timezone.utc)-timedelta(hours=24))
        self.assertEqual(history[0]['content'],f.BODY)
        self.assertEqual(self.http.post.call_args.kwargs['json']['type'],'template')
