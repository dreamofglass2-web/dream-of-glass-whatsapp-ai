import json,unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock,patch
from tests.test_form_outreach_database import FormOutreachDatabaseTests,connect
import app as yossi
import outreach_recovery as r
import form_outreach as f
import whatsapp_delivery as d
from handoff_store import write_state
from handoff_state import new_state

class RecoveryPostgres(unittest.TestCase):
 setUp=FormOutreachDatabaseTests.setUp
 enqueue=FormOutreachDatabaseTests.enqueue
 rows=FormOutreachDatabaseTests.rows
 def cleanup(self):
  with connect() as db,db.cursor() as cur:
   cur.execute('DELETE FROM yossi_outreach_recoveries WHERE campaign_id=%s',(self.campaign,))
   cur.execute('DELETE FROM yossi_message_receipts WHERE phone=ANY(%s)',(self.phones,))
  FormOutreachDatabaseTests.cleanup(self)
 def prepare(self):
  with connect() as db,db.cursor() as cur:
   yossi.ensure_handoff_tables(cur)
   cur.execute("UPDATE meta_leadgen_events SET form_id='other' WHERE lead_id=ANY(%s)",(self.ids[1:],))
  self.assertTrue(self.enqueue(0))
  with patch.object(f,'approval_ready',return_value=True):self.assertTrue(f.dispatch(connect,self.http,'test',f.BUSINESS_NUMBER_ID,lambda:True,Mock()))
  self.http.post.reset_mock()
  self.http.post.return_value.json.return_value={'messages':[{'id':'wamid.recovery-test'}]}
 def recover(self):
  env={'FORM_OUTREACH_RECOVERIES':self.campaign+':'+self.phones[0]}
  with patch.object(f,'approval_ready',return_value=True):
   return r.dispatch(connect,self.http,'test',f.BUSINESS_NUMBER_ID,lambda:True,Mock(),env=env)
 def test_parallel_recovery_is_once_and_does_not_change_membership(self):
  self.prepare()
  with ThreadPoolExecutor(max_workers=4) as pool:result=list(pool.map(lambda _:self.recover(),range(4)))
  self.assertEqual(sum(result),1);self.http.post.assert_called_once()
  self.assertEqual(self.rows('SELECT count(*) FROM yossi_pilot_members WHERE campaign_id=%s',(self.campaign,))[0][0],1)
  with connect() as db,db.cursor() as cur:
   cur.execute('SELECT conversation,last_inbound_at FROM glass_leads WHERE phone=%s',(self.phones[0],));history,inbound=cur.fetchone()
   self.assertEqual(len(history),2);self.assertIsNone(inbound)
   self.assertEqual(d.outreach_status(cur,self.phones[0])['status'],'accepted')
 def test_owner_takeover_and_confirmed_delivery_prevent_resend(self):
  self.prepare()
  with connect() as db,db.cursor() as cur:write_state(cur,self.phones[0],dict(new_state(),owner='operator'))
  self.assertFalse(self.recover());self.http.post.assert_not_called()
  with connect() as db,db.cursor() as cur:
   write_state(cur,self.phones[0],new_state())
   d.record(cur,d.parse_statuses({'metadata':{'phone_number_id':f.BUSINESS_NUMBER_ID},'statuses':[{'id':'wamid.fake-isolated-test','recipient_id':self.phones[0],'status':'delivered','timestamp':'1793851200'}]},f.BUSINESS_NUMBER_ID))
  self.assertFalse(self.recover());self.http.post.assert_not_called()
 def test_timeout_or_provider_failure_never_retries(self):
  self.prepare();self.http.post.side_effect=TimeoutError('mock only')
  self.assertFalse(self.recover());self.assertFalse(self.recover());self.http.post.assert_called_once()
  self.assertEqual(self.rows('SELECT status FROM yossi_outreach_recoveries WHERE campaign_id=%s',(self.campaign,))[0][0],'uncertain')
