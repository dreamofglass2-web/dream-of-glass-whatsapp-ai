import os,unittest
from unittest.mock import patch,MagicMock
os.environ.setdefault('OPENAI_API_KEY','sk-offline-test-only')
import app as yossi
import website_inquiry as w
class WebsiteInquiryTests(unittest.TestCase):
    def test_arrival_is_not_a_generic_website_question(self):
        for text in ['היי הגעתי דרך האתר','הגעתי מהאתר שלכם, אני צריך מקלחון','שלום, באתי דרך האתר']:
            self.assertTrue(w.arrives_from_website(text))
        for text in ['יש לכם אתר?','לא הגעתי דרך האתר','תשלח לי אתר']:
            self.assertFalse(w.arrives_from_website(text))
        self.assertFalse(w.greeting_only('הגעתי דרך האתר, אני צריך מראה'))
    def test_greeting_without_form_gets_a_natural_reply_without_ai_or_photos(self):
        from tests.test_conversation_simulator import ConversationSimulation
        h=ConversationSimulation();h.setUp()
        try:
            with patch.object(yossi,'HANDOFF_ENABLED',False):
                reply=h.step('היי הגעתי דרך האתר')
            self.assertIn('יוסי',reply);self.assertIn('איזו עבודת',reply)
            self.assertNotIn('[TEST_IMAGE]',h.sent)
        finally:h.doCleanups()
    def test_feature_is_explicit_and_records_only_signed_caller_pipeline(self):
        env={'BUSINESS_PILOT_ID':'unit-test','BUSINESS_PILOT_ALLOW_WEBSITE':'true','BUSINESS_PILOT_REQUIRE_FORM':'true','BUSINESS_PILOT_ALL_INBOUND':'false'}
        msg={'type':'text','timestamp':'1793322000','text':{'body':'היי הגעתי דרך האתר'}}
        with patch.dict(os.environ,env),patch.object(yossi,'ensure_db'),patch.object(yossi,'db_connection',return_value=MagicMock()) as db:
            self.assertTrue(yossi.persist_verified_direct_inbound('972501234567',msg));db.assert_called_once()
        with patch.dict(os.environ,dict(env,BUSINESS_PILOT_ALLOW_WEBSITE='false')),patch.object(yossi,'db_connection') as db:
            self.assertFalse(yossi.persist_verified_direct_inbound('972501234567',msg));db.assert_not_called()
