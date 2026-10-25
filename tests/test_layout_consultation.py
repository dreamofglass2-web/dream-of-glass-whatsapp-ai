import unittest
from unittest.mock import patch, MagicMock
from handoff_state import new_state
import tests.test_conversation_simulator as sim
import app as yossi
from layout_consultation import layout_consultation_reply

class LayoutAdviceJourney(sim.ConversationSimulation):
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


class LayoutAdviceRules(unittest.TestCase):
    def test_known_configuration_and_unrelated_requests_are_not_overridden(self):
        self.assertIsNone(layout_consultation_reply('מה אתה ממליץ',{'configuration':'פינתי 2 דלתות'}))
        self.assertIsNone(layout_consultation_reply('יקר לי',{}))
    def test_missing_configuration_question_is_plain_language(self):
        self.assertIn('בין שני קירות',yossi.missing_quote_detail({}))
    def test_bath_advice_does_not_assume_corner_shower(self):
        self.assertIn('אמבטיה',layout_consultation_reply('לא יודע',{'product':'אמבטיון'}))

class GeometryRules(unittest.TestCase):
    def test_negated_and_ambiguous_geometry_do_not_become_facts(self):
        from layout_consultation import capture_layout_geometry
        for text in ['לא בפינה','אולי בפינה','מה עדיף פינתי או חזיתי','בפינה יש ארון']:
            self.assertEqual(capture_layout_geometry({},text),{})

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
