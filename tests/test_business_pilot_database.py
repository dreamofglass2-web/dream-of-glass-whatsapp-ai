"""Disposable PostgreSQL finite-pilot admission. Never send external messages."""
import json,os,unittest,uuid
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
import psycopg2
from unittest.mock import patch
import business_pilot

def connect():return psycopg2.connect(os.environ['DATABASE_URL'],sslmode='disable',connect_timeout=5)
class PilotDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.config=('TEST_PILOT_'+uuid.uuid4().hex,datetime(2020,1,1,tzinfo=timezone.utc),3)
        self.phones=['9725'+str(810000+i).zfill(8) for i in range(8)]
        self.stamp=str(int(datetime.now(timezone.utc).timestamp()))
        with connect() as db:
            with db.cursor() as cur:
                business_pilot.ensure_tables(cur);business_pilot.configure(cur,self.config)
                for phone in self.phones:
                    cur.execute('INSERT INTO glass_leads(phone,context,created_at) VALUES(%s,%s::jsonb,now())',(phone,json.dumps({'whatsapp_referral':{'source':'meta_click_to_whatsapp_ad'}})))
        self.addCleanup(self.cleanup)
    def cleanup(self):
        with connect() as db:
            with db.cursor() as cur:
                cur.execute('DELETE FROM yossi_pilot_members WHERE campaign_id=%s',(self.config[0],))
                cur.execute('DELETE FROM yossi_pilot_campaigns WHERE id=%s',(self.config[0],))
                for table in ('yossi_resume_jobs','yossi_handoffs'):
                    cur.execute('SELECT to_regclass(%s)',(table,))
                    if cur.fetchone()[0]:cur.execute('DELETE FROM '+table+' WHERE phone=ANY(%s)',(self.phones,))
                cur.execute('DELETE FROM glass_leads WHERE phone=ANY(%s)',(self.phones,))
    def admit(self,phone,stamp=None):
        with connect() as db:
            with db.cursor() as cur:return business_pilot.admit(cur,self.config,phone,stamp or self.stamp)
    def test_parallel_new_leads_admit_exactly_three_and_restarts_cannot_add_fourth(self):
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(self.admit,self.phones))
        self.assertEqual(sum(results),3)
        with connect() as db:
            with db.cursor() as cur:
                cur.execute('SELECT phone,ordinal FROM yossi_pilot_members WHERE campaign_id=%s ORDER BY ordinal',(self.config[0],));members=cur.fetchall()
                self.assertEqual([r[1] for r in members],[1,2,3])
                for phone,_ in members:self.assertTrue(business_pilot.allows(cur,self.config,phone))
        for phone,_ in members:self.assertTrue(self.admit(phone))
        self.assertEqual(sum(self.admit(phone) for phone in self.phones),3)
    def test_old_private_opted_out_test_and_pre_cutoff_leads_do_not_consume_slots(self):
        with connect() as db:
            with db.cursor() as cur:
                cur.execute("UPDATE glass_leads SET created_at='2019-01-01T00:00:00Z' WHERE phone=%s",(self.phones[0],))
                cur.execute("UPDATE glass_leads SET context='{}'::jsonb WHERE phone=%s",(self.phones[1],))
                cur.execute("UPDATE glass_leads SET context=context||'{\"no_followups\":true}'::jsonb WHERE phone=%s",(self.phones[2],))
                cur.execute("UPDATE glass_leads SET context=context||'{\"simulation_recipient_id\":\"test\"}'::jsonb WHERE phone=%s",(self.phones[3],))
        for phone in self.phones[:4]:self.assertFalse(self.admit(phone))
        self.assertFalse(self.admit(self.phones[4],'1'))
        self.assertTrue(self.admit(self.phones[4]))
        self.assertTrue(self.admit(self.phones[5]))
        self.assertTrue(self.admit(self.phones[6]))
        self.assertFalse(self.admit(self.phones[7]))
    def test_campaign_cutoff_cannot_be_reset_under_same_identity(self):
        self.assertTrue(self.admit(self.phones[0]))
        with connect() as db:
            with db.cursor() as cur:
                with self.assertRaises(ValueError):business_pilot.configure(cur,(self.config[0],datetime(2021,1,1,tzinfo=timezone.utc),3))
                self.assertTrue(business_pilot.allows(cur,self.config,self.phones[0]))

    def test_form_message_only_mode_excludes_direct_and_ad_only_inquiries(self):
        with connect() as db:
            with db.cursor() as cur:
                cur.execute("UPDATE glass_leads SET context='{\"whatsapp_referral\":{\"source\":\"meta_whatsapp_form_message\"}}'::jsonb WHERE phone=%s",(self.phones[0],))
                cur.execute("UPDATE glass_leads SET context='{\"meta_leads\":{\"test\":{\"source\":\"meta_instant_form\"}}}'::jsonb WHERE phone=%s",(self.phones[1],))
                cur.execute("UPDATE glass_leads SET context='{\"whatsapp_referral\":{\"source\":\"meta_whatsapp_direct_inbound\"}}'::jsonb WHERE phone=%s",(self.phones[2],))
        with patch.dict(os.environ,{'BUSINESS_PILOT_REQUIRE_FORM':'true'}):
            self.assertTrue(self.admit(self.phones[0]));self.assertTrue(self.admit(self.phones[1]))
            self.assertFalse(self.admit(self.phones[2]));self.assertFalse(self.admit(self.phones[3]))

    def test_fresh_campaign_cannot_reuse_existing_leads_even_with_form_provenance(self):
        with connect() as db:
            with db.cursor() as cur:
                cur.execute("UPDATE glass_leads SET created_at='2019-01-01',context='{\"whatsapp_referral\":{\"source\":\"meta_whatsapp_form_message\"}}'::jsonb WHERE phone=%s",(self.phones[0],))
        with patch.dict(os.environ,{'BUSINESS_PILOT_REQUIRE_FORM':'true'}):
            self.assertFalse(self.admit(self.phones[0]))

    def selected_env(self,revision=2):
        from datetime import timedelta
        return {'BUSINESS_PILOT_REQUIRE_FORM':'true','BUSINESS_PILOT_SELECTED_EXISTING':self.phones[0],
            'BUSINESS_PILOT_SELECTED_REVISION':str(revision),
            'BUSINESS_PILOT_SELECTED_RESUME_AT':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
    def seed_selected(self,revision=2):
        from handoff_store import ensure_tables,write_state
        from handoff_state import new_state
        with connect() as db,db.cursor() as cur:
            ensure_tables(cur)
            cur.execute("UPDATE glass_leads SET created_at='2019-01-01',last_inbound_at=now(),context='{\"meta_leads\":{\"selected\":{\"source\":\"meta_instant_form\"}}}'::jsonb WHERE phone=%s",(self.phones[0],))
            write_state(cur,self.phones[0],dict(new_state(),owner='operator',revision=revision))
    def test_selected_existing_lead_counts_once_and_return_is_scheduled_not_sent(self):
        from handoff_store import read_state,owner_action
        self.seed_selected();env=self.selected_env()
        with connect() as db,db.cursor() as cur:
            self.assertEqual(business_pilot.activate_selected_existing(cur,self.config,env),'scheduled')
            state=read_state(cur,self.phones[0]);self.assertEqual(state['owner'],'yossi')
            self.assertEqual(state['resume_at'],env['BUSINESS_PILOT_SELECTED_RESUME_AT'])
            self.assertEqual(business_pilot.activate_selected_existing(cur,self.config,env),'already_applied')
            cur.execute('SELECT count(*) FROM yossi_resume_jobs WHERE phone=%s',(self.phones[0],));self.assertEqual(cur.fetchone()[0],1)
            cur.execute('SELECT count(*) FROM yossi_pilot_members WHERE campaign_id=%s',(self.config[0],));self.assertEqual(cur.fetchone()[0],1)
            owner_action(cur,self.phones[0],state['revision'],{'type':'takeover'},datetime.now(timezone.utc).isoformat())
            self.assertEqual(business_pilot.activate_selected_existing(cur,self.config,env),'already_applied')
            self.assertEqual(read_state(cur,self.phones[0])['owner'],'operator')
    def test_new_human_message_since_selection_prevents_return_and_membership(self):
        self.seed_selected(revision=3)
        with connect() as db,db.cursor() as cur:
            self.assertEqual(business_pilot.activate_selected_existing(cur,self.config,self.selected_env(2)),'conversation_changed')
            self.assertFalse(business_pilot.allows(cur,self.config,self.phones[0]))

    def test_operator_owned_lead_never_consumes_a_fresh_pilot_slot(self):
        from handoff_store import ensure_tables,write_state
        from handoff_state import new_state
        with connect() as db,db.cursor() as cur:
            ensure_tables(cur)
            write_state(cur,self.phones[0],dict(new_state(),owner='operator'))
        self.assertFalse(self.admit(self.phones[0]))
        for phone in self.phones[1:4]:self.assertTrue(self.admit(phone))
        self.assertFalse(self.admit(self.phones[4]))

    def test_website_inquiries_share_form_quota_and_require_explicit_enablement(self):
        with connect() as db,db.cursor() as cur:
            for phone in self.phones[:4]:
                cur.execute("UPDATE glass_leads SET context='{\"whatsapp_referral\":{\"source\":\"meta_whatsapp_website_inbound\"}}'::jsonb WHERE phone=%s",(phone,))
        with patch.dict(os.environ,{'BUSINESS_PILOT_REQUIRE_FORM':'true','BUSINESS_PILOT_ALLOW_WEBSITE':'false'}):
            self.assertFalse(self.admit(self.phones[0]))
        with patch.dict(os.environ,{'BUSINESS_PILOT_REQUIRE_FORM':'true','BUSINESS_PILOT_ALLOW_WEBSITE':'true'}):
            for phone in self.phones[:3]:self.assertTrue(self.admit(phone))
            self.assertFalse(self.admit(self.phones[3]))
