"""Synthetic audio pipeline tests: no paid API or customer messages."""
import os
import json
import hmac
import types
import unittest
from unittest.mock import Mock, patch, MagicMock
os.environ.setdefault('OPENAI_API_KEY', 'sk-offline-test-only')
import app as yossi
from audio_transcription import transcribe_audio, AUDIO_FAILURE, MAX_AUDIO_BYTES


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.payload = {'type':'audio', 'media_id':'MEDIA123', 'mime_type':'audio/ogg; codecs=opus'}
        self.api = Mock()
        self.endpoint = self.api.with_options.return_value.audio.transcriptions.create
        self.endpoint.return_value = types.SimpleNamespace(text='אני רוצה מקלחון פינתי 80 על 90')
        self.download = Mock(return_value=(b'OggS synthetic opus', 'audio/ogg; codecs=opus'))
        self.log = Mock()

    def transcribe(self):
        return transcribe_audio(self.payload, self.api, self.download, 'gpt-4o-mini-transcribe', self.log)

    def test_ogg_opus_transcript_enters_existing_text_pipeline(self):
        with patch.object(yossi, '_authorized_meta_media', self.download), patch.object(yossi, 'client', self.api):
            result = yossi.resolve_incoming_body('__MEDIA_DATA__:' + json.dumps(self.payload))
        self.assertEqual(result, 'אני רוצה מקלחון פינתי 80 על 90')
        self.assertEqual(yossi.customer_written_text(result), result)
        call = self.endpoint.call_args.kwargs
        self.assertEqual(call['file'][0], 'voice.ogg')
        self.assertEqual(call['language'], 'he')
        self.assertEqual(call['response_format'], 'json')
        self.api.with_options.assert_called_once_with(timeout=45.0, max_retries=0)
        self.assertNotIn(result, str(self.log.mock_calls))

    def test_download_failure_does_not_call_api(self):
        self.download.side_effect = TimeoutError()
        self.assertEqual(self.transcribe(), AUDIO_FAILURE)
        self.endpoint.assert_not_called()

    def test_empty_unsupported_and_oversized_audio_are_rejected(self):
        for raw, mime in [(b'', 'audio/ogg'), (b'abc', 'audio/aac'), (b'x'*(MAX_AUDIO_BYTES+1), 'audio/ogg')]:
            self.download.return_value = (raw, mime)
            self.assertEqual(self.transcribe(), AUDIO_FAILURE)
        self.endpoint.assert_not_called()

    def test_api_failure_empty_and_long_transcripts(self):
        self.endpoint.side_effect = TimeoutError()
        self.assertEqual(self.transcribe(), AUDIO_FAILURE)
        self.endpoint.side_effect = None
        for text in ['', '  ', 'x'*6001]:
            self.endpoint.return_value = types.SimpleNamespace(text=text)
            self.assertEqual(self.transcribe(), AUDIO_FAILURE)

    def test_failure_asks_for_text_without_sales_ai(self):
        with patch.object(yossi, 'HANDOFF_ENABLED', False), patch.object(yossi, 'load_conversation', return_value=([], {})), patch.object(yossi, 'save_conversation') as save, patch.object(yossi, 'has_new_messages', return_value=False), patch.object(yossi, 'send_whatsapp') as send, patch.object(yossi.client.responses, 'create') as sales:
            self.assertTrue(yossi.process_message('TEST_ONLY', AUDIO_FAILURE))
        self.assertIn('לא הצלחתי לתמלל', send.call_args.kwargs['body'])
        sales.assert_not_called()
        save.assert_called_once()

    def test_audio_result_persisted_and_reused_on_retry(self):
        original = '__MEDIA_DATA__:' + json.dumps(self.payload)
        pending = {'TEST_ONLY':[('MID123', original, 123)]}
        db = MagicMock()
        with patch.object(yossi, 'pending', pending), patch.object(yossi, 'db_connection', return_value=db), patch.object(yossi, 'resolve_incoming_body', return_value='התמלול'):
            self.assertEqual(yossi.resolve_queued_body('TEST_ONLY', pending['TEST_ONLY'][0]), 'התמלול')
            self.assertEqual(pending['TEST_ONLY'][0][1], 'התמלול')
            cur = db.__enter__.return_value.cursor.return_value.__enter__.return_value
            self.assertEqual(cur.execute.call_args.args[1], ('התמלול', 'TEST_ONLY', 'MID123', original))
        with patch.object(yossi, 'db_connection') as connect, patch.object(yossi, 'analyze_customer_media') as analyze:
            self.assertEqual(yossi.resolve_queued_body('TEST_ONLY', pending['TEST_ONLY'][0]), 'התמלול')
            connect.assert_not_called()
            analyze.assert_not_called()

    def test_text_bypasses_transcription(self):
        with patch.object(yossi, 'analyze_customer_media') as analyze:
            self.assertEqual(yossi.resolve_incoming_body('שלום'), 'שלום')
            analyze.assert_not_called()

    def test_signed_audio_webhook_enqueues_only_authorized_sender(self):
        secret = 'offline-test-secret'
        payload = {'entry':[{'changes':[{'value':{'metadata':{'phone_number_id':str(yossi.PHONE_NUMBER_ID)}, 'messages':[{'id':'MID123','from':'972501234567','type':'audio','audio':{'id':'MEDIA123','mime_type':'audio/ogg; codecs=opus','voice':True}}]}}]}]}
        raw = json.dumps(payload).encode()
        signature = 'sha256=' + hmac.new(secret.encode(), raw, 'sha256').hexdigest()
        with patch.object(yossi, 'APP_SECRET', secret), patch.object(yossi, 'BUSINESS_AUTO_REPLY_ENABLED', True), patch.object(yossi, 'HANDOFF_ENABLED', False), patch.object(yossi, 'ensure_worker_started'), patch.object(yossi, 'clear_simulation_for_business_inbound'), patch.object(yossi, 'verified_business_lead', return_value=True) as allowed, patch.object(yossi, 'queue_message') as queue, patch.object(yossi, 'analyze_customer_media') as analyze:
            response = yossi.app.test_client().post('/webhook', data=raw, content_type='application/json', headers={'X-Hub-Signature-256':signature})
            self.assertEqual(response.status_code, 200)
            queued = json.loads(queue.call_args.args[1][len('__MEDIA_DATA__:'):])
            self.assertEqual(queued['type'], 'audio')
            self.assertEqual(queued['media_id'], 'MEDIA123')
            analyze.assert_not_called()
            queue.reset_mock()
            allowed.return_value = False
            yossi.app.test_client().post('/webhook', data=raw, content_type='application/json', headers={'X-Hub-Signature-256':signature})
            queue.assert_not_called()


if __name__ == '__main__':
    unittest.main()
