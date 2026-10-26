import unittest
from unittest.mock import patch, MagicMock
from handoff_state import new_state
import tests.test_conversation_simulator as sim
import app as yossi
from layout_consultation import layout_consultation_reply

class LayoutAdviceJourney(sim.ConversationSimulation):
    def test_competitor_amount_does_not_erase_the_qualitative_price_answer(self):
        specs={'product':'מקלחון','configuration':'חזית קבוע + דלת','width_cm':150,'height_cm':200,
               'glass_type':'שקופה','finish':'שחור','handles':['ידית כפתור'],'solution_agreed':True}
        offer=yossi.bundle_offer({'sales_items':{'1':specs}},yossi.calculate_quote,allow_single=True)
        self.memory[self.phone]=([{'role':'assistant','content':'תרצי לבדוק גוון אחר?'}],
            dict(specs,sales_discovery_completed=True,combined_offer=dict(offer,issued=True),
                 validated_quote=dict(specs,issued=True,amount_ils_pre_vat=offer['amount_ils_pre_vat'])))
        answer=('ההצעה שקיבלת היא 1800 ש״ח כולל מע״מ. נשמור על הפרזול השחור שבחרת. '
                'אלירן מודד ומתקין בעצמו בלי קבלני משנה ונשאר כתובת שמכירה את העבודה. חשוב לך הליווי האישי הזה?')
        with patch.object(yossi,'PDF_QUOTES_ENABLED',True):
            reply=self.step('אני לא רוצה לשנות את השחור. מתחרה נותן לי אותו מפרט ב1800 כולל מעמ',self.model(answer,**specs))
        self.assertIn('נשמור על הפרזול השחור',reply)
        self.assertIn('הליווי האישי',reply)
        self.assertNotIn('המחיר מפורט בהצעת',reply)
        self.assertFalse(yossi.contains_ils_amount(reply))
        self.assertFalse(self.documents)
        self.assertEqual(self.memory[self.phone][1]['combined_offer']['fingerprint'],offer['fingerprint'])

    def test_short_six_mm_insistence_closes_without_discovery_or_model_call(self):
        initial=self.step('כמה עולה מקלחון 6 ממ?')
        self.assertIn('קשיחה יותר',initial)
        with patch.object(yossi.client.responses,'create') as ai:
            reply=self.step('לא רוצה 8, אני רוצה רק 6')
        ai.assert_not_called()
        self.assertNotIn('?',reply)
        self.assertIn('תודה שפנית',reply)
        self.assertTrue(self.memory[self.phone][1]['sales_closed'])
        self.assertFalse(self.documents)

    def test_first_complete_customer_specification_delivers_document_without_reasking_layout(self):
        specs={'product':'מקלחון','configuration':'חזית קבוע + דלת','width_cm':150,'height_cm':200,
               'glass_type':'שקופה','finish':'שחור','handles':['ידית כפתור'],'solution_agreed':True}
        customer='שלום אני דנה, מחליפה מקלחון ישן ברחובות. חשוב לי שיהיה נוח לנקות. רוצה הצעה לחזית קבוע ודלת ברוחב 150 וגובה 200, זכוכית שקופה, פרזול שחור וידית כפתור. יש מקום לפתוח את הדלת'
        self.memory[self.phone]=([],{})
        with patch.object(yossi,'PDF_QUOTES_ENABLED',True):
            reply=self.step(customer,self.model('אפשר לוודא את חלוקת המקלחון?',quote_requested=True,**specs))
        self.assertEqual(len(self.documents),1)
        self.assertIn('מצורפת הצעת המחיר',reply)
        self.assertNotIn('לוודא',reply)
        self.assertEqual(self.documents[0]['items'][0]['specification']['width_cm'],150)
        self.assertFalse(yossi.contains_ils_amount(reply))

    def test_discount_request_is_an_objection_not_a_duplicate_document(self):
        specs={'product':'מקלחון','configuration':'חזית קבוע + דלת','width_cm':150,'height_cm':200,
               'glass_type':'שקופה','finish':'שחור','handles':['ידית כפתור'],'solution_agreed':True}
        offer=yossi.bundle_offer({'sales_items':{'1':specs}},yossi.calculate_quote,allow_single=True)
        for request in ('חשבתי עד 2000 כולל מעמ, אתה יכול לעשות לי הנחה?','יש אפשרות להנחה?','תעשה לי מחיר טוב'):
            with self.subTest(request=request):
                self.memory[self.phone]=([{'role':'assistant','content':'מה התקציב שתכננת?'}],
                    dict(specs,sales_discovery_completed=True,combined_offer=dict(offer,issued=True)))
                with patch.object(yossi,'PDF_QUOTES_ENABLED',True):
                    reply=self.step(request,self.model('אפשר לבדוק שינוי בגוון הפרזול, בלי לשנות את המבנה שקל לך לנקות. תרצי לבדוק חלופה?',quote_requested=True,**specs))
                self.assertTrue(yossi.price_objection(request))
                self.assertFalse(self.documents)
                self.assertIn('לבדוק חלופה',reply)
                self.assertFalse(yossi.contains_ils_amount(reply))
                self.assertEqual(self.memory[self.phone][1]['combined_offer']['fingerprint'],offer['fingerprint'])

    def test_budget_acknowledgement_does_not_restart_layout_discovery_after_pdf(self):
        specs={'product':'מקלחון','configuration':'חזית קבוע + דלת','width_cm':150,'height_cm':200,
               'glass_type':'שקופה','finish':'שחור','handles':['ידית כפתור'],'solution_agreed':True}
        offer=yossi.bundle_offer({'sales_items':{'1':specs}},yossi.calculate_quote,allow_single=True)
        self.memory[self.phone]=([{'role':'assistant','content':'מה התקציב שתכננת?'}],
            dict(specs,sales_discovery_completed=True,combined_offer=dict(offer,issued=True)))
        answer='מבין שחשבת על 2000 ש״ח כולל מע״מ. אפשר לבדוק שינוי בגוון הפרזול בלי לשנות את המבנה שנוח לך לנקות. תרצי לבדוק חלופה?'
        with patch.object(yossi,'PDF_QUOTES_ENABLED',True):
            reply=self.step('חשבתי עד 2000 כולל מעמ, אתה יכול לעשות לי הנחה?',self.model(answer,quote_requested=True,**specs))
        self.assertIn('לבדוק חלופה',reply)
        self.assertNotIn('חלוקת המקלחון',reply)
        self.assertFalse(yossi.contains_ils_amount(reply))
        self.assertFalse(self.documents)
        self.assertEqual(self.memory[self.phone][1]['combined_offer']['fingerprint'],offer['fingerprint'])

    def test_single_shower_keeps_toilet_side_and_advances_to_clearance(self):
        question='אין בעיה, אפשר להתחיל מתיאור. האסלה נמצאת מימין או משמאל לפתח המקלחת כשעומדים מולו?'
        self.memory[self.phone]=([{'role':'user','content':'אין לי צילום'},
            {'role':'assistant','content':question}],
            {'product':'מקלחון','layout_geometry':'front','customer_photo_unavailable':True,'sales_discovery_completed':True})
        reply=self.step('משמאל',self.model('אפשר לשלוח צילום?'))
        self.assertIn('כמה מרווח',reply)
        self.assertNotIn('מימין או משמאל',reply)
        self.assertEqual(self.memory[self.phone][1]['obstacle_side'],'משמאל')
        reply=self.step('20 בערך',self.model('אפשר לשלוח צילום?',width_cm=20))
        self.assertIn('עומק',reply)
        self.assertEqual(self.memory[self.phone][1]['obstacle_clearance_cm'],20)
        self.assertNotIn('width_cm',self.memory[self.phone][1])
        self.assertFalse(self.documents)

    def test_unknown_width_does_not_become_a_sliding_recommendation(self):
        self.memory[self.phone]=([{'role':'user','content':'אין לי מידות'},
            {'role':'assistant','content':'יש אסלה קרובה?'}],
            {'product':'מקלחון','layout_geometry':'front','sales_discovery_completed':True})
        reply=self.step('כן',self.model('בגלל האסלה כדאי לבחון הזזה עם מסילה עליונה. באיזו עיר ההתקנה?'))
        self.assertIn('רק מ־140',reply)
        self.assertNotIn('בגלל האסלה כדאי',reply)
        self.assertTrue(reply.endswith('באיזו עיר ההתקנה?'))
        self.assertNotIn('configuration',self.memory[self.phone][1])
        self.assertFalse(self.documents)

    def test_personal_price_answer_survives_issued_document_guards(self):
        specs={'product':'מקלחון','configuration':'חזית קבוע + דלת','width_cm':150,'height_cm':200,
               'glass_type':'שקופה','finish':'שחור','handles':['ידית כפתור'],'solution_agreed':True}
        offer=yossi.bundle_offer({'sales_items':{'1':specs}},yossi.calculate_quote,allow_single=True)
        self.memory[self.phone]=([{'role':'user','content':'חשוב לי שיהיה קל לנקות ושלא יצאו מים'},
            {'role':'assistant','content':'מצורפת ההצעה הראשונית שבחרנו.'}],
            dict(specs,sales_discovery_completed=True,combined_offer=dict(offer,issued=True)))
        answer=('מבין שחשוב לך לבדוק את ההוצאה. בחרנו קבוע ודלת בלי מסילת הזזה לניקוי, עם סגירה שעוזרת לצמצם התזות. '
                'אלירן מגיע בעצמו בלי קבלני משנה למדידה ולהתקנה ונשאר כתובת אחת לשירות. '
                'ההצעה כוללת פליז פרימיום, 7 שנות אחריות לפרזול ושנה על ההתקנה. מה התקציב שתכננת?')
        reply=self.step('יקר לי',self.model(answer,**specs))
        self.assertIn('בלי מסילת הזזה לניקוי',reply)
        self.assertIn('לצמצם התזות',reply)
        self.assertIn('כתובת אחת',reply)
        self.assertTrue(reply.endswith('מה התקציב שתכננת?'))
        self.assertFalse(yossi.contains_ils_amount(reply))
        self.assertFalse(self.documents)
        self.assertEqual(self.memory[self.phone][1]['combined_offer']['fingerprint'],offer['fingerprint'])

    def test_front_answer_survives_later_uncertainty_about_toilet_clearance(self):
        question='המקלחון בפינה עם שני צדדי זכוכית, או עם זכוכית רק בחזית?'
        self.memory[self.phone]=([{'role':'user','content':'אין לי מידות ואני לא בבית'},
            {'role':'assistant','content':question}], {'product':'מקלחון','sales_discovery_completed':True})
        advice='בחזית אפשר לבחון דלת ציר לפי המרווח. יש אסלה או ארון קרובים שמפריעים?'
        self.step('רק בחזית',self.model(advice))
        self.assertEqual(self.memory[self.phone][1].get('layout_geometry'),'front')
        self.assertNotIn('configuration',self.memory[self.phone][1])
        followup='כשתהיה בבית נבדוק רוחב ומרווח ליד האסלה לפני בחירת פתיחה. בינתיים אפשר לבחור זכוכית לפרטיות.'
        with patch.object(yossi,'HANDOFF_ENABLED',True),patch.object(yossi,'ensure_db'),patch.object(yossi,'db_connection',return_value=MagicMock()),patch.object(yossi,'read_handoff_state',return_value=new_state()),patch.object(yossi,'pause_for_owner') as pause:
            reply=self.step('יש אסלה ממש קרובה ואני לא יודע כמה מקום נשאר',self.model(followup))
        pause.assert_not_called()
        self.assertEqual(reply,followup)
        self.assertFalse(self.documents)
        self.assertNotIn('width_cm',self.memory[self.phone][1])

    def test_three_item_price_fallback_becomes_helpful_guidance_without_owner_alert(self):
        h=[{'role':'user','content':'אני צריך 3 מקלחונים'},
           {'role':'assistant','content':'מה שמך?'},{'role':'user','content':'אלירן'},
           {'role':'assistant','content':'למה העבודה?'},{'role':'user','content':'לשיפוץ'},
           {'role':'assistant','content':'מה היית רוצה לשפר?'},
           {'role':'user','content':'לא יודע אני רק רוצה לדעת כמה יעלה לי'},
           {'role':'assistant','content':'כדי להציג הצעה מלאה לכל המקלחונים, נשלים את פרטי מקלחון 1. איך מחולקות הזכוכיות והדלתות?'}]
        prior={'sales_discovery_completed':True,'product':'מקלחון','quote_requested':True,
               'expected_sales_item_count':3,'active_sales_item':'1','sales_items':{'1':{'product':'מקלחון'}}}
        self.memory[self.phone]=(h,prior)
        with patch.object(yossi,'HANDOFF_ENABLED',True),patch.object(yossi,'ensure_db'),patch.object(yossi,'db_connection',return_value=MagicMock()),patch.object(yossi,'read_handoff_state',return_value=new_state()),patch.object(yossi,'pause_for_owner') as pause:
            reply=self.step('אין לי מושג , מה אתה ממליץ',self.model(h[-1]['content'],quote_requested=True))
        pause.assert_not_called()
        self.assertIn('אפשר לשלוח תמונה',reply)
        self.assertNotIn('איך מחולקות',reply)
        self.assertFalse(self.documents)
        self.assertFalse(self.memory[self.phone][1].get('solution_agreed'))

    def test_corner_answer_survives_multi_item_quote_fallback_and_next_turn(self):
        h=[{'role':'user','content':'צריך 3 מקלחונים'},
           {'role':'assistant','content':'במקלחון הראשון צריך לסגור צד אחד בין קירות או שני צדדים בפינה?'}]
        self.memory[self.phone]=(h,{'product':'מקלחון','sales_discovery_completed':True,
            'quote_requested':True,'expected_sales_item_count':3,'active_sales_item':'1',
            'sales_items':{'1':{'product':'מקלחון'}}})
        reply=self.step('בפינה',self.model('צריך לסגור צד אחד בין שני קירות, או שני צדדים שנפגשים בפינה?',quote_requested=True))
        self.assertIn('מידות',reply)
        saved=self.memory[self.phone][1]
        self.assertEqual(saved['sales_items']['1']['layout_geometry'],'corner')
        self.assertNotIn('configuration',saved['sales_items']['1'])
        from sales_items import item_context,save_item
        switched=item_context(saved,h+[{'role':'user','content':'נעבור למקלחון השני'}],'נעבור למקלחון השני')
        self.assertNotIn('layout_geometry',switched)
        self.assertNotIn('layout_geometry',switched['sales_items']['2'])
        self.assertEqual(switched['sales_items']['1']['layout_geometry'],'corner')


    def test_no_obstruction_leads_to_proposal_then_acceptance_moves_to_glass(self):
        question='יש ליד המקלחת ארון או אסלה שעלולים להפריע לפתיחת הדלתות?'
        specs={'product':'מקלחון','layout_geometry':'corner','width_cm':90,'second_width_cm':90}
        self.memory[self.phone]=([{'role':'user','content':'90 על 90'},{'role':'assistant','content':question}],
            dict(specs,sales_discovery_completed=True,quote_requested=True,active_sales_item='1',
                 expected_sales_item_count=3,sales_items={'1':dict(specs)}))
        with patch.object(yossi,'HANDOFF_ENABLED',True),patch.object(yossi,'ensure_db'),patch.object(yossi,'db_connection',return_value=MagicMock()),patch.object(yossi,'read_handoff_state',return_value=new_state()),patch.object(yossi,'pause_for_owner') as pause:
            reply=self.step('לא',self.model(question,quote_requested=True))
        pause.assert_not_called()
        self.assertIn('שתי דלתות שנפגשות בפינה',reply)
        saved=self.memory[self.phone][1]
        self.assertIs(saved['sales_items']['1']['door_obstruction'],False)
        self.assertFalse(saved['sales_items']['1'].get('solution_agreed'))
        reply=self.step('כן',self.model('איזה סוג זכוכית תרצה?',configuration='פינתי 2 דלתות',solution_agreed=True,quote_requested=True))
        self.assertIn('זכוכית',reply)
        self.assertNotIn('ארון או אסלה',reply)
        self.assertEqual(self.memory[self.phone][1]['sales_items']['1']['configuration'],'פינתי 2 דלתות')


    def test_glass_options_typo_is_answered_instead_of_repeated_quote_question(self):
        question='איזה סוג זכוכית תרצו למקלחון?'
        specs={'product':'מקלחון','configuration':'פינתי 2 דלתות','width_cm':90,'second_width_cm':90,'solution_agreed':True}
        for request in ['מה האפשרויות?','מה האפשרוית ?','מה האופציות?']:
            self.memory[self.phone]=([{'role':'user','content':'צריך 3 מקלחונים'},{'role':'assistant','content':question}],
                dict(specs,sales_discovery_completed=True,quote_requested=True,active_sales_item='1',
                     expected_sales_item_count=3,sales_items={'1':dict(specs)}))
            with patch.object(yossi,'HANDOFF_ENABLED',True),patch.object(yossi,'ensure_db'),patch.object(yossi,'db_connection',return_value=MagicMock()),patch.object(yossi,'read_handoff_state',return_value=new_state()),patch.object(yossi,'pause_for_owner') as pause:
                reply=self.step(request,self.model(question,configuration='פינתי 2 דלתות',quote_requested=True,solution_agreed=True))
            pause.assert_not_called()
            self.assertIn('אקסטרה קליר',reply)
            self.assertIn('פרטיות',reply)
            self.assertNotIn('נשלים את פרטי',reply)
            self.assertFalse(self.documents)


    def test_sticky_quote_request_does_not_erase_current_preference_consultation(self):
        question='מה חשוב לך יותר בזכוכית, מראה שקוף ופתוח או פרטיות?'
        specs={'product':'מקלחון','configuration':'פינתי 2 דלתות','width_cm':90,'second_width_cm':90,'solution_agreed':True}
        self.memory[self.phone]=([{'role':'user','content':'צריך 3 מקלחונים'},{'role':'assistant','content':question}],
            dict(specs,sales_discovery_completed=True,quote_requested=True,active_sales_item='1',
                 expected_sales_item_count=3,sales_items={'1':dict(specs)}))
        advice='למראה כהה יש אנטיסן אפור למראה קריר או ברונזה למראה חם. שניהם עדיין שקופים במידה מסוימת. איזה מהם יותר מתאים לחדר שלך?'
        reply=self.step('אני רוצה כהה אבל לא יודע איזה גוון',self.model(advice,configuration='פינתי 2 דלתות',quote_requested=True,solution_agreed=True))
        self.assertIn('אנטיסן אפור',reply)
        self.assertIn('ברונזה',reply)
        self.assertNotIn('נשלים את פרטי',reply)
        self.assertNotIn('glass_type',self.memory[self.phone][1]['sales_items']['1'])
        self.assertFalse(self.documents)


    def test_recommended_bronze_picture_then_customer_choice_advances(self):
        previous='עם אריחי בז וברזים שחורים הייתי ממליץ על אנטיסן ברונזה. אנטיסן אפור הוא חלופה. נלך על ברונזה למקלחון הראשון?'
        specs={'product':'מקלחון','configuration':'פינתי 2 דלתות','width_cm':90,'second_width_cm':90,'solution_agreed':True}
        self.memory[self.phone]=([{'role':'user','content':'צריך 3 מקלחונים'},{'role':'assistant','content':previous}],
            dict(specs,sales_discovery_completed=True,quote_requested=True,active_sales_item='1',expected_sales_item_count=3,sales_items={'1':dict(specs)}))
        catalog=[dict(url='https://example.test/bronze',glass='אנטיסן ברונזה',product='מקלחון',configuration='חזית'),
                 dict(url='https://example.test/grey',glass='אנטיסן אפור',product='מקלחון',configuration='פינתי')]
        with patch.object(yossi,'PHOTO_CATALOG',catalog),patch.object(yossi,'send_whatsapp',side_effect=self.send) as send:
            reply=self.step('אפשר לראות איך זה נראה ?',self.model('איזה סוג זכוכית תרצו למקלחון?',quote_requested=True,configuration='פינתי 2 דלתות',solution_agreed=True))
        images=[c.kwargs['image_url'] for c in send.call_args_list if c.kwargs.get('image_url')]
        self.assertEqual(images,['https://example.test/bronze'])
        self.assertIn('מה דעתך על הגוון',reply)
        self.assertNotIn('נשלים את פרטי',reply)
        self.assertNotIn('glass_type',self.memory[self.phone][1]['sales_items']['1'])
        reply=self.step('נלך על ברונזה',self.model('איזה גוון פרזול תרצה?',glass_type='אנטיסן ברונזה',configuration='פינתי 2 דלתות',solution_agreed=True,quote_requested=True))
        self.assertIn('פרזול',reply)
        self.assertEqual(self.memory[self.phone][1]['sales_items']['1']['glass_type'],'אנטיסן ברונזה')


    def test_finished_first_of_three_advances_without_partial_offer_or_document(self):
        specs={'product':'מקלחון','configuration':'פינתי 2 דלתות','width_cm':90,'second_width_cm':90,
               'glass_type':'אנטיסן ברונזה','finish':'שחור','solution_agreed':True}
        self.memory[self.phone]=([{'role':'user','content':'צריך 3 מקלחונים'},{'role':'assistant','content':'איזה ידיות תרצה לשתי הדלתות?'}],
            dict(specs,sales_discovery_completed=True,quote_requested=True,active_sales_item='1',expected_sales_item_count=3,
                 sales_items={'1':dict(specs),'2':{},'3':{}}))
        with patch.object(yossi,'PDF_QUOTES_ENABLED',True):
            reply=self.step('כפתור בשתי הדלתות',self.model('אפשר לחשב את ההצעה לפי הפרטים שסיכמנו.',
                **dict(specs,handles=['ידית כפתור','ידית כפתור'],quote_requested=True)))
        self.assertIn('השני',reply)
        self.assertFalse(self.documents)
        self.assertNotIn('validated_quote',self.memory[self.phone][1])
        self.assertNotIn('אפשר לחשב',reply)
        self.assertFalse(yossi.contains_ils_amount(reply))
        reply=self.step('בפינה',self.model('מה המידות המשוערות של שני הצדדים?',quote_requested=True))
        saved=self.memory[self.phone][1]
        self.assertEqual(saved['active_sales_item'],'2')
        self.assertEqual(saved['sales_items']['1']['handles'],['ידית כפתור','ידית כפתור'])
        self.assertNotIn('handles',saved['sales_items']['2'])


    def test_combined_document_is_sent_only_after_third_item_is_complete(self):
        specs={'product':'מקלחון','configuration':'פינתי 2 דלתות','width_cm':90,'second_width_cm':90,
               'glass_type':'אנטיסן ברונזה','finish':'שחור','handles':['ידית כפתור','ידית כפתור'],'solution_agreed':True}
        third=dict(specs);third.pop('handles')
        self.memory[self.phone]=([{'role':'user','content':'צריך 3 מקלחונים'},{'role':'assistant','content':'במקלחון השלישי, איזה ידיות תרצה?'}],
            dict(third,sales_discovery_completed=True,quote_requested=True,active_sales_item='3',expected_sales_item_count=3,
                 sales_items={'1':dict(specs),'2':dict(specs),'3':dict(third)}))
        with patch.object(yossi,'PDF_QUOTES_ENABLED',True):
            reply=self.step('כפתור בשתי הדלתות',self.model('הנה ההצעה.',**dict(specs,quote_requested=True)))
        self.assertEqual(len(self.documents),1)
        self.assertEqual(len(self.documents[0]['items']),3)
        self.assertEqual(self.documents[0]['amount_ils_pre_vat'],sum(i['amount_ils_pre_vat'] for i in self.documents[0]['items']))
        self.assertFalse(yossi.contains_ils_amount(reply))


    def test_narrow_front_with_toilet_cannot_become_a_sliding_offer(self):
        specs={'product':'מקלחון','layout_geometry':'front','width_cm':120}
        self.memory[self.phone]=([{'role':'user','content':'מקלחון בין שני קירות 120'},{'role':'assistant','content':'יש אסלה קרובה?'}],
            dict(specs,sales_discovery_completed=True,quote_requested=True,active_sales_item='2',expected_sales_item_count=3,sales_items={'1':{},'2':dict(specs),'3':{}}))
        reply=self.step('כן יש אסלה קרובה',self.model('ממליץ על קבוע ודלת הזזה. נתקדם?',configuration='הזזה קבוע + דלת',quote_requested=True))
        self.assertIn('רק מ־140',reply)
        self.assertIn('צילום',reply)
        self.assertNotIn('ממליץ על קבוע',reply)
        self.assertNotIn('configuration',self.memory[self.phone][1]['sales_items']['2'])
        self.assertFalse(self.documents)


    def test_unavailable_photo_switches_to_verbal_question_and_persists_per_item(self):
        specs={'product':'מקלחון','layout_geometry':'front','width_cm':120,'obstacle_type':'אסלה'}
        self.memory[self.phone]=([{'role':'user','content':'בין שני קירות 120'},{'role':'assistant','content':'אפשר לשלוח צילום של הפתח והאסלה?'}],
            dict(specs,sales_discovery_completed=True,quote_requested=True,active_sales_item='2',expected_sales_item_count=3,sales_items={'1':{},'2':dict(specs),'3':{}}))
        reply=self.step('אין לי תמונה כרגע',self.model('ב־120 לא מתאים הזזה, אפשר לשלוח צילום?',quote_requested=True))
        self.assertIn('מימין או משמאל',reply)
        self.assertNotIn('לשלוח צילום',reply)
        saved=self.memory[self.phone][1]
        self.assertTrue(saved['sales_items']['2']['customer_photo_unavailable'])
        reply=self.step('משמאל',self.model('אפשר לשלוח צילום של האסלה?',quote_requested=True))
        self.assertIn('כמה מרווח',reply)
        self.assertNotIn('מימין או משמאל',reply)
        reply=self.step('בערך 20 ס״מ',self.model('אפשר לשלוח צילום?',quote_requested=True,width_cm=20))
        self.assertIn('עומק',reply)
        self.assertEqual(self.memory[self.phone][1]['sales_items']['2']['width_cm'],120)
        self.assertEqual(self.memory[self.phone][1]['sales_items']['2']['obstacle_clearance_cm'],20)
        reply=self.step('80 בערך',self.model('אפשר לשלוח צילום?',quote_requested=True,width_cm=80))
        self.assertIn('בדיקת התאמה',reply)
        saved=self.memory[self.phone][1]
        self.assertEqual(saved['sales_items']['2']['width_cm'],120)
        self.assertEqual(saved['sales_items']['2']['shower_depth_cm'],80)
        self.assertFalse(self.documents)
        from sales_items import item_context
        switched=item_context(saved,self.memory[self.phone][0]+[{'role':'user','content':'למקלחון השלישי'}],'למקלחון השלישי')
        self.assertNotIn('customer_photo_unavailable',switched)


    def test_completed_single_sends_document_despite_model_asking_about_extra_shower(self):
        specs={'product':'מקלחון','configuration':'חזית קבוע + דלת','width_cm':150,'height_cm':200,
               'glass_type':'שקופה','finish':'שחור','solution_agreed':True}
        self.memory[self.phone]=([{'role':'user','content':'כמה עולה מקלחון'},{'role':'assistant','content':'איזה ידית תרצה?'}],
            dict(specs,sales_discovery_completed=True,quote_requested=True))
        with patch.object(yossi,'PDF_QUOTES_ENABLED',True):
            reply=self.step('כפתור',self.model('סיכמנו חזית קבועה ודלת עם כפתור. יש מקלחון נוסף שצריך לתמחר?',
                **dict(specs,handles=['ידית כפתור'],quote_requested=True)))
        self.assertEqual(len(self.documents),1)
        self.assertEqual(len(self.documents[0]['items']),1)
        self.assertIn('מצורפת הצעת המחיר',reply)
        self.assertNotIn('אפשר לחשב',reply)
        self.assertFalse(yossi.contains_ils_amount(reply))


