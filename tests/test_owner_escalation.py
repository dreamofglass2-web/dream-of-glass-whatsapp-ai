import unittest
import os
import json
import types
from unittest.mock import MagicMock, patch, Mock
from handoff_state import new_state, transition, automatic_reply_allowed
from handoff_store import escalate_to_owner
from owner_escalation import escalation_reason
from owner_notifications import alert_configuration, dispatch_owner_alerts


class EscalationTests(unittest.TestCase):
    def test_telegram_requires_private_chat_and_explicit_activation(self):
        config={'OWNER_ALERT_ENABLED':'true','OWNER_ALERT_CHANNEL':'telegram',
                'OWNER_TELEGRAM_BOT_TOKEN':'123456789:'+'a'*35,'OWNER_TELEGRAM_CHAT_ID':'123456'}
        with patch.dict('os.environ',config,clear=True):
            self.assertEqual(alert_configuration()[0],'telegram')
            for chat in ['-100123456','@someone','', '0']:
                os.environ['OWNER_TELEGRAM_CHAT_ID']=chat
                self.assertIsNone(alert_configuration())

    def test_telegram_alert_has_links_uses_exact_chat_and_never_whatsapp_token(self):
        state=new_state()
        state['escalation']={'id':'a'*32,'active':True,'reason':'נדרשת בדיקה','customerText':'הבקשה','notificationStatus':'not_configured'}
        db=MagicMock()
        db.__enter__.return_value.cursor.return_value.__enter__.return_value.fetchall.return_value=[('972501234567',)]
        http=Mock()
        http.post.return_value.ok=True
        http.post.return_value.json.return_value={'ok':True,'result':{'message_id':44,'chat':{'id':123456}}}
        config={'OWNER_ALERT_ENABLED':'true','OWNER_ALERT_CHANNEL':'telegram',
                'OWNER_TELEGRAM_BOT_TOKEN':'123456789:'+'a'*35,'OWNER_TELEGRAM_CHAT_ID':'123456'}
        with patch.dict('os.environ',config,clear=True),patch('owner_notifications.read_state',return_value=state),patch('owner_notifications.write_state'):
            dispatch_owner_alerts(lambda:db,http,'','unused',Mock())
            self.assertEqual(state['escalation']['notificationStatus'],'accepted')
            call=http.post.call_args
            self.assertTrue(call.args[0].endswith('/sendMessage'))
            self.assertEqual(call.kwargs['json']['chat_id'],'123456')
            self.assertNotIn('headers',call.kwargs)
            self.assertEqual(len(call.kwargs['json']['reply_markup']['inline_keyboard']),2)
            dispatch_owner_alerts(lambda:db,http,'','unused',Mock())
            http.post.assert_called_once()

    def test_sales_model_uncertainty_never_sends_its_reply(self):
        os.environ.setdefault('OPENAI_API_KEY','sk-offline-test-only')
        import app as yossi
        result = types.SimpleNamespace(output_text=json.dumps({'reply':'תשובה לא בטוחה','needs_human':True,'product':'מראה'}))
        with patch.object(yossi,'HANDOFF_ENABLED',True), patch.object(yossi,'ensure_db'), patch.object(yossi,'db_connection',return_value=MagicMock()), patch.object(yossi,'read_handoff_state',return_value=new_state()), patch.object(yossi,'load_conversation',return_value=([],{})), patch.object(yossi,'has_new_messages',return_value=False), patch.object(yossi.client.responses,'create',return_value=result), patch.object(yossi,'pause_for_owner',return_value=True) as pause, patch.object(yossi,'send_whatsapp') as send:
            self.assertTrue(yossi.process_message('TEST_ONLY','אני רוצה מראה עגולה לסלון'))
            pause.assert_called_once()
            send.assert_not_called()

    def test_model_exception_pauses_instead_of_generic_customer_retry(self):
        os.environ.setdefault('OPENAI_API_KEY','sk-offline-test-only')
        import app as yossi
        with patch.object(yossi,'HANDOFF_ENABLED',True), patch.object(yossi,'ensure_db'), patch.object(yossi,'db_connection',return_value=MagicMock()), patch.object(yossi,'read_handoff_state',return_value=new_state()), patch.object(yossi,'load_conversation',return_value=([],{})), patch.object(yossi,'has_new_messages',return_value=False), patch.object(yossi.client.responses,'create',side_effect=TimeoutError()), patch.object(yossi,'pause_for_owner',return_value=True) as pause, patch.object(yossi,'send_whatsapp') as send:
            self.assertTrue(yossi.process_message('TEST_ONLY','אני רוצה מראה עגולה לסלון'))
            pause.assert_called_once()
            send.assert_not_called()

    def test_uncertain_model_and_empty_output_pause(self):
        self.assertIsNotNone(escalation_reason('שאלה', {'needs_human':True}, 'תשובה'))
        self.assertIsNotNone(escalation_reason('שאלה', {}, ''))
        self.assertIsNone(escalation_reason('כמה עולה?', {}, 'מה המידות?'))

    def test_complaint_expert_request_and_unknown_warranty(self):
        for text in ['אתה לא מבין אותי', 'אני רוצה נציג אנושי', 'צריך אישור מהנדס למעקה']:
            self.assertIsNotNone(escalation_reason(text))
        self.assertIsNotNone(escalation_reason('אחריות?', {}, 'אין לי כרגע תנאי אחריות מאומתים'))
        self.assertIsNone(escalation_reason('אין לי מידות'))

    def test_repeated_answer_does_not_continue_loop(self):
        history = [{'role':'assistant','content':'מה המידות?'}, {'role':'user','content':'לא יודע'}, {'role':'assistant','content':'מה המידות?'}]
        self.assertIsNotNone(escalation_reason('אמרתי שאין', {}, 'מה המידות?', history))

    def test_atomic_pause_and_duplicate_request(self):
        cursor = MagicMock()
        stamp = '2026-10-12T21:00:00+00:00'
        with patch('handoff_store.read_state', return_value=new_state()), patch('handoff_store.capture_suppression'), patch('handoff_store.write_state') as write:
            state = escalate_to_owner(cursor, '972501234567', 'צריך בדיקה', 'הבקשה שלי', stamp)
        self.assertEqual(state['owner'], 'operator')
        self.assertTrue(state['escalation']['active'])
        self.assertFalse(automatic_reply_allowed(state, stamp))
        write.assert_called_once()
        with patch('handoff_store.read_state', return_value=state), patch('handoff_store.write_state') as write:
            self.assertEqual(escalate_to_owner(cursor, '972501234567', 'שוב', 'שוב', stamp), state)
            write.assert_not_called()
        state['summary'] = 'טופל עם הלקוח'
        returned = transition(state, state['revision'], {'type':'returnToYossi'}, stamp)
        self.assertFalse(returned['escalation']['active'])

    def test_owner_alert_requires_explicit_destination_and_template(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertIsNone(alert_configuration())
        with patch.dict('os.environ', {'OWNER_ALERT_ENABLED':'true','OWNER_ALERT_PHONE':'972501234567','OWNER_ALERT_TEMPLATE':'yossi_owner_attention'}, clear=True):
            self.assertEqual(alert_configuration(), ('972501234567','yossi_owner_attention','he'))


if __name__ == '__main__':
    unittest.main()
