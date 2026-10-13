import unittest
from sales_reply import quote_facts_for_turn, safe_quote_wording, open_finish_question, grounded_price_comparison


class QuoteGroundingTests(unittest.TestCase):
    def setUp(self):
        self.specs = dict(product='מקלחון',configuration='חזית קבוע + דלת',width_cm=120,
                          glass_type='שקופה',finish='שחור',handles=['ידית מגבת'])
        self.reply = ('לכניסה הנוחה שרצית, ההצעה הראשונית היא ₪2,314 לפני מע״מ, '
                      'כולל מדידה, הובלה והתקנה. את המידות נבדוק בשטח; '
                      'שינוי במידות עשוי לשנות את המחיר. איך זה נשמע לך?')

    def test_owner_default_height_is_grounding_not_customer_measurement(self):
        seen=[]
        facts=quote_facts_for_turn(self.specs,'כמה זה עולה?',lambda specs:seen.append(specs) or 2314.4)
        self.assertEqual(seen[0]['height_cm'],200)
        self.assertNotIn('height_cm',self.specs)
        self.assertTrue(facts['preliminary'])

    def test_explicit_height_overrides_old_height(self):
        specs=dict(self.specs,height_cm=190)
        facts=quote_facts_for_turn(specs,'תחשב לפי גובה 210',lambda specs:specs['height_cm'])
        self.assertEqual(facts['specification']['height_cm'],210)

    def test_changed_job_material_and_other_products_do_not_reuse_old_price(self):
        for text in ('בעצם רוצה חלבי','מקלחון אחר','לחדר אחר','מחפש מראה','תשנה לשחור'):
            with self.subTest(text=text):
                self.assertIsNone(quote_facts_for_turn(self.specs,text,lambda _:9999))
        self.assertIsNone(quote_facts_for_turn(dict(product='מראה'),'כמה עולה?',lambda _:9999))

    def test_incomplete_calculator_input_does_not_authorize_amount(self):
        self.assertIsNone(quote_facts_for_turn(self.specs,'מחיר?',lambda _:None))

    def test_grounded_consultative_quote_is_preserved(self):
        self.assertTrue(safe_quote_wording(self.reply,2314.4))

    def test_unverified_amount_vat_missing_terms_or_fake_action_is_rejected(self):
        for text in (self.reply.replace('2,314','500'),self.reply.replace('לפני מע״מ','כולל מע״מ'),
                     self.reply.replace('ראשונית','סופית'),self.reply.replace('הובלה',''),
                     self.reply+' קבענו התקנה מחר.', self.reply+' המחיר אחרי הנחה ₪2,000.'):
            with self.subTest(text=text):
                self.assertFalse(safe_quote_wording(text,2314.4))

class ConsultationPreservationTests(unittest.TestCase):
    def test_finish_list_changes_only_the_question(self):
        reply='אפשר להשאיר מעבר נוח. איזה גוון פרזול תרצו, שחור או כרום?'
        self.assertEqual(open_finish_question(reply,'חשוב לי נוחות'),
                         'אפשר להשאיר מעבר נוח. איזה גוון פרזול תרצו?')
        self.assertEqual(open_finish_question(reply,'איזה צבעים יש?'),reply)

    def test_price_gap_requires_customer_evidence_and_relative_wording(self):
        self.assertTrue(grounded_price_comparison('המחיר שלנו 700 שקל יותר',2595,'קיבלתי הצעה זולה ב-700 שקל'))
        self.assertFalse(grounded_price_comparison('המחיר שלנו 700 שקל',2595,'קיבלתי הצעה זולה ב-700 שקל'))
        self.assertFalse(grounded_price_comparison('אפשר 500 שקל פחות',2595,'תעשה לי ב500'))
