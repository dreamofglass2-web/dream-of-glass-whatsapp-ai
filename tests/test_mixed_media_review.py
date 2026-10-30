import os,unittest
from unittest.mock import patch
from datetime import datetime
os.environ.setdefault('OPENAI_API_KEY','sk-offline-test-only')
import app as yossi

PHOTO='[לקוח צירף תמונה שנותח בפועל. ממצאים חזותיים, לא מידות מאומתות: בתמונה חדר רחצה עם קיר אחד. המלצה פנימית שאסור לראות כבקשת לקוח: תשלח תמונות של עבודות מקלחונים.]'
VIDEO='[נשלחה סרטון שלא נותחה]'
class MixedMediaReviewTests(unittest.TestCase):
    def setUp(self):
        from tests.test_conversation_simulator import ConversationSimulation
        self.h=ConversationSimulation();self.h.setUp();self.addCleanup(self.h.doCleanups)
        p=patch.object(yossi,'HANDOFF_ENABLED',False);p.start();self.addCleanup(p.stop)
    def test_analyzed_photos_with_unsupported_video_continue_consultation(self):
        text=PHOTO+'\n'+VIDEO+'\nאני רוצה מקלחון עם קיר אחד'
        reply=self.h.step(text,self.h.model('מה מפריע כרגע לפתיחת הדלת במקום הזה?'))
        self.assertIn('פתיחת הדלת',reply)
        self.assertNotIn('לא יכול לפתוח',reply)
        self.assertNotIn('[TEST_IMAGE]',self.h.sent)
    def test_unsupported_video_alone_still_does_not_claim_to_be_seen(self):
        reply=self.h.step(VIDEO)
        self.assertIn('לא יכול לפתוח',reply)
        self.assertFalse(self.h.ai.queue)
    def test_visual_annotations_removed_before_form_label_processing(self):
        from tests.test_form_media_intent import FORM
        text=PHOTO+'\n'+FORM+'\n'+VIDEO
        request=yossi.customer_written_text(text)
        self.assertNotIn('תשלח תמונות',request)
        self.assertNotIn('המלצה פנימית',request)
        self.assertFalse(yossi.requests_portfolio_photos(request))
        self.h.step(text,self.h.model('הפתח מיועד לפינה או בין שני קירות?'))
        self.assertNotIn('[TEST_IMAGE]',self.h.sent)

class CallbackReviewTests(unittest.TestCase):
    def test_availability_wording_from_voice_or_text_is_a_callback(self):
        from tests.test_owner_requests import OwnerRequestTests
        harness=OwnerRequestTests()
        for text in ['נשמח אם תוכל לדבר איתי בזמנך הפנוי, תסביר את זה יותר לעומק.','אתה יכול לדבר איתי שתתפנה ?']:
            self.assertTrue(yossi.is_callback_request(text))
            send,save,callback,work,pause,ai=harness.run_turn(text)
            self.assertIn('מתי נוח',send.call_args.kwargs['body'])
            callback.assert_called_once();ai.assert_not_called();pause.assert_not_called()
        self.assertFalse(yossi.is_callback_request('אני מעדיף להתכתב כאן ולא בטלפון, אפשר לדבר איתי כאן'))
    def test_friday_and_saturday_opening_waits_for_sunday(self):
        for moment in ['2026-10-30T11:00:00+02:00','2026-10-31T15:00:00+02:00']:
            self.assertEqual(yossi.next_yossi_business_open(datetime.fromisoformat(moment)).isoformat(),'2026-11-01T08:00:00+02:00')
