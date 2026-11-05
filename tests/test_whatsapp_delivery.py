import os,json,hmac,unittest
from datetime import datetime,timezone
from unittest.mock import MagicMock,patch
os.environ.setdefault('OPENAI_API_KEY','sk-offline-test-only')
import whatsapp_delivery as delivery
import app as yossi

NUMBER='456765487527572'
PHONE='972501234567'
EVENT={'id':'wamid.receipt-test','recipient_id':PHONE,'status':'delivered','timestamp':'1793851200'}

class ReceiptTests(unittest.TestCase):
    def value(self,event=None):
        return {'metadata':{'phone_number_id':NUMBER},'statuses':[event or EVENT]}
    def test_only_exact_channel_and_valid_bounded_events(self):
        self.assertEqual(delivery.parse_statuses(self.value(),NUMBER)[0][2],'delivered')
        self.assertEqual(delivery.parse_statuses(self.value(),'other'),[])
        self.assertEqual(delivery.parse_statuses({'metadata':[],'statuses':[EVENT]},NUMBER),[])
        for key,val in [('id','bad'),('recipient_id','+972501234567'),('status',[]),('status','unknown'),('timestamp','x'),('timestamp','9'*10000)]:
            with self.subTest(key=key,value=str(val)[:20]):
                self.assertEqual(delivery.parse_statuses(self.value(dict(EVENT,**{key:val})),NUMBER),[])
    def test_only_numeric_error_codes_retained_not_customer_or_provider_text(self):
        events=delivery.parse_statuses(self.value(dict(EVENT,status='failed',errors=[{'code':131049,'message':'private details'},{'code':True},{'code':'invalid'}])),NUMBER)
        self.assertEqual(events[0][-1],[131049]);self.assertNotIn('private',repr(events))
    def test_read_and_delivery_proof_survive_later_sent_or_failure(self):
        cur=MagicMock();now=datetime.now(timezone.utc)
        cur.fetchall.return_value=[('accepted',now,'wamid.x','failed',now,[131049]),('accepted',now,'wamid.x','read',now,[]),('accepted',now,'wamid.x','sent',now,[])]
        result=delivery.outreach_status(cur,PHONE)
        self.assertEqual(result['status'],'read');self.assertTrue(result['deliveryVerified'])
        cur.fetchall.return_value=[('accepted',now,'wamid.x',None,None,None)]
        result=delivery.outreach_status(cur,PHONE)
        self.assertEqual(result['status'],'accepted');self.assertFalse(result['deliveryVerified'])
    def post(self,value,signed=True):
        raw=json.dumps({'entry':[{'changes':[{'field':'messages','value':value}]}]}).encode()
        signature='sha256='+hmac.new(b'only-test-secret',raw,'sha256').hexdigest() if signed else 'wrong'
        with patch.object(yossi,'APP_SECRET','only-test-secret'),patch.object(yossi,'PHONE_NUMBER_ID',NUMBER):
            return yossi.app.test_client().post('/webhook',data=raw,content_type='application/json',headers={'X-Hub-Signature-256':signature})
    def test_signed_receipts_stored_without_send_queue_or_admission(self):
        with patch.object(yossi,'ensure_worker_started'),patch.object(yossi,'ensure_db'),patch.object(yossi,'db_connection',return_value=MagicMock()),patch.object(delivery,'record') as record,patch.object(yossi,'queue_message') as queue,patch.object(yossi,'send_whatsapp') as send,patch.object(yossi,'admit_business_pilot') as admit:
            self.assertEqual(self.post(self.value()).status_code,200)
            self.assertEqual(record.call_count,1);queue.assert_not_called();send.assert_not_called();admit.assert_not_called()
            record.reset_mock()
            self.assertEqual(self.post(self.value(),False).status_code,403);record.assert_not_called()
            self.assertEqual(self.post({'metadata':{'phone_number_id':'wrong'},'statuses':[EVENT]}).status_code,200);record.assert_not_called()
    def test_database_error_returns_retryable_503_without_private_data(self):
        with patch.object(yossi,'ensure_worker_started'),patch.object(yossi,'ensure_db'),patch.object(yossi,'db_connection',side_effect=RuntimeError('private')):
            response=self.post(self.value());self.assertEqual(response.status_code,503);self.assertNotIn('private',response.text)

class ProbeTests(unittest.TestCase):
    def env(self):return {'WHATSAPP_DELIVERY_PROBE_ID':'offline-probe','WHATSAPP_DELIVERY_PROBE_PHONE':PHONE}
    def setup_io(self,existing=False):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect=[(1,) if existing else None,('offline-probe',)]
        http=MagicMock();http.get.return_value.status_code=200;http.get.return_value.json.return_value={'display_phone_number':'+972 50-855-4415'}
        http.post.return_value.status_code=200;http.post.return_value.json.return_value={'messages':[{'id':'wamid.probe'}]}
        return MagicMock(return_value=conn),cur,http
    def run_probe(self,connect,http,**kw):
        with patch.object(delivery.form_outreach,'approval_ready',return_value=True):
            delivery.dispatch_probe(connect,http,'offline-token',NUMBER,lambda:True,MagicMock(),env=self.env(),**kw)
    def test_probe_no_repeat_on_restart_or_existing_uncertain_claim(self):
        connect,cur,http=self.setup_io(existing=True);self.run_probe(connect,http);http.post.assert_not_called();http.get.assert_not_called()
    def test_probe_checks_sender_then_sends_only_once_without_touching_leads(self):
        connect,cur,http=self.setup_io();self.run_probe(connect,http)
        self.assertEqual(http.post.call_count,1);self.assertEqual(http.post.call_args.kwargs['json']['to'],PHONE)
        self.assertTrue(any('accepted' in c.args[1] for c in cur.execute.call_args_list if c.args[0].startswith('UPDATE')))
        self.assertFalse(any('glass_leads' in c.args[0] or 'pilot_members' in c.args[0] for c in cur.execute.call_args_list))
    def test_wrong_sender_rejected_and_timeout_does_not_retry(self):
        connect,cur,http=self.setup_io();http.get.return_value.json.return_value={'display_phone_number':'+972500000000'}
        self.run_probe(connect,http);http.post.assert_not_called()
        connect,cur,http=self.setup_io();http.post.side_effect=TimeoutError()
        self.run_probe(connect,http);self.assertEqual(http.post.call_count,1)
        self.assertTrue(any('uncertain' in c.args[1] for c in cur.execute.call_args_list if c.args[0].startswith('UPDATE')))
    def test_approval_hours_channel_disabled_and_lost_claim_never_send(self):
        for token,number,hours,env in [('',NUMBER,True,self.env()),('token','wrong',True,self.env()),('token',NUMBER,False,self.env()),('token',NUMBER,True,{})]:
            connect,cur,http=self.setup_io();delivery.dispatch_probe(connect,http,token,number,lambda:hours,MagicMock(),env=env);http.post.assert_not_called()
        connect,cur,http=self.setup_io();cur.fetchone.side_effect=[None,None];self.run_probe(connect,http);http.post.assert_not_called()
        connect,cur,http=self.setup_io()
        with patch.object(delivery.form_outreach,'approval_ready',return_value=False):
            delivery.dispatch_probe(connect,http,'token',NUMBER,lambda:True,MagicMock(),env=self.env())
        http.post.assert_not_called()