class LayoutAdviceRules(unittest.TestCase):
    def test_known_configuration_and_unrelated_requests_are_not_overridden(self):
        self.assertIsNone(layout_consultation_reply('מה אתה ממליץ',{'configuration':'פינתי 2 דלתות'}))
        self.assertIsNone(layout_consultation_reply('יקר לי',{}))
    def test_missing_configuration_question_is_plain_language(self):
        self.assertIn('בין שני קירות',yossi.missing_quote_detail({}))
    def test_bath_advice_does_not_assume_corner_shower(self):
        self.assertIn('אמבטיה',layout_consultation_reply('לא יודע',{'product':'אמבטיון'}))

class GeometryRules(unittest.TestCase):
    def test_unknown_width_guard_preserves_explanation_and_known_widths(self):
        from sales_items import slider_reply
        explanation='בהזזה הדלת נעה הצידה במקום להיפתח קדימה.'
        self.assertEqual(slider_reply(explanation,{'product':'מקלחון'}),explanation)
        advice='אפשר לבחון הזזה, אבל צריך לבדוק את החלוקה בשטח.'
        for width in (140,150):
            self.assertEqual(slider_reply(advice,{'product':'מקלחון','width_cm':width}),advice)
        from sales_items import item_context
        self.assertNotIn('obstacle_side',item_context({},[{'role':'assistant','content':'איזה גוון פרזול?'},{'role':'user','content':'משמאל'}],'משמאל'))

    def test_plain_front_answers_are_geometry_not_an_approved_configuration(self):
        from layout_consultation import capture_layout_geometry
        for text in ['רק בחזית','בחזית','חזית','זכוכית רק בחזית','לא מבין בזה, יש זכוכית רק מקדימה','רק מקדימה אחי, מה לא ברור']:
            with self.subTest(text=text):
                self.assertEqual(capture_layout_geometry({},text),{'layout_geometry':'front'})

    def test_known_geometry_does_not_restart_discovery_on_other_uncertainty(self):
        for geometry in ('front','corner'):
            with self.subTest(geometry=geometry):
                self.assertIsNone(layout_consultation_reply('לא יודע כמה מקום נשאר',{'layout_geometry':geometry}))

    def test_negated_and_ambiguous_geometry_do_not_become_facts(self):
        from layout_consultation import capture_layout_geometry
        for text in ['לא בפינה','אולי בפינה','מה עדיף פינתי או חזיתי','בפינה יש ארון','לא רק מקדימה, יש גם בצד','לא רוצה רק מקדימה','אולי רק מקדימה','רק מקדימה או גם בצד?']:
            self.assertEqual(capture_layout_geometry({},text),{})

