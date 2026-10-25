import unittest
from sales_reply import quote_facts_for_turn, safe_quote_wording, open_finish_question, grounded_price_comparison, retain_known_quote_choices


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
                     self.reply+' קבענו התקנה מחר.', self.reply+' המחיר אחרי הנחה ₪2,000.',
                     self.reply+' אחרי הנחה נסגור ב2000.', self.reply+' יש אחריות על הזכוכית.'):
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

class KnownQuoteChoiceTests(unittest.TestCase):
    def test_recalculation_keeps_choices_but_explicit_new_values_remain_allowed(self):
        prior={'configuration':'חזית קבוע + דלת','width_cm':100,'finish':'שחור'}
        self.assertEqual(retain_known_quote_choices(prior,{'configuration':'שם אחר','finish':'שם אחר'},'תחשב מחדש')['finish'],'שחור')
        self.assertEqual(retain_known_quote_choices(prior,{'width_cm':120},'120')['width_cm'],120)
        self.assertEqual(retain_known_quote_choices(prior,{'width_cm':120},'כמה עולה ברוחב 120')['width_cm'],120)

class ConsultationFactRetentionTests(unittest.TestCase):
    def test_past_experience_does_not_change_current_choice(self):
        from sales_reply import retain_known_quote_choices, normalize_sales_fields
        prior={'configuration':'חזית קבוע + דלת','finish':'שחור'}
        result=retain_known_quote_choices(prior,{'configuration':'הזזה קבוע + דלת','finish':'ניקל'},'היה לי הזזה, אהבתי את הנוחות אבל קשה לנקות')
        self.assertEqual(result,prior)
        result=normalize_sales_fields({'configuration':'מקלחון חזיתי קבוע ודלת'},['חזית קבוע + דלת'],[],[])
        self.assertEqual(result['configuration'],'חזית קבוע + דלת')
        self.assertEqual(normalize_sales_fields({'configuration':'תכנון אחר'},['חזית קבוע + דלת'],[],[])['configuration'],'תכנון אחר')

class PriceGapAcknowledgementTests(unittest.TestCase):
    def test_customer_supplied_gap_is_not_a_new_price(self):
        from sales_reply import grounded_price_comparison
        self.assertTrue(grounded_price_comparison('מבין, 400 ש״ח זה פער ששווה להתייחס אליו.',1964,'קיבלתי הצעה זולה יותר ב-400 שקל'))
        self.assertFalse(grounded_price_comparison('המחיר שלך 400 ש״ח',1964,'קיבלתי הצעה זולה ב-400 שקל'))



