import unittest
from unittest.mock import patch
import tests.test_conversation_simulator as sim
import app as yossi
from sales_items import item_context, group_choices, save_item, bundle_offer, partial_offer_reply, slider_specs

LIST='2 מקלחונים 90/90 שתי דלתות\n1 מקלחון הזזה פתח 1.50\n1 אמבטיוו\nאמבטיון'


def history():
    return [{'role':'user','content':'צריך 4 מקלחונים'},
            {'role':'user','content':'ונקי זכוכית ברונזה'},
            {'role':'user','content':LIST},
            {'role':'assistant','content':'בשני המקלחונים של 90 על 90, שתי דלתות שנפגשות בפינה, בלי חלקי זכוכית קבועים?'},
            {'role':'user','content':'כן'}]


class FourItemStateTests(unittest.TestCase):
    def test_quantity_list_expands_four_independent_items_and_shared_choice_is_bounded(self):
        state=item_context({},history(),'כן')
        self.assertEqual(state['expected_sales_item_count'],4)
        self.assertEqual(state['sales_items']['4']['product'],'אמבטיון')
        self.assertEqual(state['sales_items']['3']['width_cm'],150)
        self.assertEqual(state['sales_items']['2']['width_cm'],90)
        data={'configuration':'פינתי 2 דלתות','solution_agreed':True}
        state.update(data);save_item(state);group_choices(state,history(),data)
        self.assertTrue(state['sales_items']['2']['solution_agreed'])
        self.assertNotIn('configuration',state['sales_items']['3'])
        state['sales_items']['1']['width_cm']=95
        self.assertEqual(state['sales_items']['2']['width_cm'],90)
        self.assertIsNone(bundle_offer(state,yossi.calculate_quote,allow_single=True))

    def test_legacy_product_mix_is_repaired_and_cabinet_never_becomes_bath_width(self):
        corner={'product':'מקלחון','configuration':'פינתי 2 דלתות','width_cm':90,'second_width_cm':90,
                'glass_type':'אנטיסן ברונזה','finish':'ברונזה','handles':['ידית כפתור']*2,'solution_agreed':True}
        corrupt=dict(corner,product='אמבטיון',height_cm=200,solution_agreed=False)
        prior=dict(corrupt,active_sales_item='2',expected_sales_item_count=3,
                   sales_items={'1':corner,'2':corrupt,'3':{'product':'מקלחון','configuration':'הזזה קבוע + דלת',
                   'width_cm':150,'finish':'גרפיט','glass_type':'אנטיסן ברונזה','solution_agreed':True}})
        h=history()+[{'role':'assistant','content':'נעבור לאמבטיון, צריך לסגור רק את הצד הארוך?'},
                     {'role':'user','content':'כן רק תארוך אני צריך יש בערך שם 1.30'},
                     {'role':'assistant','content':'יש ליד האמבטיה ארון או אסלה?'},
                     {'role':'user','content':'ארוך 40 סמ'},
                     {'role':'assistant','content':'40 ס״מ זה רוחב הארון או המרחק?'},
                     {'role':'user','content':'תן לי הצעה אחי לדעת כיוון, רוחב ארון'}]
        fixed=item_context(prior,h,h[-1]['content'])
        self.assertEqual(fixed['active_sales_item'],'4')
        self.assertEqual(fixed['width_cm'],130)
        self.assertNotIn('second_width_cm',fixed)
        self.assertNotIn('configuration',fixed)
        self.assertEqual(fixed['sales_items']['2']['product'],'מקלחון')
        self.assertTrue(fixed['sales_items']['2']['solution_agreed'])
        for n in ('1','2','3'):
            specs=slider_specs(fixed['sales_items'][n]);specs['height_cm']=200
            self.assertIsNotNone(yossi.calculate_quote(specs))
        self.assertEqual(yossi.preliminary_height(fixed),140)

    def test_four_complete_items_have_one_complete_offer_with_correct_defaults(self):
        corner={'product':'מקלחון','configuration':'פינתי 2 דלתות','width_cm':90,'second_width_cm':90,
                'glass_type':'אנטיסן ברונזה','finish':'ברונזה','handles':['ידית כפתור']*2,'solution_agreed':True}
        slider=dict(corner,configuration='הזזה קבוע + דלת',width_cm=150,second_width_cm=None,handles=None)
        bath=dict(corner,product='אמבטיון',configuration='חזית קבוע + דלת',width_cm=130,second_width_cm=None,handles=['ידית כפתור'])
        state={'expected_sales_item_count':4,'sales_items':{'1':corner,'2':dict(corner),'3':slider,'4':bath}}
        offer=bundle_offer(state,yossi.calculate_quote)
        self.assertEqual(len(offer['items']),4)
        self.assertEqual([i['specification']['height_cm'] for i in offer['items']],[200,200,200,140])
        self.assertEqual(offer['items'][2]['specification']['handles'],['ידית כפתור'])
        self.assertEqual(offer['amount_ils_pre_vat'],sum(i['amount_ils_pre_vat'] for i in offer['items']))