class NaturalCustomerRegressionTests(unittest.TestCase):
    setUp=sim.ConversationSimulation.setUp
    load=sim.ConversationSimulation.load
    save=sim.ConversationSimulation.save
    send=sim.ConversationSimulation.send
    reset=sim.ConversationSimulation.reset
    step=sim.ConversationSimulation.step
    model=sim.ConversationSimulation.model

    def test_away_from_home_does_not_restart_geometry_or_call_model(self):
        self.memory[self.phone]=([{'role':'assistant','content':'מה רוחב הפתח מקיר לקיר בערך?'}],
            {'product':'מקלחון','layout_geometry':'front','quote_requested':True})
        with patch.object(yossi.client.responses,'create') as ai:
            reply=self.step('אין לי מושג אני לא בבית עכשיו')
        ai.assert_not_called()
        self.assertIn('כשתהיה בדירה',reply)
        self.assertNotIn('פינה',reply)
        self.assertFalse(self.documents)
        self.assertEqual(self.memory[self.phone][1]['layout_geometry'],'front')

    def test_narrow_opening_reply_does_not_invent_toilet_and_correction_is_answered(self):
        from sliding_policy import sliding_limit_reply
        answer=sliding_limit_reply({'product':'מקלחון','width_cm':139})
        self.assertIn('140',answer)
        self.assertNotIn('אסלה',answer)
        self.memory[self.phone]=([{'role':'user','content':'יש לי פתח 139, רוצה הזזה'},
            {'role':'assistant','content':'אפשר לשלוח צילום של הפתח והאסלה?'}],
            {'product':'מקלחון','width_cm':139,'sales_discovery_completed':False})
        reply=self.step('איזה אסלה? יש שם ארון',self.model('הבנתי, ליד הפתח יש ארון. אפשר צילום של הפתח והארון כדי לבדוק מרווח לפתיחה?'))
        self.assertIn('יש ארון',reply)
        self.assertNotIn('בית חדש',reply)
        self.assertNotIn('מה שמך',reply)
        self.assertFalse(self.documents)

    def test_replacing_old_one_in_shower_context_does_not_reask_if_there_was_a_shower(self):
        for text in ('להחליף את הישן','להחליף ישן','אני מחליף את הישן'):
            with self.subTest(text=text):
                self.memory[self.phone]=([{'role':'user','content':'צריך מקלחון'},
                    {'role':'assistant','content':'זה לבית חדש, לשיפוץ או להחלפת מקלחון קיים?'},
                    {'role':'user','content':text},{'role':'assistant','content':'מה שמך?'}],
                    {'product':'מקלחון','customer_name':'רועי','sales_discovery_completed':False})
                reply=self.step('רועי',self.model('איך המקלחון הקודם היה לך בשימוש, ומה היית רוצה לשפר?'))
                self.assertIn('מה היית רוצה לשפר',reply)
                self.assertNotIn('וילון',reply)
                self.assertNotIn('היה לך מקלחון עד היום',reply)

    def test_leaving_to_check_elsewhere_stops_pending_quote_without_model(self):
        self.memory[self.phone]=([{'role':'assistant','content':'מה רוחב הפתח?'}],
            {'product':'מקלחון','quote_requested':True})
        with patch.object(yossi.client.responses,'create') as ai:
            reply=self.step('עזוב אחי אתה שואל אותי אותו דבר, אבדוק במקום אחר')
        ai.assert_not_called()
        self.assertNotIn('?',reply)
        self.assertTrue(self.memory[self.phone][1]['sales_closed'])
        self.assertFalse(self.memory[self.phone][1]['quote_requested'])
        self.assertFalse(self.documents)
        self.assertIsNone(yossi.customer_boundary('לא אבדוק במקום אחר, רוצה להמשיך איתך'))


