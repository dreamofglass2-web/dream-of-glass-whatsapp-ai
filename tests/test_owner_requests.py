import os, json, types, unittest
from unittest.mock import patch, MagicMock
os.environ.setdefault('OPENAI_API_KEY','sk-offline-test-only')
import app as yossi
from handoff_state import new_state
from owner_requests import unavailable_quote, conversation_summary, QUOTE_REASON, CALLBACK_REASON
class OwnerRequestTests(unittest.TestCase):
    def run_turn(self, text, history=(), prior=None, model=None):
        from contextlib import ExitStack
        with ExitStack() as stack:
            for name,value in [('HANDOFF_ENABLED',True),('TYPING_MIN',0),('TYPING_MAX',0)]:
                stack.enter_context(patch.object(yossi,name,value))
            for name in ['ensure_db']:
                stack.enter_context(patch.object(yossi,name))
            stack.enter_context(patch.object(yossi,'db_connection',return_value=MagicMock()))
            stack.enter_context(patch.object(yossi,'read_handoff_state',return_value=new_state()))
            stack.enter_context(patch.object(yossi,'load_conversation',return_value=(list(history),prior or {})))
            stack.enter_context(patch.object(yossi,'has_new_messages',return_value=False))
            stack.enter_context(patch.object(yossi,'waiting_for_callback_time',return_value=False))
            send=stack.enter_context(patch.object(yossi,'send_whatsapp'))
            save=stack.enter_context(patch.object(yossi,'save_conversation'))
            callback=stack.enter_context(patch.object(yossi,'save_callback',return_value=True))
            work=stack.enter_context(patch.object(yossi,'owner_work_request',return_value=True))
            pause=stack.enter_context(patch.object(yossi,'pause_for_owner',return_value=True))
            ai=stack.enter_context(patch.object(yossi.client.responses,'create',return_value=types.SimpleNamespace(output_text=json.dumps(model or {}))))
            self.assertTrue(yossi.process_message('TEST_ONLY',text))
            return send,save,callback,work,pause,ai
    def test_callback_asks_time_before_uncertain_model(self):
        send,save,callback,work,pause,ai=self.run_turn('היי תתקשרו אליי בבקשה')
        self.assertIn('מתי נוח',send.call_args.kwargs['body'])
        callback.assert_called_once();ai.assert_not_called();pause.assert_not_called();work.assert_not_called()
    def test_callback_time_creates_owner_task_without_ai(self):
        history=[{'role':'user','content':'תתקשרו אליי'},{'role':'assistant','content':'בשמחה, מתי נוח לך שנתקשר?'}]
        send,save,callback,work,pause,ai=self.run_turn('מחר בשעה 10',history)
        self.assertEqual(work.call_args.args[4],CALLBACK_REASON)
        self.assertIn('10:00',work.call_args.args[3]['callback_preferred_time'])
        ai.assert_not_called()
    def test_mirror_quote_ready_hands_off_instead_of_file_denial(self):
        history=[{'role':'user','content':'מראה קוטר 60 ללא מסגרת עם תאורה ברמלה לחדר רחצה'},{'role':'assistant','content':'להכין לך הצעת מחיר למראה שבחרת עם התאורה?'}]
        send,save,callback,work,pause,ai=self.run_turn('כן',history,{'product':'מראה','customer_name':'אלירן','sales_discovery_completed':True}, {'reply':'הפרטים להכנת ההצעה הושלמו. ההצעה תכלול את התאורה וההתקנה.','product':'מראה','stage':'quote_preparation','quote_requested':True,'needs_human':False})
        self.assertEqual(work.call_args.args[4],QUOTE_REASON)
        self.assertEqual(work.call_args.args[5],'אוקי, אני מכין לך הצעת מחיר.')
        send.assert_not_called();pause.assert_not_called()
    def test_unknown_professional_answer_pauses_for_all_products(self):
        for product in ['מראה','מחיצה','חיפוי זכוכית','דלת זכוכית']:
            with self.subTest(product=product):
                *_,pause,ai=self.run_turn('האם אפשר לבצע את החיבור הזה?',[],{'product':product,'sales_discovery_completed':True},{'reply':'לא יודע','product':product,'needs_human':True})
                pause.assert_called_once()
    def test_summary_uses_customer_evidence(self):
        summary=conversation_summary([{'role':'user','content':'מראה קוטר 60 ברמלה'},{'role':'assistant','content':'מחיר מומצא 100'}],QUOTE_REASON)
        self.assertIn('קוטר 60',summary);self.assertNotIn('100',summary)
    def test_quote_denials_recognized_but_real_question_is_not(self):
        self.assertTrue(unavailable_quote('כרגע אין לי קובץ הצעה מוכן עם המחיר לצרף.',{}, {}, []))
        self.assertFalse(unavailable_quote('באיזו עיר ההתקנה?',{}, {}, []))
