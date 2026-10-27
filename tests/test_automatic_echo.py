import os,unittest
from unittest.mock import patch,MagicMock
import automatic_echo as a

class AutomaticEchoTests(unittest.TestCase):
    def test_only_the_exact_configured_automatic_message_matches(self):
        text='Known automatic welcome\nBusiness hours 08:00-20:00'
        env={'BUSINESS_AUTOMATIC_ECHO_HASHES':a.fingerprint(text)}
        self.assertTrue(a.is_automatic_echo({'text':text},env))
        self.assertTrue(a.is_automatic_echo({'text':text.replace('\n','\r\n')},env))
        for body in ['שלום','אני חוזר אליך בהמשך',text+' manual reply','']:
            self.assertFalse(a.is_automatic_echo({'text':body},env))
        self.assertFalse(a.is_automatic_echo({'text':text},{}))
    def test_automatic_echo_does_not_write_operator_ownership_or_queue_a_reply(self):
        from tests.test_operator_echo_webhook import OperatorWebhookTests
        import app as yossi
        harness=OperatorWebhookTests();payload=harness.payload()
        text=payload['entry'][0]['changes'][0]['value']['message_echoes'][0]['text']['body']
        with patch.dict(os.environ,{'BUSINESS_AUTOMATIC_ECHO_HASHES':a.fingerprint(text)}),patch.object(yossi,'HANDOFF_ENABLED',True),patch.object(yossi,'HANDOFF_ECHO_ENABLED',True),patch.object(yossi,'ensure_worker_started'),patch.object(yossi,'record_message') as record,patch.object(yossi,'queue_message') as queue,patch.object(yossi,'send_whatsapp') as send:
            self.assertEqual(harness.post(payload).status_code,200)
            record.assert_not_called();queue.assert_not_called();send.assert_not_called()
    def test_personal_reply_still_records_operator_takeover(self):
        from tests.test_operator_echo_webhook import OperatorWebhookTests
        import app as yossi
        harness=OperatorWebhookTests()
        with patch.dict(os.environ,{'BUSINESS_AUTOMATIC_ECHO_HASHES':a.fingerprint('automatic welcome')}),patch.object(yossi,'HANDOFF_ENABLED',True),patch.object(yossi,'HANDOFF_ECHO_ENABLED',True),patch.object(yossi,'ensure_worker_started'),patch.object(yossi,'ensure_db'),patch.object(yossi,'db_connection',return_value=MagicMock()),patch.object(yossi,'verified_business_lead',return_value=True),patch.object(yossi,'record_message') as record:
            self.assertEqual(harness.post(harness.payload()).status_code,200)
            self.assertTrue(record.call_args.kwargs['operator'])