class FixturePhotoFallbackTests(unittest.TestCase):
    def test_unavailable_photo_does_not_invent_toilet_and_cabinet_answers_bind(self):
        from sliding_policy import verbal_clearance_question,capture_spatial_answer
        self.assertNotIn('obstacle_type',capture_spatial_answer({},'יש שם ארון?',''))
        self.assertIn('ארון או אסלה',verbal_clearance_question({}))
        self.assertNotIn('האסלה נמצאת',verbal_clearance_question({}))
        state=capture_spatial_answer({},'איזה אסלה? יש שם ארון','')
        self.assertEqual(state['obstacle_type'],'ארון')
        question=verbal_clearance_question(state)
        self.assertIn('הארון',question)
        self.assertNotIn('אסלה',question)
        capture_spatial_answer(state,'משמאל',question)
        capture_spatial_answer(state,'20',verbal_clearance_question(state))
        self.assertEqual(state['obstacle_side'],'משמאל')
        self.assertEqual(state['obstacle_clearance_cm'],20)


class ObstructionRules(unittest.TestCase):
    def test_no_is_only_bound_to_the_actual_obstruction_question(self):
        from layout_consultation import capture_layout_geometry
        self.assertEqual(capture_layout_geometry({},'לא','רוצה זכוכית שקופה?'),{})
        state=capture_layout_geometry({},'כן','יש ליד המקלחת ארון או אסלה שעלולים להפריע לפתיחת הדלתות?')
        self.assertIs(state['door_obstruction'],True)

