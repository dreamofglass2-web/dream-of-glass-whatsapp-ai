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