class PersonalServiceValueTests(unittest.TestCase):
    def test_hardware_word_is_not_a_cheaper_price_objection(self):
        from sales_reply import is_price_objection
        self.assertFalse(is_price_objection('פרזול שחור וידית כפתור, רוצה הצעה'))
        for text in ('זול יותר','הצעה זולה','המחירים זולים','אפשר להוזיל?','תעשה לי הנחה'):
            with self.subTest(text=text):
                self.assertTrue(is_price_objection(text))

    def test_need_based_live_answer_is_completed_without_repeating_owner_pitch(self):
        from sales_reply import personal_service_value
        model=('הדלת הנפתחת מאפשרת גישה נוחה לניקוי הזכוכית משני הצדדים. '
               'ההצעה כוללת מדידה, הובלה והתקנה, ואלירן מודד ומתקין בעצמו ונשאר כתובת שמכירה את העבודה. '
               'מה התקציב שתכננת למקלחון?')
        answer=personal_service_value(model,'יקר לי',[],product='מקלחון')
        self.assertEqual(answer.count('אלירן'),1)
        self.assertEqual(answer.count('כתובת'),1)
        self.assertIn('ניקוי הזכוכית משני הצדדים',answer)
        for fact in ('פליז פרימיום','7 שנות אחריות על הפרזול','שנה אחריות על ההתקנה','בלי קבלני משנה'):
            self.assertIn(fact,answer)
        self.assertLess(len(answer),450)
        self.assertEqual(answer.count('?'),1)
        self.assertTrue(answer.endswith('מה התקציב שתכננת למקלחון?'))

    def test_owner_remaining_the_contact_is_already_a_customer_benefit(self):
        from sales_reply import personal_service_value
        model=('הדלת הנפתחת מאפשרת גישה לניקוי משני הצדדים. '
               'אלירן מודד ומתקין בעצמו ונשאר הכתובת גם אחרי העבודה. מה התקציב שתכננת?')
        answer=personal_service_value(model,'יקר לי',[],product='מקלחון')
        self.assertEqual(answer.count('כתובת'),1)
        self.assertEqual(answer.count('אלירן'),1)
        self.assertIn('בלי קבלני משנה',answer)
        self.assertIn('7 שנות אחריות על הפרזול',answer)
        self.assertTrue(answer.endswith('מה התקציב שתכננת?'))

    def test_personal_measurement_and_installation_are_recognized_in_other_word_order(self):
        from sales_reply import personal_service_value
        for execution in ('מדידה והתקנה של אלירן בעצמו','אלירן בעצמו יטפל במדידה ובהתקנה'):
            with self.subTest(execution=execution):
                answer=personal_service_value('הדלת מאפשרת גישה לניגוב משני הצדדים. ההצעה כוללת '+execution+', והוא נשאר כתובת שמכירה את העבודה גם אחר כך. איזה תקציב תכננת?', 'יקר לי',[],product='מקלחון')
                self.assertEqual(answer.count('אלירן'),1)
                self.assertEqual(answer.count('כתובת'),1)
                self.assertIn('בלי קבלני משנה',answer)
                self.assertIn('7 שנות אחריות על הפרזול',answer)
                self.assertTrue(answer.endswith('איזה תקציב תכננת?'))

    def test_existing_contact_benefit_is_not_repeated_when_owner_facts_are_missing(self):
        from sales_reply import personal_service_value
        answer=personal_service_value('יש לך כתובת אחת לשירות. מה התקציב?', 'יקר לי',[],product='מקלחון')
        self.assertEqual(answer.count('כתובת'),1)
        self.assertEqual(answer.count('אלירן'),1)
        self.assertIn('מגיע בעצמו למדידה ולהתקנה',answer)

    def test_value_is_added_without_replacing_other_benefits(self):
        from sales_reply import personal_service_value
        for text in ['יקר לי','רוצה להשוות להצעה אחרת','מתחרה הציע לי פחות']:
            answer=personal_service_value('יש 7 שנות אחריות לפרזול.',text,[])
            self.assertIn('7 שנות',answer)
            self.assertIn('בלי קבלני משנה',answer)
            self.assertIn('מההתחלה ועד הסוף',answer)
        self.assertEqual(personal_service_value('תודה','מה השעות?',[]),'תודה')
        self.assertEqual(personal_service_value('בהצלחה','יקר לי, אלך איתם',[]),'בהצלחה')

    def test_value_is_not_repeated_in_the_same_exchange(self):
        from sales_reply import personal_service_value, PERSONAL_SERVICE_VALUE
        h=[{'role':'assistant','content':PERSONAL_SERVICE_VALUE}]
        self.assertEqual(personal_service_value('אפשר לבדוק חלופה.','עדיין יקר לי',h),'אפשר לבדוק חלופה.')


    def test_model_personal_service_only_is_completed_with_material_and_warranty(self):
        from sales_reply import personal_service_value
        reply='אלירן מודד ומתקין בעצמו בלי קבלני משנה ומלווה גם בשירות אחר כך. ההצעה האחרת לאותו מפרט?'
        answer=personal_service_value(reply,'וואו יקר, קיבלתי 2500 כולל מעמ',[],product='אמבטיון')
        for fact in ['פליז פרימיום','7 שנות אחריות על הפרזול','שנה אחריות על ההתקנה','בלי קבלני משנה']:
            self.assertIn(fact,answer)
        self.assertEqual(answer.count('בלי קבלני משנה'),1)
        self.assertTrue(answer.endswith('ההצעה האחרת לאותו מפרט?'))
        self.assertNotIn('אחריות מלאה על הזכוכית',answer)

    def test_full_recent_value_is_not_repeated_and_mirror_does_not_inherit_warranty(self):
        from sales_reply import personal_service_value, PERSONAL_SERVICE_VALUE
        full='פרזול פליז פרימיום עם 7 שנות אחריות על הפרזול ושנה על ההתקנה. '+PERSONAL_SERVICE_VALUE
        history=[{'role':'assistant','content':full}]
        self.assertEqual(personal_service_value('אפשר לבדוק חלופה.','עדיין יקר לי',history,product='מקלחון'),'אפשר לבדוק חלופה.')
        answer=personal_service_value('נבחן חלופה.','יקר לי',[],product='מראה')
        self.assertNotIn('7 שנות',answer)
        self.assertNotIn('פליז',answer)


