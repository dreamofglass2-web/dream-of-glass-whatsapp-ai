import os, json, hmac, unittest
from unittest.mock import patch, MagicMock
os.environ.setdefault('OPENAI_API_KEY', 'sk-offline-test-only')
import app as yossi


class OperatorWebhookTests(unittest.TestCase):
    def payload(self, number=None):
        return {'entry':[{'changes':[{'field':'smb_message_echoes','value':{
            'messaging_product':'whatsapp', 'metadata':{'phone_number_id':number or str(yossi.PHONE_NUMBER_ID)},
            'message_echoes':[{'to':'972501234567','from':'972509999999','id':'wamid.operator',
                'timestamp':'1791817200','type':'text','text':{'body':'נקבע ביקור'}}]}}]}]}

    def post(self, payload, signed=True):
        raw=json.dumps(payload).encode()
        header='sha256='+hmac.new(b'offline-secret', raw, 'sha256').hexdigest() if signed else 'sha256=wrong'
        with patch.object(yossi,'APP_SECRET','offline-secret'):
            return yossi.app.test_client().post('/webhook',data=raw,content_type='application/json',
                headers={'X-Hub-Signature-256':header})

    def test_verified_operator_echo_is_stored_and_never_queued_or_sent(self):
        with patch.object(yossi,'HANDOFF_ENABLED',True), patch.object(yossi,'HANDOFF_ECHO_ENABLED',True), patch.object(yossi,'ensure_worker_started'), \
             patch.object(yossi,'ensure_db'), patch.object(yossi,'db_connection',return_value=MagicMock()), \
             patch.object(yossi,'verified_business_lead',return_value=True), \
             patch.object(yossi,'record_message') as record, patch.object(yossi,'queue_message') as queue, \
             patch.object(yossi,'send_whatsapp') as send:
            self.assertEqual(self.post(self.payload()).status_code,200)
            self.assertEqual(record.call_args.args[1],'972501234567')
            self.assertEqual(record.call_args.args[2]['role'],'operator')
            queue.assert_not_called();send.assert_not_called()

    def test_wrong_channel_unsigned_or_disabled_echo_cannot_write(self):
        with patch.object(yossi,'HANDOFF_ENABLED',True), patch.object(yossi,'HANDOFF_ECHO_ENABLED',True), patch.object(yossi,'ensure_worker_started'), \
             patch.object(yossi,'record_message') as record, patch.object(yossi,'queue_message') as queue:
            self.assertEqual(self.post(self.payload('another-number')).status_code,200)
            self.assertEqual(self.post(self.payload(),signed=False).status_code,403)
            with patch.object(yossi,'HANDOFF_ECHO_ENABLED',False):
                self.assertEqual(self.post(self.payload()).status_code,200)
            record.assert_not_called();queue.assert_not_called()

    def test_storage_failure_requests_meta_retry_instead_of_silent_loss(self):
        with patch.object(yossi,'HANDOFF_ENABLED',True), patch.object(yossi,'HANDOFF_ECHO_ENABLED',True), patch.object(yossi,'ensure_worker_started'), \
             patch.object(yossi,'verified_business_lead',return_value=True), \
             patch.object(yossi,'ensure_db',side_effect=RuntimeError('private data')):
            response=self.post(self.payload())
            self.assertEqual(response.status_code,503)
            self.assertNotIn('private data',response.text)

    def test_paused_customer_text_is_saved_with_meta_time_even_when_automatic_replies_disabled(self):
        from handoff_state import new_state
        state=new_state();state['owner']='operator'
        payload={'entry':[{'changes':[{'field':'messages','value':{'metadata':{'phone_number_id':str(yossi.PHONE_NUMBER_ID)},'messages':[{'from':'972501234567','id':'wamid.customer','timestamp':'1791817200','type':'text','text':{'body':'בסדר, תודה'}}]}}]}]}
        with patch.object(yossi,'HANDOFF_ENABLED',True),patch.object(yossi,'BUSINESS_AUTO_REPLY_ENABLED',False),patch.object(yossi,'ensure_worker_started'),patch.object(yossi,'ensure_db'),patch.object(yossi,'db_connection',return_value=MagicMock()),patch.object(yossi,'verified_business_lead',return_value=True),patch.object(yossi,'phone_lock'),patch.object(yossi,'read_handoff_state',return_value=state),patch.object(yossi,'record_message') as record,patch.object(yossi,'queue_message') as queue,patch.object(yossi,'send_whatsapp') as send:
            self.assertEqual(self.post(payload).status_code,200)
            self.assertEqual(record.call_args.args[2]['role'],'customer')
            self.assertEqual(record.call_args.args[2]['at'],'2026-10-12T15:00:00+00:00')
            queue.assert_not_called();send.assert_not_called()

    def test_media_during_operator_ownership_is_recorded_without_bot_queue_or_admission(self):
        from handoff_state import new_state
        state=dict(new_state(),owner='operator')
        for kind in ('image','audio','document','video'):
            payload={'entry':[{'changes':[{'field':'messages','value':{'metadata':{'phone_number_id':str(yossi.PHONE_NUMBER_ID)},'messages':[{'from':'972501234567','id':'wamid.manual-'+kind,'timestamp':'1791817200','type':kind,kind:{'id':'test-media','caption':'פרטי הלקוח'}}]}}]}]}
            with self.subTest(kind=kind),patch.object(yossi,'HANDOFF_ENABLED',True),patch.object(yossi,'ensure_worker_started'),patch.object(yossi,'ensure_db'),patch.object(yossi,'db_connection',return_value=MagicMock()),patch.object(yossi,'verified_business_lead',return_value=True),patch.object(yossi,'phone_lock'),patch.object(yossi,'read_handoff_state',return_value=state),patch.object(yossi,'record_message') as record,patch.object(yossi,'queue_message') as queue,patch.object(yossi,'admit_business_pilot') as admit,patch.object(yossi,'send_whatsapp') as send:
                self.assertEqual(self.post(payload).status_code,200)
                self.assertIn('התוכן לא נותח',record.call_args.args[2]['text'])
                self.assertIn('פרטי הלקוח',record.call_args.args[2]['text'])
                queue.assert_not_called();admit.assert_not_called();send.assert_not_called()
