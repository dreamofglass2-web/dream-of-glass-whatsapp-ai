import unittest
from unittest.mock import patch
from kitchen_cladding import kitchen_state, kitchen_offer
import tests.test_conversation_simulator as sim
import app as yossi
from handoff_state import new_state


class KitchenCalculatorTests(unittest.TestCase):
    def history(self):
        return [{'role':'user','content':'אני צריך חיפוי מטבח בצבע לבן'},
                {'role':'assistant','content':'מה האורך והגובה?'},
                {'role':'user','content':'4 מטר רץ'},
                {'role':'assistant','content':'מה הגובה המשוער של החיפוי?'},
                {'role':'user','content':'65'},
                {'role':'user','content':'3 שקעים'},
                {'role':'assistant','content':'ממליץ על לבן חם. נתקדם להצעה?'},
                {'role':'user','content':'כן'}]

    def test_actual_written_dimensions_price_color_and_print_independently(self):
        state=kitchen_state({'product':'חיפוי מטבח'},self.history())
        offer=kitchen_offer(state)
        s=offer['items'][0]['specification']
        self.assertEqual((s['area_m2'],s['rate_ils_per_m2'],s['socket_count']),(2.6,1100,3))
        self.assertEqual(s['cladding_color'],'לבן חם')
        self.assertEqual(offer['amount_ils_pre_vat'],2860)
        printed=kitchen_offer(dict(state,cladding_type='הדפסה'))
        self.assertEqual(printed['amount_ils_pre_vat'],3900)
        self.assertNotEqual(printed['fingerprint'],offer['fingerprint'])
        switched=kitchen_state(state,self.history()+[{'role':'user','content':'כמה יעלה עם הדפס?'}])
        self.assertEqual(kitchen_offer(switched)['amount_ils_pre_vat'],3900)

    def test_no_height_default_and_no_shower_or_image_measurements(self):
        h=[{'role':'user','content':'חיפוי לבן [לקוח צירף תמונה שנותח בפועל. אורך 400 גובה 65]'}]
        state=kitchen_state({'product':'מקלחון','width_cm':200,'height_cm':200},h)
        self.assertIsNone(kitchen_offer(state))
        self.assertNotIn('height_cm',state)
        self.assertIsNone(kitchen_state({'product':'חיפוי מטבח','width_cm':400,'height_cm':65},
                                       [{'role':'user','content':'בעצם אני רוצה מראה כמה עולה?'}]))

    def test_exact_area_is_authorized_without_minimum_or_double_vat(self):
        offer=kitchen_offer({'cladding_type':'צבע','cladding_area_m2':0.5})
        self.assertEqual(offer['amount_ils_pre_vat'],550)
        for invalid in (0,-1,float('nan'),float('inf')):
            self.assertIsNone(kitchen_offer({'cladding_type':'צבע','cladding_area_m2':invalid}))
        self.assertIsNone(kitchen_offer({'width_cm':400,'height_cm':65}))


class KitchenDeliveryTests(unittest.TestCase):
    setUp=sim.ConversationSimulation.setUp
    load=sim.ConversationSimulation.load
    save=sim.ConversationSimulation.save
    send=sim.ConversationSimulation.send
    reset=sim.ConversationSimulation.reset
    step=sim.ConversationSimulation.step
    model=sim.ConversationSimulation.model

    def test_customer_waiting_gets_verified_pdf_not_a_promise_or_chat_price(self):
        h=KitchenCalculatorTests().history()
        self.memory[self.phone]=(h,{'product':'חיפוי מטבח','width_cm':400,'height_cm':65})
        with patch.object(yossi.client.responses,'create') as model:
            reply=self.step('תודה מחכה להצעה')
        model.assert_not_called()
        self.assertEqual(self.documents[-1]['amount_ils_pre_vat'],2860)
        self.assertIn('חיפוי המטבח',reply)
        self.assertFalse(yossi.contains_ils_amount(reply))
        state=self.memory[self.phone][1]
        self.assertTrue(state['kitchen_offer']['issued'])
        self.assertTrue(state['quote_document'])

    def test_missing_height_is_one_question_not_an_invented_standard_height(self):
        self.memory[self.phone]=([{'role':'user','content':'חיפוי מטבח בצבע לבן 4 מטר רץ'}],{'product':'חיפוי מטבח'})
        with patch.object(yossi.client.responses,'create') as model:
            reply=self.step('אפשר הצעת מחיר?')
        model.assert_not_called()
        self.assertIn('גובה',reply)
        self.assertEqual(self.documents,[])

    def test_pdf_failure_creates_owner_request_instead_of_waiting_claim(self):
        self.memory[self.phone]=(KitchenCalculatorTests().history(),{'product':'חיפוי מטבח'})
        with patch.object(yossi,'HANDOFF_ENABLED',True),patch.object(yossi,'ensure_db'), \
             patch.object(yossi,'db_connection') as db,patch.object(yossi,'read_handoff_state',return_value=new_state()), \
             patch.object(yossi,'phone_lock'),patch.object(yossi,'deliver_order_offer',side_effect=ValueError('PDF failed')), \
             patch.object(yossi,'pause_for_owner',return_value=True) as pause:
            self.assertTrue(yossi.process_message(self.phone,'תכין הצעת מחיר'))
        pause.assert_called_once()
        self.assertIn('חיפוי',pause.call_args.args[2])
        self.assertEqual(self.sent,[])