class ShowerThicknessPolicyTests(unittest.TestCase):
    def test_comparison_is_limited_to_showers_and_does_not_absorb_other_requests(self):
        from sales_reply import shower_thickness_reply
        self.assertIn('8 מ״מ', shower_thickness_reply('מה ההבדל בין 6 מ״מ ל8 מ״מ?', 'אמבטיון'))
        for customer, product in (
            ('למה 8 מ״מ?', 'מראה'),
            ('למה 8 מ״מ וכמה עולה?', 'מקלחון'),
            ('למה 8 מ״מ, יש סדק בזכוכית', 'מקלחון'),
            ('למה 8 מ״מ, רוצה לדבר עם אלירן', 'מקלחון'),
            ('למה 8 מ״מ, זה בטוח ברוחב 200?', 'מקלחון'),
            ('אני רוצה אותו דבר 6 מ״מ', 'מקלחון'),
        ):
            with self.subTest(customer=customer, product=product):
                self.assertIsNone(shower_thickness_reply(customer, product))


class UnsupportedShowerThicknessTests(unittest.TestCase):
    def test_short_unitless_rejection_binds_only_to_the_thickness_exchange(self):
        from sales_reply import shower_six_mm_choice as choice
        policy=['מצטער, אנחנו לא מתעסקים עם זכוכית 6 מ״מ. אנחנו מבצעים מקלחונים בזכוכית מחוסמת 8 מ״מ.']
        for text in ('לא רוצה 8, אני רוצה רק 6','רק 6','6'):
            self.assertEqual(choice(text,'מקלחון',policy),'close')
        self.assertEqual(choice('רוצה 8','מקלחון',policy),'accept_eight')
        for text in ('רוצה 6 פריטים','גובה 80','רוחב 68','רוחב 6 ס״מ'):
            self.assertIsNone(choice(text,'מקלחון',policy))
        self.assertIsNone(choice('רק 6','מקלחון',[]))
        self.assertIsNone(choice('6','מקלחון',policy+['כמה מקלחונים צריך?']))

    def test_preferences_existing_glass_negations_and_other_products(self):
        from sales_reply import shower_six_mm_choice as choice
        policy = ['מצטער, לא מתעסקים ב־6 מ״מ. אנחנו מציעים 8 מ״מ.']
        for text in ('אני רוצה 6 ממ', 'רק 6 מ״מ', 'אפשר מקלחון 6 מ״מ?', '6 מ״מ', 'כמה עולה מקלחון 6 ממ?'):
            with self.subTest(text=text):
                self.assertEqual(choice(text, 'מקלחון'), 'offer_eight')
                self.assertEqual(choice(text, 'מקלחון', policy), 'close')
        self.assertEqual(choice('אני לא רוצה 8 ממ אבל', 'מקלחון', policy), 'close')
        self.assertEqual(choice('אני לא רוצה 6 ממ\n8 ממ', 'מקלחון', policy), 'accept_eight')
        for text, product in (('יש לי מקלחון 6 ממ', 'מקלחון'),
                              ('למה צריך 8 מ״מ אם יש לי 6 מ״מ?', 'מקלחון'),
                              ('אני רוצה 6 ממ', 'מראה'),
                              ('רוצה 6 ממ אבל דבר עם אלירן', 'מקלחון')):
            with self.subTest(text=text):
                self.assertIsNone(choice(text, product, policy))


