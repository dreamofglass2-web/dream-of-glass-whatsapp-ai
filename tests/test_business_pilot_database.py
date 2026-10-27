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