class ContextOptionsRules(unittest.TestCase):
    def test_options_bind_to_last_subject_and_slider_has_no_towel_offer(self):
        from consultation_options import contextual_options_reply
        self.assertIn('ברזים',contextual_options_reply('מה האפשרויות?','איזה גוון פרזול תרצה?',{}))
        self.assertIn('כפתור',contextual_options_reply('מה האפשרויות?','איזה סוג ידית?',{}))
        self.assertNotIn('מגבת',contextual_options_reply('מה האפשרויות?','איזה סוג ידית?',{'configuration':'הזזה קבוע + דלת'}))
        self.assertIsNone(contextual_options_reply('מה האפשרויות?','מה רוחב הפתח?',{}))

class VisualReferenceRules(unittest.TestCase):
    def test_latest_recommendation_only_and_no_automatic_acceptance(self):
        from sales_visuals import referenced_glass_sample,implicit_visual_request
        self.assertTrue(implicit_visual_request('אפשר לראות איך זה נראה?'))
        history=[{'role':'assistant','content':'ממליץ על אנטיסן ברונזה. אפור חלופה.'},{'role':'user','content':'אפשר לראות איך זה נראה?'}]
        self.assertEqual(referenced_glass_sample(history[-1]['content'],history,{}),'אנטיסן ברונזה')
        self.assertIsNone(referenced_glass_sample('לא צריך תמונות',history,{}))
        self.assertIsNone(referenced_glass_sample('אפשר לראות איך זה נראה?',[{'role':'assistant','content':'ידית כפתור או מגבת?'},{'role':'user','content':'אפשר לראות איך זה נראה?'}],{}))