class ColorNameIsNotPriceObjectionTests(unittest.TestCase):
    def test_color_question_preserves_brief_bronze_clarification(self):
        from sales_reply import personal_service_value
        answer = 'יכול להיות שאתה מתכוון לברונזה, גוון חום חמים. זה הגוון שהתכוונת אליו?'
        for customer in ('צבע קפה כזה איך זה ניקרא ?', 'איך נקרא הגוון הזה?', 'ברונזה איך זה ניקרא'):
            with self.subTest(customer=customer):
                self.assertEqual(personal_service_value(answer, customer, [], product='מקלחון'), answer)

    def test_real_price_objections_still_include_value(self):
        from sales_reply import personal_service_value
        for customer in ('יקר לי', 'ההצעה יקרה', 'המחירים יקרים', 'זה התייקר', 'יקר!'):
            with self.subTest(customer=customer):
                self.assertIn('פליז פרימיום', personal_service_value('נבדוק מה חשוב לך.', customer, [], product='מקלחון'))


class CustomerBenefitPersuasionTests(unittest.TestCase):
    def test_fact_only_model_answer_gets_a_reason_to_choose_the_service(self):
        from sales_reply import personal_service_value
        facts = ('פרזול פליז פרימיום, 7 שנות אחריות על הפרזול ושנה על ההתקנה. '
                 'אלירן מגיע בעצמו בלי קבלני משנה. מה חשוב לך בהשוואה?')
        reply = personal_service_value(facts, 'קיבלתי הצעה אחרת זולה יותר, למה לקנות אצלכם?', [], product='מקלחון')
        self.assertIn('כתובת אחת', reply)
        self.assertIn('בלי שתצטרך לתאם', reply)
        self.assertEqual(reply.count('7 שנות'), 1)
        self.assertTrue(reply.endswith('מה חשוב לך בהשוואה?'))
        self.assertNotIn('יחסוך לך', reply)

    def test_existing_customer_benefit_is_preserved_without_another_pitch(self):
        from sales_reply import personal_service_value
        reply = ('פרזול פליז פרימיום עם 7 שנות אחריות על הפרזול ושנה על ההתקנה. '
                 'אלירן מגיע בעצמו בלי קבלני משנה, כך שיש לך כתובת אחת שמכירה את העבודה. '
                 'אם הליווי הזה חשוב לך, נוכל להתקדם עם ההצעה שלנו.')
        self.assertEqual(personal_service_value(reply, 'יקר לי ביחס להצעה האחרת', [], product='מקלחון'), reply)


class EquivalentCompetitorOfferTests(unittest.TestCase):
    def test_same_offer_is_not_met_with_another_specification_question(self):
        from sales_reply import personal_service_value
        reply = personal_service_value('ההצעה האחרת לאותו מפרט?',
            'המתחרה נותן את אותו הדבר בדיוק אבל זול יותר', [], product='מקלחון')
        self.assertNotIn('לאותו מפרט?', reply)
        self.assertIn('ממליץ', reply)
        self.assertIn('כתובת אחת', reply)
        self.assertNotIn('איכות נמוכה', reply)
        self.assertNotIn('יחסוך', reply)


class NoDiscountPolicyTests(unittest.TestCase):
    def test_old_policy_and_owner_check_cannot_offer_discount(self):
        from sales_reply import no_discount_reply
        for reply in ('אפשר להציע הנחה עד 7%.', 'אבדוק הנחה מול אלירן.',
                      'במזומן נוריד 5 אחוז.', 'אפשר להוריד את המחיר.', 'יש קופון בשבילך'):
            with self.subTest(reply=reply):
                result=no_discount_reply(reply)
                self.assertIn('לא נותנים הנחות', result)
                self.assertNotIn('אבדוק',result)
                self.assertNotIn('%',result)
                self.assertIn('שינוי במפרט', result)

    def test_specification_alternative_and_warranty_are_preserved(self):
        from sales_reply import no_discount_reply
        reply='אפשר לבחון גוון אחר ולחשב הצעה חדשה. יש 7 שנות אחריות לפרזול.'
        self.assertEqual(no_discount_reply(reply),reply)
