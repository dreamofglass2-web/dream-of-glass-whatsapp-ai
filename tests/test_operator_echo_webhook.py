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