class SliderConversationTests(unittest.TestCase):
    setUp=sim.ConversationSimulation.setUp
    load=sim.ConversationSimulation.load
    save=sim.ConversationSimulation.save
    send=sim.ConversationSimulation.send
    reset=sim.ConversationSimulation.reset
    step=sim.ConversationSimulation.step
    model=sim.ConversationSimulation.model

    def test_model_towel_option_is_removed_and_slider_only_keeps_button(self):
        specs={'product':'מקלחון','configuration':'הזזה קבוע + דלת','width_cm':150,
               'glass_type':'אנטיסן ברונזה','finish':'גרפיט','solution_agreed':True,'sales_discovery_completed':True}
        self.memory[self.phone]=([{'role':'assistant','content':'סיכמנו הזזה.'}],specs)
        reply=self.step('מעולה',self.model('תרצה ידית כפתור או ידית מגבת?',handles=['ידית מגבת'],**specs))
        self.assertNotIn('מגבת',reply)
        self.assertIn('כפתור בלבד',reply)
        self.assertEqual(self.memory[self.phone][1]['handles'],['ידית כפתור'])
        self.assertIsNone(yossi.calculate_quote(dict(specs,height_cm=200,handles=['ידית מגבת'])))

    def test_next_identical_item_does_not_repeat_dimensions_or_height(self):
        corner={'product':'מקלחון','configuration':'פינתי 2 דלתות','width_cm':90,'second_width_cm':90,
                'glass_type':'אנטיסן ברונזה','finish':'ברונזה','solution_agreed':True}
        state=item_context(dict(corner,sales_discovery_completed=True),history(),'כן')
        state['sales_items']['2'].update(corner)
        self.memory[self.phone]=(history(),state)
        reply=self.step('שתי ידיות כפתור',self.model('מה המידות של המקלחון השני?',handles=['ידית כפתור']*2,**corner))
        self.assertIn('שתי ידיות כפתור',reply)
        self.assertNotIn('מידות',reply)
        self.assertNotIn('גובה',reply)
        self.assertIn('לכל הפריטים',reply)


    def test_slider_examples_only_send_button_even_when_towel_is_requested(self):
        specs={'product':'מקלחון','configuration':'הזזה קבוע + דלת','width_cm':150,
               'glass_type':'אנטיסן ברונזה','finish':'גרפיט','solution_agreed':True,'sales_discovery_completed':True}
        self.memory[self.phone]=([{'role':'assistant','content':'סיכמנו הזזה.'}],specs)
        catalog=[{'url':'https://example.test/button','handle':'כפתור','glass':'שקופה'},
                 {'url':'https://example.test/towel','handle':'מגבת','glass':'שקופה'}]
        with patch.object(yossi,'PHOTO_CATALOG',catalog),patch.object(yossi,'send_whatsapp',side_effect=self.send) as send:
            reply=self.step('תשלח דוגמאות של ידית מגבת',self.model('מצרף דוגמה לידית מגבת.',
                            handles=['ידית מגבת'],send_handle_images=True,**specs))
        urls=[call.kwargs['image_url'] for call in send.call_args_list if call.kwargs.get('image_url')]
        self.assertEqual(urls,['https://example.test/button'])
        self.assertIn('כפתור בלבד',reply)