class SlidingMinimumTests(unittest.TestCase):
    def test_owner_minimum_boundary_is_enforced_by_calculator(self):
        specs={'product':'מקלחון','configuration':'הזזה קבוע + דלת','glass_type':'שקופה','finish':'שחור','handles':['ידית כפתור'],'height_cm':200}
        for width in [120,139,139.9]:
            self.assertIsNone(yossi.calculate_quote(dict(specs,width_cm=width)))
        self.assertIsNotNone(yossi.calculate_quote(dict(specs,width_cm=140)))
        self.assertIsNotNone(yossi.calculate_quote(dict(specs,width_cm=150)))

class MissingPhotoRules(unittest.TestCase):
    def test_missing_photo_does_not_replace_a_useful_non_photo_followup(self):
        from sliding_policy import respect_missing_customer_photo,no_customer_photo
        state={'customer_photo_unavailable':True,'obstacle_type':'אסלה'}
        self.assertEqual(respect_missing_customer_photo('כמה מרווח בערך יש מהאסלה לפתח?',state,'משמאל'),'כמה מרווח בערך יש מהאסלה לפתח?')
        self.assertFalse(no_customer_photo('יש לי תמונה'))
        self.assertIn('מימין או משמאל',respect_missing_customer_photo('אפשר לשלוח תמונה?',state,'משמאל'))
