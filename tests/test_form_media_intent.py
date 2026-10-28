import os,unittest
from unittest.mock import patch
os.environ.setdefault('OPENAI_API_KEY','sk-offline-test-only')
import app as yossi
import form_intent
from sales_visuals import handle_photo_request,implicit_visual_request

FORM=('הי! השלמתי את הטופס שלך, וברצוני לדעת יותר על העסק שלך.\n\n'
      'אילו עבודות אתם מחפשים?: מקלחון\nCity: עיר בדיקה\n'
      'יש לכם תמונות / תוכניות / מידות של הפרויקט?: כן, אשלח בוואטסאפ\n'
      'מהו סוג הנכס שלכם?: דירה\nPhone number: +9720501234567\nFull name: לקוח בדיקה\n'
      'באיזה שלב נמצא הפרויקט?: מוכן למדידה עכשיו\nמה הכי חשוב לכם בפרויקט?: פתרון בסיסי במחיר נמוך')
CATALOG=[{'url':'https://example.test/form-sample','product':'מקלחון','glass':'שקופה','configuration':'פינתי','finish':'שחור','handle':'כפתור'}]
class FormMediaIntentTests(unittest.TestCase):
    def test_form_upload_answer_is_not_a_portfolio_catalog_or_handle_request(self):
        for text in [FORM,FORM.replace('כן, אשלח בוואטסאפ','עדיין לא')]:
            self.assertFalse(yossi.requests_portfolio_photos(text));self.assertFalse(yossi.requests_catalog_samples(text))
            self.assertFalse(handle_photo_request(text,[]));self.assertFalse(implicit_visual_request(text))
            self.assertIn('מקלחון',yossi.customer_written_text(text))
            self.assertNotIn('יש לכם תמונות',yossi.customer_written_text(text))
    def test_customer_promise_to_send_photos_is_not_an_imperative_to_the_business(self):
        for text in ['אני אשלח לך תמונות של המקלחון','אשלח תמונות של עבודות שאני אוהב','אני שולחת תמונה של הידית']:
            self.assertFalse(yossi.requests_portfolio_photos(text));self.assertFalse(yossi.requests_catalog_samples(text))
            self.assertFalse(handle_photo_request(text,[]))
    def test_explicit_request_added_to_form_still_allows_appropriate_images(self):
        text=FORM+'\nאפשר לראות דוגמאות של עבודות מקלחונים שלכם?'
        self.assertTrue(yossi.requests_portfolio_photos(text))
        self.assertIn('אפשר לראות דוגמאות',yossi.customer_written_text(text))
    def test_product_inquiry_without_visual_request_does_not_send_portfolio(self):
        for text in ['אני רוצה שני מקלחונים לבית חדש','יש לכם מקלחונים?','אשמח להצעת מחיר עבור עבודות זכוכית']:
            self.assertFalse(yossi.requests_portfolio_photos(text))
        self.assertTrue(yossi.requests_portfolio_photos('תשלח לי עבודות שעשיתם'))

    def test_generated_meta_phone_prefix_with_trunk_zero_is_supported(self):
        import business_pilot
        self.assertTrue(business_pilot.is_customer_form_message('972501234567',{'type':'text','text':{'body':FORM}}))

class FormMediaDeliveryTests(unittest.TestCase):
    def setUp(self):
        from tests.test_conversation_simulator import ConversationSimulation
        self.h=ConversationSimulation();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.patches=[patch.object(yossi,'HANDOFF_ENABLED',False),patch.object(yossi,'PHOTO_CATALOG',CATALOG)]
        for p in self.patches:p.start()
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patches)])
    def test_first_form_turn_asks_next_question_and_never_sends_images(self):
        reply=self.h.step(FORM,self.h.model('כדי להתאים את המקלחון, הוא מיועד לפינה או בין שני קירות?',send_glass_images=True))
        self.assertNotIn('[TEST_IMAGE]',self.h.sent)
        self.assertIn('בין שני קירות',reply)
        self.assertIn('כן, אשלח בוואטסאפ',self.h.memory[self.h.phone][0][0]['content'])
    def test_erroneous_model_caption_does_not_trigger_images_or_false_attachment_claim(self):
        reply=self.h.step(FORM,self.h.model('מצרף לך תמונות לדוגמה',send_glass_images=True))
        self.assertNotIn('[TEST_IMAGE]',self.h.sent)
        self.assertNotIn('מצרף',reply);self.assertNotIn('אין תמונה',reply)
    def test_form_plus_actual_sample_request_can_send_catalog_images(self):
        self.h.step(FORM+'\nאפשר לראות דוגמאות של עבודות מקלחונים שלכם?',self.h.model('מצרף דוגמאות'))
        self.assertIn('[TEST_IMAGE]',self.h.sent)
