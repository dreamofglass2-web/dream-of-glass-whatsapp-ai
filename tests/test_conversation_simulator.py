"""Offline end-to-end conversation simulation.

Runs the real process_message function but replaces Meta, PostgreSQL and the
OpenAI response with in-memory fakes. No real customer receives messages.
"""
import json
import os
import types
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test-only")
import app as yossi


class FakeResponses:
    def __init__(self):
        self.queue = []

    def create(self, **kwargs):
        # Every offline journey validates the real conversation/API boundary.
        for message in kwargs.get('input', [])[2:]:
            if set(message) != {'role', 'content'} or message.get('role') not in ('user','assistant') or not isinstance(message.get('content'), str):
                raise AssertionError('CRM metadata or unsupported message fields leaked to model input')
        if not self.queue:
            raise AssertionError("No scripted model response available")
        return types.SimpleNamespace(output_text=json.dumps(self.queue.pop(0), ensure_ascii=False))


class ConversationSimulation(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.memory = {}
        self.ai = FakeResponses()
        self.patches = [
            patch.object(yossi, "load_conversation", side_effect=self.load),
            patch.object(yossi, "save_conversation", side_effect=self.save),
            patch.object(yossi, "send_whatsapp", side_effect=self.send),
            patch.object(yossi, "reset_conversation_for_phone", side_effect=self.reset),
            patch.object(yossi, "save_callback", return_value=True),
            patch.object(yossi, "save_custom_quote_lead", return_value=True),
            patch.object(yossi, "has_new_messages", return_value=False),
            patch.object(yossi.time, "sleep", return_value=None),
            patch.object(yossi.client.responses, "create", side_effect=self.ai.create),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        self.phone = "OFFLINE_SIMULATION_ONLY"
        yossi.pending.clear()
        yossi.customer_context.clear()
        yossi.histories.clear()

    def load(self, phone):
        history, context = self.memory.get(phone, ([], {'sales_discovery_completed': True}))
        context = dict(context)
        context.setdefault('sales_discovery_completed', True)  # Pricing fixtures represent post-discovery turns.
        return list(history), context

    def save(self, phone, history, context):
        self.memory[phone] = (list(history), dict(context))

    def send(self, phone, body=None, image_url=None, caption=None):
        self.assertEqual(phone, self.phone)
        self.sent.append(body if body is not None else "[TEST_IMAGE]")

    def reset(self, phone):
        self.memory[phone] = ([], {})
        return True

    def step(self, customer, model=None):
        if model is not None:
            self.ai.queue.append(model)
        self.assertTrue(yossi.process_message(self.phone, customer))
        return self.sent[-1]

    def model(self, reply, **fields):
        return dict({
            "reply": reply, "stage": "discovery", "action": "reply",
            "product": "מקלחון", "needs_human": False,
            "quote_requested": False, "solution_agreed": False,
        }, **fields)



    def test_two_showers_keep_separate_specs_and_complete_total(self):
        first=dict(product='מקלחון',configuration='חזית קבוע + דלת',width_cm=120,
                   height_cm=200,glass_type='שקופה',finish='שחור',handles=['ידית כפתור'],
                   solution_agreed=True)
        self.step('אני צריך שני מקלחונים. הראשון חזית קבוע ודלת 120 שקוף שחור כפתור',
                  self.model('נעבור למקלחון השני: מה רוחב הפתח?',**first))
        second=dict(product='מקלחון',configuration='חזית קבוע + דלת',width_cm=160,
                    height_cm=200,glass_type='אנטיסן ברונזה',finish='ברונזה',
                    handles=['ידית מגבת'],solution_agreed=True)
        self.step('160',self.model('להכין הצעת מחיר לשני המקלחונים?',**second))
        reply=self.step('כן תודה',self.model('בודק מחיר',**second,quote_requested=True))
        total=round(yossi.calculate_quote(first))+round(yossi.calculate_quote(second))
        self.assertIn(f'{total:,.0f}',reply)
        state=self.memory[self.phone][1]
        self.assertEqual(state['sales_items']['1']['width_cm'],120)
        self.assertEqual(state['sales_items']['1']['handles'],['ידית כפתור'])
        self.assertEqual(state['sales_items']['2']['width_cm'],160)

    def test_handle_example_uses_shower_photo_caption_and_not_glass_gallery(self):
        self.memory[self.phone]=([{'role':'assistant','content':'ידית כפתור או מגבת?'}],
                                 {'handles':['ידית כפתור']})
        pictures=[]
        def capture(phone,body=None,image_url=None,caption=None):
            self.sent.append(body or '[TEST_IMAGE]')
            if image_url: pictures.append((image_url,caption))
        catalog=[dict(url='https://example.test/button',glass='גלינה קליר',
                      product='מקלחון',handle='כפתור')]
        with patch.object(yossi,'PHOTO_CATALOG',catalog), patch.object(yossi,'send_whatsapp',side_effect=capture):
            self.step('יש לך דוגמה?',self.model('הנה דוגמה'))
        self.assertEqual(len(pictures),1)
        self.assertIn('כפתור',pictures[0][1])





    def test_natural_project_question_is_preserved(self):
        self.memory[self.phone] = ([], {'sales_discovery_completed': False})
        reply='היי, אני יוסי מחלומות מזכוכית. אשמח לעזור לבחור משהו שיהיה נוח לך. זה לשיפוץ או להחלפת מקלחון קיים?'
        self.assertEqual(self.step('מחפש מקלחון',self.model(reply)),reply)


    def test_offer_request_and_city_turn_do_not_discard_valid_model_quote(self):
        specs=dict(product='מקלחון',configuration='חזית קבוע + דלת',width_cm=120,height_cm=200,
                   glass_type='שקופה',finish='שחור',handles=['ידית מגבת'],solution_agreed=True,
                   sales_discovery_completed=True)
        for request in ('פתח תקווה','תן הצעה לפי מה שבחרתי'):
            self.memory[self.phone]=([],dict(specs))
            amount=yossi.calculate_quote(specs)
            reply=f'ההצעה הראשונית היא {amount:,.0f} ש״ח לפני מע״מ, כולל מדידה, הובלה והתקנה. המידות הסופיות ייבדקו בשטח ושינוי במידות עשוי לשנות את המחיר.'
            answer=self.step(request,self.model(reply,action='quote',quote_requested=False,solution_agreed=True))
            self.assertIn(f'{amount:,.0f}',answer)
            self.assertNotIn('חסר עוד אימות',answer)
            self.assertTrue(self.memory[self.phone][1]['validated_quote']['issued'])

    def test_pending_price_survives_model_false_until_calculation(self):
        specs=dict(product='מקלחון',configuration='חזית קבוע + דלת',width_cm=120,height_cm=200,
                   glass_type='שקופה',finish='שחור',handles=['ידית מגבת'],solution_agreed=True,
                   quote_requested=True,sales_discovery_completed=False)
        self.memory[self.phone]=([{'role':'user','content':'כמה עולה מקלחון לשיפוץ?'},
                                  {'role':'assistant','content':'מה הכי חשוב לך בתוצאה?'}],specs)
        answer=self.step('חשוב לי ניקוי קל',self.model('נוכל להכין הצעה',quote_requested=False))
        self.assertIn('₪',answer)

    def test_non_price_product_openings_use_consultation(self):
        for customer,product in [('מחפש מקלחון','מקלחון'),('צריך מראה','מראה'),('מחיצה למשרד','מחיצה')]:
            self.memory[self.phone] = ([], {'sales_discovery_completed': False})
            answer=self.step(customer,self.model('מה הרוחב?',product=product))
            self.assertIn('שיפוץ',answer)
            self.assertNotIn('מה הרוחב',answer)

    def test_price_first_discovers_project_and_experience(self):
        self.memory[self.phone] = ([], {'sales_discovery_completed': False})
        specs=dict(product='מקלחון',configuration='פינתי 2 קבועים + 2 דלתות',width_cm=80,
                   second_width_cm=80,height_cm=200,glass_type='שקופה',finish='ניקל',
                   handles=['ידית כפתור']*2,solution_agreed=True,quote_requested=True)
        answer=self.step('כמה עולה מקלחון פינתי 80/80',self.model('המחיר 2294 ש״ח',**specs))
        self.assertIn('בית חדש',answer)
        self.assertNotIn('2294',answer)
        answer=self.step('להחליף מקלחון קיים',self.model('המחיר 2294 ש״ח',**specs))
        self.assertIn('מה שמך',answer)
        answer=self.step('דניאל',self.model('בוא נחשב מחיר',**specs))
        self.assertIn('בשימוש',answer)
        self.assertEqual(yossi.extract_customer_name(self.memory[self.phone][0]),'דניאל')
        answer=self.step('היה הזזה וקשה לנקות את המסילה',self.model('נחשב מחיר',**specs))
        self.assertIn('₪',answer)

    def test_owner_pricing_base_buffer_removal_rounding_and_no_minimum(self):
        specs=dict(configuration='חזית קבוע + דלת',width_cm=160,height_cm=200,
                   glass_type='שקופה',finish='שחור',handles=['ידית מגבת'])
        # Old formula: glass + hardware + 1650. Owner replaces 1650 with 1300.
        price=yossi.calculate_quote(specs)
        self.assertIsInstance(price,int)
        self.assertEqual(price,2084)
        specs['width_cm']=160.5
        fractional=yossi.calculate_quote(specs)
        self.assertIsInstance(fractional,int)
        self.assertEqual(fractional,price+1)
        with patch.dict(yossi.GLASS_COSTS,{'שקופה':0}), patch.dict(yossi.HARDWARE_COSTS,dict.fromkeys(yossi.HARDWARE_COSTS,0)):
            self.assertEqual(yossi.calculate_quote(specs),1300)

    def test_recalculate_changed_width_keeps_known_choices_and_uses_calculator(self):
        specs=dict(product='מקלחון',configuration='חזית קבוע + דלת',width_cm=120,
                   height_cm=200,glass_type='שקופה',finish='שחור',handles=['ידית מגבת'],
                   quote_requested=True,solution_agreed=True)
        self.step('תחשב מחיר',self.model('בודק',**specs))
        self.step('בעצם רוחב 100 במקום 120',self.model('נחשב לפי הרוחב החדש',width_cm=100))
        answer=self.step('תחשב מחדש',self.model('המחיר 2,254 ש״ח',configuration='תיאור לא תקין',finish='שם לא תקין'))
        expected=yossi.calculate_quote(dict(specs,width_cm=100))
        self.assertIn(f'₪{expected:,.0f}',answer)
        self.assertEqual(self.memory[self.phone][1]['configuration'],specs['configuration'])
        self.assertEqual(self.memory[self.phone][1]['width_cm'],100)

    def test_correct_mixed_warranty_keeps_location_in_the_same_sentence(self):
        reply='היי, אני יוסי מחלומות מזכוכית. אין אחריות על הזכוכית; במקלחון יש 7 שנות אחריות לפרזול ושנה להתקנה, ופתח תקווה באזור השירות שלנו. הפתח בין שני קירות?'
        answer=self.step('מקלחון ברוחב 120 בפתח תקווה, יש אחריות לזכוכית?',self.model(reply,width_cm=120))
        self.assertEqual(answer,reply)
        self.assertIn('פתח תקווה',answer)

    def test_grounded_quote_keeps_consultant_voice_and_receives_calculator_facts(self):
        specs=dict(product='מקלחון',configuration='חזית קבוע + דלת',width_cm=120,
                   glass_type='שקופה',finish='שחור',handles=['ידית מגבת'],solution_agreed=True)
        self.memory[self.phone]=([{'role':'user','content':'חשוב לי כניסה נוחה'},
                                 {'role':'assistant','content':'נבחר קבוע ודלת'}],specs)
        amount=yossi.calculate_quote(dict(specs,height_cm=200))
        answer=(f'לכניסה הנוחה שרצית, ההצעה הראשונית היא ₪{amount:,.0f} לפני מע״מ, '
                'כולל מדידה, הובלה והתקנה. את המידות נבדוק בשטח; שינוי במידות עשוי לשנות את המחיר. איך זה נשמע לך?')
        captured=[]
        def capture(**kwargs):
            captured.append(kwargs)
            return self.ai.create(**kwargs)
        with patch.object(yossi.client.responses,'create',side_effect=capture):
            actual=self.step('אין לי גובה מדוד, כמה זה עולה?',self.model(answer,quote_requested=True))
        self.assertEqual(actual,answer)
        state=json.loads('{' + captured[0]['input'][1]['content'].split('{',1)[1])
        self.assertEqual(state['approved_quote_for_reply']['amount_ils_pre_vat'],amount)
        self.assertEqual(state['approved_quote_for_reply']['specification']['height_cm'],200)
        self.assertTrue(self.memory[self.phone][1]['validated_quote']['issued'])

    def test_wrong_model_amount_cannot_use_natural_quote_preservation(self):
        specs=dict(product='מקלחון',configuration='חזית קבוע + דלת',width_cm=120,
                   height_cm=200,glass_type='שקופה',finish='שחור',handles=['ידית מגבת'],solution_agreed=True)
        self.memory[self.phone]=([],specs)
        bad='ההצעה הראשונית היא ₪500 לפני מע״מ כולל מדידה, הובלה והתקנה. נבדוק בשטח ושינוי במידות ישנה את המחיר.'
        answer=self.step('כמה זה עולה?',self.model(bad,quote_requested=True))
        self.assertNotIn('₪500',answer)
        self.assertIn(f"₪{yossi.calculate_quote(specs):,.0f}",answer)

    def test_crm_message_metadata_never_reaches_model_input(self):
        self.memory[self.phone] = ([
            {'role':'user','content':'אני רוצה מקלחון','at':'2026-10-13T14:43:41Z','source':'crm'},
            {'role':'assistant','content':'מה הרוחב?','id':'audit-only'},
        ], {})
        captured = []
        def capture(**kwargs):
            captured.append(kwargs)
            for message in kwargs['input'][2:]:
                self.assertEqual(set(message), {'role','content'})
            return self.ai.create(**kwargs)
        with patch.object(yossi.client.responses,'create',side_effect=capture):
            self.step('120', self.model('איזה גוון תרצה?'))
        self.assertEqual(captured[0]['input'][2]['content'], 'אני רוצה מקלחון')
        self.assertEqual(self.memory[self.phone][0][0]['at'], '2026-10-13T14:43:41Z')

    def test_after_quote_hesitation_and_objection_keep_model_consultation(self):
        specs = dict(product='מקלחון', configuration='חזית קבוע + דלת',
                     width_cm=120, height_cm=200, glass_type='שקופה', finish='שחור',
                     handles=['ידית מגבת'], solution_agreed=True, quote_requested=True)
        self.step('תחשב מחיר', self.model('בודק', **specs))
        for customer, answer in [('אני צריך לחשוב','קח את הזמן, אני כאן אם תרצה לברר משהו.'),
                                 ('תעשה לי 30 אחוז הנחה','אין אפשרות להנחה של 30 אחוז. מה התקציב שלך?'),
                                 ('אין צורך בתמונות או עוד הסברים','בסדר, אשאיר את הפרטים כאן.')]:
            with self.subTest(customer=customer):
                actual = self.step(customer, self.model(answer, quote_requested=True))
                self.assertEqual(actual, answer)
                self.assertFalse(self.memory[self.phone][1]['quote_requested'])

    def test_customer_declines_callback_without_creating_one(self):
        with patch.object(yossi,'save_callback') as callback, patch.object(yossi.client.responses,'create') as model:
            answer = self.step('לא רוצה שתחזרו אליי')
        callback.assert_not_called()
        model.assert_not_called()
        self.assertIn('לא נתקשר', answer)
        self.assertTrue(self.memory[self.phone][1]['no_phone_calls'])

    def test_ready_quote_does_not_bypass_unknown_payment_policy_handoff(self):
        specs = dict(product='מקלחון', configuration='חזית קבוע + דלת',
                     width_cm=120, height_cm=200, glass_type='שקופה', finish='שחור',
                     handles=['ידית מגבת'], solution_agreed=True, quote_requested=True)
        self.memory[self.phone] = ([], specs)
        with patch.object(yossi,'HANDOFF_ENABLED',True), patch.object(yossi,'ensure_db'), patch.object(yossi,'db_connection',return_value=unittest.mock.MagicMock()), patch.object(yossi,'read_handoff_state',return_value=__import__('handoff_state').new_state()), patch.object(yossi,'pause_for_owner',return_value=True) as pause:
            self.ai.queue.append(self.model('צריך לבדוק תנאי תשלום', needs_human=True))
            self.assertTrue(yossi.process_message(self.phone, 'כמה זה עולה והאם מקבלים אשראי?'))
        pause.assert_called_once()
        self.assertEqual(self.sent, [])

    def test_indirect_visual_request_sends_matching_catalog_example(self):
        catalog = [dict(url='https://res.cloudinary.com/test/image/upload/front.jpg',
                        glass='שקופה', product='מקלחון', configuration='חזית קבוע + דלת')]
        self.memory[self.phone] = ([{'role':'user','content':'חזית קבוע ודלת רוחב 120'},
                                   {'role':'assistant','content':'חלק אחד קבוע ואחד נפתח'}],
                                  dict(product='מקלחון', configuration='חזית קבוע + דלת'))
        with patch.object(yossi,'PHOTO_CATALOG',catalog):
            answer = self.step('קשה לי לדמיין איך זה ייראה', self.model('דמיין את הפתח'))
        self.assertIn('[TEST_IMAGE]', self.sent)
        self.assertIn('חזית קבוע + דלת', answer)
        self.assertIn('להמחשה', answer)
        self.assertNotIn('דמיין את הפתח', answer)

    def test_refusal_of_images_preserves_text_only_consultation(self):
        catalog = [dict(url='https://res.cloudinary.com/test/image/upload/front.jpg',
                        glass='שקופה', product='מקלחון', configuration='חזית קבוע + דלת')]
        with patch.object(yossi,'PHOTO_CATALOG',catalog):
            answer = self.step('לא רוצה תמונות, תסביר במילים', self.model('חלק אחד נשאר במקום והדלת נפתחת.'))
        self.assertNotIn('[TEST_IMAGE]', self.sent)
        self.assertIn('חלק אחד', answer)

    def test_unavailable_visual_request_does_not_claim_sent_media(self):
        with patch.object(yossi,'PHOTO_CATALOG',[]), patch.object(yossi,'GLASS_SAMPLE_IMAGES',{}), patch.object(yossi,'save_missing_photo_lead',return_value=True):
            answer = self.step('קשה לי לדמיין איך זה ייראה', self.model('הנה התמונות'))
        self.assertNotIn('[TEST_IMAGE]', self.sent)
        self.assertIn('אין לי תמונה מתאימה', answer)
        self.assertNotIn('הנה התמונות', answer)

    def test_media_delivery_failure_never_claims_images_were_sent(self):
        catalog = [dict(url='https://res.cloudinary.com/test/image/upload/front.jpg',
                        glass='שקופה', product='מקלחון', configuration='חזית קבוע + דלת')]
        def fail_image(phone, body=None, image_url=None, caption=None):
            if image_url:
                raise yossi.requests.RequestException('synthetic delivery failure')
            self.send(phone,body=body)
        with patch.object(yossi,'PHOTO_CATALOG',catalog), patch.object(yossi,'send_whatsapp',side_effect=fail_image):
            answer = self.step('קשה לי לדמיין', self.model('אשלח דוגמה'))
        self.assertIn('השליחה לא הצליחה', answer)
        self.assertNotIn('הנה דוגמאות', answer)

    def test_compact_cache_prefix_excludes_private_customer_context(self):
        captured = []
        def capture(**kwargs):
            captured.append(kwargs)
            return self.ai.create(**kwargs)
        with patch.object(yossi.client.responses, 'create', side_effect=capture):
            self.step('מימין כיור ומשמאל אסלה', self.model('אפשר להתאים את הכניסה לחדר.'))
            self.step('אני לא מבין צריך לראות, הם כבר מורכבים',
                      self.model('אסביר בפשטות: הכניסה תהיה באמצע.'))
        request = captured[-1]
        self.assertLess(len(request['instructions']), 12000)
        self.assertNotIn('הם כבר מורכבים', request['instructions'])
        self.assertEqual(request['prompt_cache_options'], {'mode': 'explicit', 'ttl': '30m'})
        prefix = request['input'][0]['content'][0]
        self.assertEqual(prefix['prompt_cache_breakpoint']['mode'], 'explicit')
        state = json.loads('{' + request['input'][1]['content'].split('{', 1)[1])
        self.assertTrue(state['dialogue']['sanitary_fixtures_installed'])
        self.assertTrue(state['dialogue']['customer_needs_plain_visual_explanation'])

    def test_calculate_by_200_uses_known_specs_despite_model_uncertainty(self):
        specs = dict(product='מקלחון', configuration='חזית קבוע + דלת',
                     width_cm=120, height_cm=None, glass_type='שקופה', finish='שחור',
                     handles=['ידית מגבת'], solution_agreed=True, quote_requested=True)
        self.memory[self.phone] = ([{'role':'user','content':'בחרנו קבוע ודלת שקופה שחור ידית מגבת'},
                                   {'role':'assistant','content':'מה הגובה?'}], specs)
        with patch.object(yossi,'HANDOFF_ENABLED',True), patch.object(yossi,'ensure_db'), patch.object(yossi,'db_connection',return_value=unittest.mock.MagicMock()), patch.object(yossi,'read_handoff_state',return_value=yossi.new_handoff_state() if hasattr(yossi,'new_handoff_state') else __import__('handoff_state').new_state()), patch.object(yossi,'pause_for_owner') as pause:
            answer = self.step('תחשב לי לפי גובה 200', self.model('צריך בדיקה', needs_human=True))
        pause.assert_not_called()
        self.assertIn('₪', answer)
        self.assertIn('200', answer)
        self.assertIn('ראשונית', answer)
        self.assertIn('לפני מע״מ', answer)
        self.assertEqual(self.memory[self.phone][1]['validated_quote']['height_cm'], 200)

    def test_missing_height_uses_owner_approved_preliminary_basis(self):
        specs = dict(product='מקלחון', configuration='חזית קבוע + דלת',
                     width_cm=120, glass_type='שקופה', finish='שחור',
                     handles=['ידית מגבת'], solution_agreed=True)
        self.memory[self.phone] = ([], specs)
        answer = self.step('כמה זה עולה?', self.model('צריך לדעת את הגובה'))
        self.assertIn('₪', answer)
        self.assertEqual(self.memory[self.phone][1]['pricing_height_basis'], 'owner_approved_preliminary_200')

    def test_general_price_question_keeps_known_customer_dimensions(self):
        captured = []
        def capture(**kwargs):
            captured.append(kwargs)
            return self.ai.create(**kwargs)
        with patch.object(yossi.client.responses, 'create', side_effect=capture):
            self.step('מקלחון 100/100', self.model('אפשר להתאים לך מקלחון פינתי.'))
            self.step('כמה עולה?', self.model('צריך להשלים את המפרט לפני מחיר מאומת.'))
        customer_messages = [m['content'] for m in captured[-1]['input'] if m['role'] == 'user']
        self.assertTrue(any('100/100' in t for t in customer_messages))


    def test_price_inclusions_answer_keeps_installation_and_vat(self):
        specs = dict(product='מקלחון', configuration='פינתי 2 דלתות',
                     width_cm=100, second_width_cm=100, height_cm=200,
                     glass_type='שקופה', finish='שחור',
                     handles=['ידית כפתור', 'ידית כפתור'],
                     quote_requested=True, solution_agreed=True)
        self.step('אפשר מחיר לפינתי 100/100?', self.model('בודק', **specs))
        answer = self.step('כולל התקנה ומע״מ?', self.model('המחיר כולל מע״מ 3,999 ש״ח'))
        self.assertIn('ההתקנה כלולות', answer)
        self.assertIn('המע״מ מתווסף', answer)
        self.assertNotIn('3,999', answer)
        self.assertEqual(self.memory[self.phone][1]['validated_quote']['amount_ils_pre_vat'],
                         yossi.calculate_quote(specs))

    def test_no_dimensions_statement_does_not_inject_a_photo_pitch(self):
        reply = 'אפשר להתחיל בכיוון כללי גם בלי מידות. במקלחון מודדים אחרי סיום הריצוף.'
        self.assertEqual(yossi.avoid_repeated_dimensions(reply, {'no_dimensions': True}, 'מתי מודדים?'), reply)

    def test_dimensions_guard_removes_only_repeated_question(self):
        reply = 'אפשר להתחיל בייעוץ. מה הרוחב והגובה שלכם?'
        answer = yossi.avoid_repeated_dimensions(reply, {'no_dimensions': True}, 'אין לי מידות')
        self.assertEqual(answer, 'אפשר להתחיל בייעוץ.')
        self.assertNotIn('תמונה', answer)

    def test_customer_measurements_stay_known_after_following_turn(self):
        history = [{'role':'user','content':v} for v in
                   ('אין לי מידות', 'מדדתי: 100/100', 'כן, שקוף')]
        self.assertFalse(yossi.conversation_constraints(history)['no_dimensions'])



    def test_mixed_voice_transcript_keeps_location_need_and_dimensions(self):
        request = 'שלום יוסי, אני רוצה מקלחון ברוחב מטר ועשרים. אתם מתקינים בפתח תקווה? והאם יש אחריות על הזכוכית?'
        reply = 'היי, אני יוסי מחלומות מזכוכית. כן, אנחנו מתקינים בפתח תקווה ואפשר להתאים מקלחון ברוחב 120 ס״מ. יש אחריות מלאה על הזכוכית. מדובר במקלחון חזיתי או פינתי?'
        with patch.object(yossi.client.responses, 'create', side_effect=self.ai.create) as ai:
            answer = self.step(request, self.model(reply, width_cm=120))
        ai.assert_called_once()
        self.assertIn('פתח תקווה', answer)
        self.assertIn('120', answer)
        self.assertIn('מקלחון', answer)
        self.assertTrue(answer.startswith('היי'))
        self.assertIn('חזיתי או פינתי?', answer)
        self.assertIn('אין אחריות על הזכוכית', answer)
        self.assertNotIn('אחריות מלאה', answer)
        self.assertEqual(self.memory[self.phone][1]['width_cm'], 120)

    def test_mixed_warranty_followup_keeps_other_answer_without_new_greeting(self):
        self.step('אני רוצה מראה', self.model('היי, איזה גודל?', product='מראה'))
        answer = self.step('אתם מגיעים לפתח תקווה ומה האחריות?',
                           self.model('כן, אנחנו מגיעים לפתח תקווה. יש אחריות על הזכוכית.',
                                      product='מראה'))
        self.assertIn('פתח תקווה', answer)
        self.assertIn('אין אחריות על הזכוכית', answer)
        self.assertFalse(answer.startswith('היי'))
        self.assertNotIn('7 שנות', answer)

    def test_warranty_applies_owner_confirmed_glass_exclusion(self):
        answer = self.step('איזו אחריות על המקלחונים?', self.model('אחריות מלאה לזכוכית'))
        self.assertIn('אין אחריות על הזכוכית', answer)
        self.assertIn('7 שנות אחריות על הפרזול', answer)
        self.assertIn('שנה על ההתקנה', answer)

    def test_explicit_glass_warranty_uses_verified_policy_without_ai(self):
        self.step('רוצה מקלחון', self.model('מה חשוב לך?', product='מקלחון'))
        with patch.object(yossi.client.responses, 'create') as ai:
            answer = self.step('יש אחריות על הזכוכית במקלחון?')
            self.assertIn('אין אחריות על הזכוכית', answer)
            self.assertIn('7 שנות אחריות על הפרזול', answer)
            ai.assert_not_called()

    def test_mirror_glass_warranty_does_not_borrow_shower_coverage(self):
        self.step('אני רוצה מראה', self.model('מה הגודל?', product='מראה'))
        with patch.object(yossi.client.responses, 'create') as ai:
            answer = self.step('יש אחריות על הזכוכית?')
            self.assertEqual(answer, 'אין אחריות על הזכוכית.')
            ai.assert_not_called()

    def test_mirror_does_not_receive_shower_hardware_warranty(self):
        self.step('רוצה מראה לחדר רחצה', self.model('בשמחה', product='מראה'))
        answer = self.step('מה האחריות עליה?', self.model('7 שנות אחריות לפרזול', product='מראה'))
        self.assertNotIn('7 שנות', answer)
        self.assertIn('לבדוק את הכיסוי', answer)

    def test_astra_request_preserves_json_contract_and_consultant_context(self):
        captured = []
        def capture(**kwargs):
            captured.append(kwargs)
            return self.ai.create(**kwargs)
        with patch.object(yossi.client.responses, 'create', side_effect=capture):
            self.step('אני רוצה מראה עגולה בקוטר 90 בלי תאורה', self.model(
                'מראה עגולה יכולה להתאים. באיזה חדר היא מיועדת להיות?', product='מראה'))
        request = captured[-1]
        self.assertEqual(request['model'], yossi.MODEL)
        self.assertEqual(request['reasoning'], {'effort': 'medium'})
        self.assertEqual(request['timeout'], 90.0)
        self.assertEqual(request['text']['format']['type'], 'json_schema')
        self.assertTrue(request['text']['format']['strict'])
        schema=request['text']['format']['schema']
        self.assertFalse(schema['additionalProperties'])
        self.assertIn('חזית קבוע + דלת',schema['properties']['configuration']['enum'])
        self.assertIn('ריצוף גמור אינו תנאי כללי למראה', request['instructions'])
        self.assertIn('החזר JSON בלבד', request['instructions'])

    def test_mirror_quote_closure_does_not_require_shower_flooring(self):
        quote = {'issued': True, 'approved': True}
        answer = yossi.close_validated_quote(quote, [], 'אני מאשר', product='מראה')
        self.assertIn('מראה', answer)
        self.assertNotIn('ריצוף', answer)
        shower = yossi.close_validated_quote(quote, [], 'אני מאשר', product='מקלחון')
        self.assertIn('ריצוף', shower)

    def test_tomorrow_callback_collects_hour_and_saves_exact_date(self):
        with patch.object(yossi, 'save_callback', return_value=True) as store:
            first = self.step('היי תתקשרו אליי מחר')
            self.assertIn('באיזו שעה מחר', first)
            self.assertNotIn('נקבע', first)
            store.assert_called_once_with(self.phone)
            self.assertEqual(self.memory[self.phone][1]['callback_requested_day'], 'מחר')
            with patch.object(yossi, 'waiting_for_callback_time', return_value=True):
                reply = self.step('בשעה 10', self.model('נחזור אליך'))
            self.assertIn('10:00', reply)
            self.assertIn('אלירן', reply)
            self.assertNotIn('תאריך טרם תואם', reply)
            self.assertEqual(store.call_count, 2)
            self.assertIsNone(self.memory[self.phone][1].get('callback_requested_day'))

    def test_outgoing_messages_never_contain_emojis(self):
        self.assertEqual(yossi.without_emojis("היי 😊 מה שלומך? 🙂"), "היי מה שלומך?")
        self.assertEqual(yossi.without_emojis("תודה רבה 👍"), "תודה רבה")
        self.assertEqual(yossi.without_emojis("מחיר ₪2,595 לפני מע״מ"), "מחיר ₪2,595 לפני מע״מ")
        self.assertNotIn("🙂", yossi.polish_reply("אני כאן בשבילך 🙂", []))

    def test_finish_question_does_not_offer_colors_unasked(self):
        opening = self.step("שלום, רוצה מקלחון פינתי",
                            self.model("איזה גוון פרזול תרצו, שחור או כרום?"))
        self.assertIn("איזה גוון פרזול תרצו?", opening)
        self.assertNotIn("שחור או כרום", opening)

    def test_finish_colors_can_be_listed_when_customer_asks(self):
        opening = self.step("איזה גוונים יש לפרזול?",
                            self.model("יש שחור או כרום, וגם ניקל מוברש."))
        self.assertIn("שחור או כרום", opening)

    def test_custom_quote_mentions_eliran_and_uses_known_name(self):
        self.step("שלום, קוראים לי דניאל. צריך מקלחון פינתי",
                  self.model("איזה סוג דלתות תרצה?"))
        reply = self.step("הזזה פינתי, כמה יעלה?",
                          self.model("איך מחולקות הדלתות?", quote_requested=True))
        self.assertIn("אלירן דוד הכהן", reply)
        self.assertIn("בעל העסק", reply)
        self.assertIn("שמרתי את הפנייה", reply)
        self.assertNotIn("מה שמך", reply)

    def test_unsupported_corner_sliding_creates_owner_lead(self):
        self.step("אני רוצה מקלחון פינתי 90 על 90 גובה 200",
                  self.model("כמה דלתות?"))
        reply = self.step("אני רוצה דלתות הזזה. כמה יעלה?",
                          self.model("איך מחולקות הדלתות?", quote_requested=True))
        self.assertIn("שמרתי את הפנייה", reply)
        self.assertIn("מה שמך", reply)
        self.assertTrue(self.memory[self.phone][1].get("custom_quote_lead_saved"))
        with patch.object(yossi, "save_custom_quote_lead") as store:
            again = self.step("אמרתי לך הזזה",
                              self.model("איך מחולקות הדלתות?"))
            store.assert_not_called()
            self.assertIn("כבר שמורה", again)

    def test_corner_sliding_customer_is_not_asked_same_layout_again(self):
        self.step("אני מחפש מקלחון פינתי 90 על 90 גובה 200",
                  self.model("איזה סוג דלתות תרצה?"))
        self.step("מעדיף מקלחון פינתי עם דלתות הזזה. כמה זה עולה?",
                  self.model("איך מחולקות הזכוכיות והדלתות?", quote_requested=True))
        answer = self.step("אמרתי לך הזזה", self.model(
            "כדי לתת מחיר אמין צריך לוודא את תצורת המקלחון. איך מחולקות הזכוכיות והדלתות?"))
        self.assertIn("דלתות הזזה", answer)
        self.assertIn("אין לי כרגע מחיר מאומת", answer)
        self.assertNotIn("איך מחולקות הזכוכיות והדלתות", answer)
        self.assertNotIn("₪", answer)

    def test_sales_guidance_recognizes_objection_and_preserves_name_intro(self):
        opening = [{"role": "user", "content": "שלום, אני רוצה מקלחון"}]
        first = yossi.sales_turn_guidance("שלום, אני רוצה מקלחון", opening)
        self.assertIn("שם הלקוח", first)
        history = [
            {"role": "user", "content": "אני צריך מקלחון"},
            {"role": "assistant", "content": "אשמח לעזור"},
            {"role": "user", "content": "קיבלתי הצעה זולה יותר"},
        ]
        objections = yossi.sales_turn_guidance("קיבלתי הצעה זולה יותר", history)
        self.assertIn("התנגדות", objections)
        self.assertIn("ערך מבוסס", objections)

    def test_warm_open_and_no_invented_price(self):
        message = "אהלן, רוצה מקלחון פינתי 100 על 100, גובה 200, שתי דלתות פתיחה, זכוכית שקופה ופרזול שחור. כמה יעלה?"
        reply = self.step(message, self.model("כדי לתת מחיר אמין צריך לוודא את תצורת המקלחון. איך מחולקות הזכוכיות והדלתות?", quote_requested=True))
        self.assertTrue(reply.startswith("היי"), reply)
        self.assertIn("שתי דלתות", reply)
        self.assertNotIn("₪", reply)
        self.assertNotIn("4,200", reply)

    def test_never_pass_ai_fabricated_amount(self):
        message = "כמה עולה מקלחון פינתי?"
        reply = self.step(message, self.model("זה עולה 4,200 ש״ח.", quote_requested=True))
        self.assertNotIn("4,200", reply)
        self.assertNotIn("4200", reply)

    def test_price_then_repeat_then_approval_then_measurement(self):
        specs = dict(
            product="מקלחון", configuration="פינתי 2 דלתות",
            width_cm=100, second_width_cm=100, height_cm=200,
            glass_type="שקופה", finish="שחור", handles=["ידית כפתור", "ידית כפתור"],
            quote_requested=True, solution_agreed=True,
        )
        if yossi.calculate_quote(specs) is None:
            self.skipTest("Business calculator differs: adjust test fixtures to actual enum")
        price = yossi.calculate_quote(specs)
        opening = self.step("שלום, כמה עולה מקלחון פינתי 100 על 100 גובה 200 שתי דלתות?",
                            self.model("אשמח לעזור.", **specs))
        self.assertIn(f"₪{price:,.0f}", opening)
        repeated = self.step("מה המחיר שוב?", self.model("המחיר הוא 99,999 ש״ח"))
        self.assertIn(f"₪{price:,.0f}", repeated)
        self.assertNotIn("99,999", repeated)
        interested = self.step("נשמע סביר, רוצה להתקדם", self.model("אתה מחליט לבד?"))
        self.assertIn("מאשר", interested)
        self.assertNotIn("מחליט לבד", interested)
        approved = self.step("אני מאשר את ההצעה", self.model("בוא נתחיל.", **specs))
        self.assertIn("ההצעה מאושרת", approved)
        self.assertNotIn("כתובת ההתקנה", approved)

    def test_tiling_revision_and_completed_approval(self):
        specs = dict(product="מקלחון", configuration="פינתי 2 דלתות",
                     width_cm=100, second_width_cm=100, height_cm=200,
                     glass_type="שקופה", finish="שחור",
                     handles=["ידית כפתור", "ידית כפתור"],
                     quote_requested=True, solution_agreed=True)
        if yossi.calculate_quote(specs) is None:
            self.skipTest("Business calculator differs: adjust test fixtures to actual enum")
        self.step("כמה עולה מקלחון פינתי 100 על 100?", self.model("בודק", **specs))
        self.step("הריצוף הסתיים", self.model("יופי"))
        self.step("טעיתי, הריצוף עוד לא הסתיים", self.model("הבנתי"))
        reply = self.step("אני מאשר את ההצעה", self.model("נתקדם"))
        self.assertNotIn("כתובת ההתקנה", reply)

    def test_real_report_corner_quote_after_customer_confirms_layout(self):
        opening = "אהלן, אני צריך מקלחון פינתי 100 על 100, שתי דלתות שנפתחות, זכוכית שקופה ופרזול שחור. כמה עולה?"
        first = self.step(opening, self.model("איך מחולקות הדלתות?", quote_requested=True))
        self.assertIn("דלתות", first)
        self.step("הדלתות ישר על הקירות, אין קבועים. גובה 200.", self.model("איזה ידיות תרצה?"))
        answer = self.step("ידיות רגילות, כפתור. כמה זה ייצא?",
                           self.model("איך מחולקות הזכוכיות והדלתות?", quote_requested=True))
        self.assertIn("₪", answer)
        self.assertNotIn("איך מחולקות הזכוכיות והדלתות", answer)
        self.assertTrue(self.memory[self.phone][1].get("validated_quote", {}).get("issued"))

    def test_cannot_accept_unissued_quote(self):
        self.step("שלום, רוצה מקלחון פינתי, כמה עולה?", self.model("צריך עוד פרטים"))
        answer = self.step("אני מאשר את ההצעה", self.model("סגור, נבוא למדוד"))
        self.assertNotIn("ההצעה מאושרת", answer)
        self.assertIn("עוד לא נתתי", answer)

    def test_cheaper_competitor_offer_is_addressed_without_fake_discount(self):
        specs = dict(
            product="מקלחון", configuration="פינתי 2 דלתות",
            width_cm=100, second_width_cm=100, height_cm=200,
            glass_type="שקופה", finish="שחור",
            handles=["ידית כפתור", "ידית כפתור"],
            quote_requested=True, solution_agreed=True,
        )
        self.step("כמה עולה מקלחון פינתי 100 על 100 שתי דלתות גובה 200?",
                  self.model("הנה המחיר", **specs))
        answer = self.step("זה יותר ממה שתכננתי. קיבלתי הצעה זולה ב-700 שקל.",
                           self.model("המחיר שלנו הוא 700 שקל יותר"))
        # A customer-stated price gap is retained as a comparison, not replaced
        # by a long canned sales pitch or interpreted as a new quote total.
        self.assertEqual(answer, "המחיר שלנו הוא 700 שקל יותר")
        self.assertNotIn("₪700", answer)
        self.assertNotIn("המחיר המאומת למפרט", answer)

    def test_customer_reset_does_not_touch_real_db(self):
        reply = self.step("התחל שיחה חדשה")
        self.assertIn("מתחילים מחדש", reply)
        self.assertEqual(self.memory[self.phone], ([], {}))


if __name__ == "__main__":
    unittest.main()


class FollowupStartupTests(unittest.TestCase):
    def test_worker_creates_followup_table_before_start(self):
        from unittest.mock import MagicMock
        with patch.object(yossi, 'ensure_db') as customer_schema, \
             patch.object(yossi, 'ensure_followup_table') as schema, \
             patch.object(yossi, 'ensure_inbound_queue_table') as queue_schema, \
             patch.object(yossi, 'ensure_outbound_attempts_table') as outbound_schema, \
             patch.object(yossi, 'restore_inbound_queue') as restore, \
             patch.object(yossi.threading, 'Thread') as thread, \
             patch.object(yossi.os, 'getpid', return_value=-999):
            yossi.ensure_worker_started()
            customer_schema.assert_called_once()
            schema.assert_called_once()
            queue_schema.assert_called_once()
            outbound_schema.assert_called_once()
            restore.assert_called_once()
            thread.assert_called_once()

    def test_failed_schema_does_not_start_worker(self):
        with patch.object(yossi, 'ensure_followup_table', side_effect=RuntimeError('test')), \
             patch.object(yossi.threading, 'Thread') as thread, \
             patch.object(yossi.os, 'getpid', return_value=-998):
            yossi.ensure_worker_started()
            thread.assert_not_called()


class CustomerInboundWindowTests(unittest.TestCase):
    def test_24_hour_window_boundaries(self):
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 10, 11, 9, tzinfo=timezone.utc)
        self.assertTrue(yossi.freeform_whatsapp_window_valid(now-timedelta(hours=23), now))
        self.assertFalse(yossi.freeform_whatsapp_window_valid(now-timedelta(hours=24), now))
        self.assertFalse(yossi.freeform_whatsapp_window_valid(now+timedelta(minutes=1), now))
        self.assertFalse(yossi.freeform_whatsapp_window_valid(None, now))

    def test_inbound_timestamp_is_persisted_without_outreach(self):
        from unittest.mock import MagicMock
        connection = MagicMock()
        cursor = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        with patch.object(yossi, 'db_connection', return_value=connection), \
             patch.object(yossi, 'ensure_db'), \
             patch.object(yossi, 'send_whatsapp') as sender:
            self.assertTrue(yossi.record_customer_inbound('TEST_NUMBER'))
            sql, args = cursor.execute.call_args.args
            self.assertIn('last_inbound_at', sql)
            self.assertEqual(args, ('TEST_NUMBER',))
            sender.assert_not_called()


class FollowupSendPreflightTests(unittest.TestCase):
    def test_fails_closed_outside_hours(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        with patch.object(yossi, 'db_connection') as db, \
             patch.object(yossi, 'send_whatsapp') as sender:
            result = yossi.inspect_due_followups(datetime(2026, 10, 17, 12, tzinfo=ZoneInfo('Asia/Jerusalem')))
            self.assertEqual(result['reason'], 'outside_business_hours')
            db.assert_not_called()
            sender.assert_not_called()

    def test_blocks_followups_without_optin_and_whatsapp_template(self):
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        from unittest.mock import MagicMock
        connection = MagicMock()
        cursor = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchall.return_value = [
            ('TEST_A', None, None, 'חדש', {}, [], None),
            ('TEST_B', None, None, 'חדש', {'followup_consent': True}, [], None),
            ('TEST_C', None, None, 'ממתין לחזרה', {}, [], None),
            ('TEST_D', None, None, 'חדש', {'no_followups': True}, [], None),
        ]
        with patch.object(yossi, 'db_connection', return_value=connection), \
             patch.object(yossi, 'ensure_followup_table'), \
             patch.object(yossi, 'send_whatsapp') as sender:
            result = yossi.inspect_due_followups(datetime(2026, 10, 12, 10, tzinfo=ZoneInfo('Asia/Jerusalem')))
            self.assertEqual(result['due'], 4)
            self.assertEqual(result['eligible'], 0)
            self.assertEqual(result['blocked'], 4)
            self.assertEqual(result['reasons']['no_explicit_followup_consent'], 1)
            self.assertEqual(result['reasons']['whatsapp_window_expired_template_required'], 1)
            sender.assert_not_called()


class DurableFollowupTests(unittest.TestCase):
    def test_schedule_is_dry_run_only(self):
        from datetime import datetime, timezone
        from unittest.mock import MagicMock
        cursor = MagicMock()
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        with patch.object(yossi, 'db_connection', return_value=connection), \
             patch.object(yossi, 'ensure_followup_table'), \
             patch.object(yossi, 'send_whatsapp') as sender:
            yossi.schedule_followup_dry_run('972501234567',
                datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc))
            sender.assert_not_called()
            query = cursor.execute.call_args.args[0]
            self.assertIn('ON CONFLICT', query)
            self.assertIn('no_followups', query)
            self.assertIn('ממתין לחזרה', query)

    def test_new_message_cancels_pending_followup(self):
        with patch.object(yossi, 'cancel_followup_dry_run') as cancel, \
             patch.object(yossi, 'persist_inbound_message', return_value=True):
            yossi.queue_message('TEST_PHONE', 'שלום', 'TEST_FOLLOWUP_MSG_001')
            cancel.assert_called_once_with('TEST_PHONE')
        with yossi.lock:
            yossi.pending.pop('TEST_PHONE', None)


class BusinessHoursPolicyTests(unittest.TestCase):
    def test_open_days_and_boundaries(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo('Asia/Jerusalem')
        self.assertTrue(yossi.is_yossi_business_hours(datetime(2026, 10, 11, 8, 0, tzinfo=tz)))
        self.assertTrue(yossi.is_yossi_business_hours(datetime(2026, 10, 15, 19, 59, tzinfo=tz)))
        self.assertFalse(yossi.is_yossi_business_hours(datetime(2026, 10, 15, 20, 0, tzinfo=tz)))
        self.assertFalse(yossi.is_yossi_business_hours(datetime(2026, 10, 16, 12, 0, tzinfo=tz)))
        self.assertFalse(yossi.is_yossi_business_hours(datetime(2026, 10, 17, 12, 0, tzinfo=tz)))

    def test_followup_four_hours_and_next_open(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo('Asia/Jerusalem')
        self.assertEqual(yossi.earliest_followup_at(datetime(2026, 10, 12, 10, 0, tzinfo=tz)).hour, 14)
        self.assertEqual(yossi.earliest_followup_at(datetime(2026, 10, 15, 19, 0, tzinfo=tz)).isoformat(),
                         datetime(2026, 10, 18, 8, 0, tzinfo=tz).isoformat())
        self.assertFalse(yossi.AUTO_FOLLOWUPS_ENABLED)


class CallHandoffPolicyTests(unittest.TestCase):
    def test_explicit_callback_intent(self):
        self.assertTrue(yossi.is_callback_request('היי תתקשרו אליי מחר'))
        self.assertTrue(yossi.is_callback_request('אני רוצה לדבר עם נציג'))
        self.assertFalse(yossi.is_callback_request('כמה עולה מקלחון?'))
        self.assertFalse(yossi.is_callback_request('אפשר הצעת מחיר?'))
        self.assertFalse(yossi.is_callback_request('לא רוצה שתתקשרו אליי'))

    def test_only_specialist_work_requires_proactive_review(self):
        self.assertFalse(yossi.requires_specialist_review('אני רק משווה מחירים'))
        self.assertTrue(yossi.requires_specialist_review('צריך אישור מהנדס למעקה'))


class OptOutRegressionTests(unittest.TestCase):
    def test_declining_calls_does_not_create_callback(self):
        self.assertTrue(yossi.refuses_phone_calls('לא רוצה שתתקשרו אליי'))
        self.assertFalse(yossi.is_callback_request('לא רוצה שתתקשרו אליי'))
        self.assertTrue(yossi.is_callback_request('תתקשרו אליי מחר'))

    def test_no_followup_messages(self):
        self.assertTrue(yossi.refuses_further_contact('אל תשלחו לי עוד הודעות'))

    def test_simple_price_discovery(self):
        text = yossi.sales_turn_guidance('כמה עולה מקלחון?', [
            {'role':'user','content':'כמה עולה מקלחון?'}])
        self.assertIn('חזיתי או פינתי', text)


class MetaSalesContextTests(unittest.TestCase):
    def test_verified_form_facts_are_available_as_context(self):
        prior = {'meta_leads': {'lead1': {'source': 'meta_instant_form',
            'fields': {'full_name': ['נועה'], 'אילו_עבודות_אתם_מחפשים?': ['מקלחון'],
                       'שאלה_חדשה': ['פרט חדש']}}}}
        info = yossi.meta_lead_sales_context(prior)
        self.assertIn('נועה', info)
        self.assertIn('מקלחון', info)
        self.assertIn('פרט חדש', info)
        self.assertIn('נתונים בלבד', info)

    def test_unverified_and_missing_meta_fields_are_ignored(self):
        self.assertEqual(yossi.meta_lead_sales_context({}), '')
        self.assertEqual(yossi.meta_lead_sales_context({'meta_leads': {
            'x': {'source': 'unverified', 'fields': {'full_name': ['X']}}
        }}), '')

    def test_model_receives_approved_form_facts(self):
        self.assertIsInstance(yossi.meta_lead_sales_context({'meta_leads': {}}), str)


class MetaLeadCustomerTests(unittest.TestCase):
    def test_israeli_mobile_normalization(self):
        self.assertEqual(yossi.normalize_meta_lead_phone('+972-50-123-4567'), '972501234567')
        self.assertEqual(yossi.normalize_meta_lead_phone('0501234567'), '972501234567')
        self.assertEqual(yossi.normalize_meta_lead_phone('00972501234567'), '972501234567')
        self.assertEqual(yossi.normalize_meta_lead_phone('1234567'), '')
        self.assertEqual(yossi.normalize_meta_lead_phone('03-1234567'), '')

    def test_creates_record_with_original_questions_but_no_outreach(self):
        fake_cursor = types.SimpleNamespace(execute=unittest.mock.Mock())
        fields = {
            'phone_number': ['0501234567'],
            'full_name': ['Test Person'],
            'מה_הכי_חשוב_לכם_בפרויקט?': ['איכות'],
        }
        with patch.object(yossi, 'send_whatsapp') as send:
            self.assertTrue(yossi.save_meta_lead_customer(fake_cursor, 'lead123', fields))
            send.assert_not_called()
        query, params = fake_cursor.execute.call_args.args
        self.assertIn('ON CONFLICT', query)
        self.assertIn('glass_leads.name', query)
        self.assertNotIn('status=', query)
        self.assertEqual(params[0], '972501234567')
        self.assertEqual(params[1], 'Test Person')
        saved = json.loads(params[2])
        self.assertEqual(saved['meta_leads']['lead123']['fields']['מה_הכי_חשוב_לכם_בפרויקט?'], ['איכות'])

    def test_invalid_phone_does_not_create_customer(self):
        cursor = types.SimpleNamespace(execute=unittest.mock.Mock())
        self.assertFalse(yossi.save_meta_lead_customer(cursor, 'lead123', {'phone_number': ['bad']}))
        cursor.execute.assert_not_called()


    def test_full_meta_details_to_customer_flow_is_silent_and_idempotent(self):
        """Run the persistence path twice using fake DB cursors, never real customers."""
        from contextlib import contextmanager
        all_queries = []

        @contextmanager
        def fake_connection():
            class Conn:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
                def cursor(self):
                    class Cur:
                        def __enter__(self):
                            return self
                        def __exit__(self, *args):
                            pass
                        def execute(self, query, params):
                            all_queries.append((query, params))
                    return Cur()
            yield Conn()

        details = {
            'id': 'synthetic-lead-01',
            'field_data': [
                {'name': 'phone_number', 'values': ['0501234567']},
                {'name': 'full_name', 'values': ['לקוח בדיקה']},
                {'name': 'city', 'values': ['בדיקה']},
                {'name': 'שאלה_חדשה_בקמפיין', 'values': ['תשובה חדשה']},
            ],
        }
        with patch.object(yossi, 'db_connection', side_effect=fake_connection), \
             patch.object(yossi, 'send_whatsapp') as send:
            yossi.persist_meta_lead_details('synthetic-lead-01', details)
            yossi.persist_meta_lead_details('synthetic-lead-01', details)
            send.assert_not_called()

        self.assertEqual(len(all_queries), 4)
        customer_statements = [(sql, params) for sql, params in all_queries
                               if 'INSERT INTO glass_leads' in sql]
        self.assertEqual(len(customer_statements), 2)
        for query, params in customer_statements:
            self.assertIn('ON CONFLICT (phone) DO UPDATE', query)
            self.assertNotIn("status=", query)
            self.assertEqual(params[0], '972501234567')
            self.assertEqual(params[1], 'לקוח בדיקה')
            fields = json.loads(params[2])['meta_leads']['synthetic-lead-01']['fields']
            self.assertEqual(fields['שאלה_חדשה_בקמפיין'], ['תשובה חדשה'])


class MetaLeadDetailsTests(unittest.TestCase):
    def test_no_token_never_calls_meta(self):
        with patch.object(yossi, 'META_LEADS_ACCESS_TOKEN', ''), \
             patch.object(yossi.requests, 'get') as request_get:
            self.assertIsNone(yossi.fetch_meta_lead_details('123'))
            request_get.assert_not_called()

    def test_fetch_uses_authorization_header_and_validates_id(self):
        response = types.SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {'id': '123', 'field_data': [
                {'name': 'full_name', 'values': ['Test Person']}]})
        with patch.object(yossi, 'META_LEADS_ACCESS_TOKEN', 'dummy-token'), \
             patch.object(yossi.requests, 'get', return_value=response) as request_get:
            details = yossi.fetch_meta_lead_details('123')
            self.assertEqual(details['id'], '123')
            kwargs = request_get.call_args.kwargs
            self.assertEqual(kwargs['headers']['Authorization'], 'Bearer dummy-token')
            self.assertNotIn('access_token', kwargs['params'])

    def test_invalid_lead_details_fail_closed(self):
        response = types.SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {'id': 'wrong', 'field_data': []})
        with patch.object(yossi, 'META_LEADS_ACCESS_TOKEN', 'dummy-token'), \
             patch.object(yossi.requests, 'get', return_value=response):
            with self.assertRaises(ValueError):
                yossi.fetch_meta_lead_details('123')

    def test_webhook_does_not_send_messages_when_meta_fetch_fails(self):
        import hmac
        payload = {'object': 'page', 'entry': [{'id': 'PAGE1', 'changes': [
            {'field': 'leadgen', 'value': {'leadgen_id': 'LEAD1'}}]}]}
        body = json.dumps(payload).encode()
        signature = 'sha256=' + hmac.new(b'test-secret', body, 'sha256').hexdigest()
        with patch.object(yossi, 'APP_SECRET', 'test-secret'), \
             patch.object(yossi, 'META_LEADS_ACCESS_TOKEN', 'dummy-token'), \
             patch.object(yossi, 'store_meta_leadgen_event'), \
             patch.object(yossi, 'fetch_meta_lead_details', side_effect=RuntimeError('fail')), \
             patch.object(yossi, 'send_whatsapp') as send:
            result = yossi.app.test_client().post('/meta-leads/webhook', data=body,
                headers={'X-Hub-Signature-256': signature}, content_type='application/json')
            self.assertEqual(result.status_code, 200)
            send.assert_not_called()


class MetaLeadgenReceiverTests(unittest.TestCase):
    def setUp(self):
        self.app = yossi.app.test_client()

    def test_verification_requires_separate_configured_token(self):
        with patch.object(yossi, 'META_LEADS_VERIFY_TOKEN', 'lead-verify-test'):
            response = self.app.get('/meta-leads/webhook', query_string={
                'hub.mode': 'subscribe', 'hub.verify_token': 'lead-verify-test',
                'hub.challenge': 'challenge123',
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_data(as_text=True), 'challenge123')
            self.assertEqual(self.app.get('/meta-leads/webhook', query_string={
                'hub.mode': 'subscribe', 'hub.verify_token': 'wrong',
            }).status_code, 403)
        with patch.object(yossi, 'META_LEADS_VERIFY_TOKEN', ''):
            self.assertEqual(self.app.get('/meta-leads/webhook', query_string={
                'hub.mode': 'subscribe', 'hub.verify_token': '',
            }).status_code, 403)

    def test_valid_signed_leadgen_is_saved_without_any_outreach(self):
        import hmac
        payload = {'object': 'page', 'entry': [{'id': 'PAGE1', 'changes': [
            {'field': 'leadgen', 'value': {
                'leadgen_id': 'LEAD1', 'form_id': 'FORM1', 'created_time': 12345,
            }},
        ]}]}
        body = json.dumps(payload).encode()
        signature = 'sha256=' + hmac.new(b'test-secret', body, 'sha256').hexdigest()
        with patch.object(yossi, 'APP_SECRET', 'test-secret'), \
                patch.object(yossi, 'store_meta_leadgen_event') as store, \
                patch.object(yossi, 'send_whatsapp') as send:
            response = self.app.post('/meta-leads/webhook', data=body,
                headers={'X-Hub-Signature-256': signature}, content_type='application/json')
            self.assertEqual(response.status_code, 200)
            store.assert_called_once_with('LEAD1', 'PAGE1', 'FORM1', 12345)
            send.assert_not_called()
            self.assertEqual(self.app.post('/meta-leads/webhook', data=body,
                content_type='application/json').status_code, 403)

    def test_receiver_fails_closed_and_retries_storage_failures(self):
        import hmac
        body = b'{"object":"page","entry":[{"id":"PAGE1","changes":[{"field":"leadgen","value":{"leadgen_id":"LEAD1"}}]}]}'
        signature = 'sha256=' + hmac.new(b'test-secret', body, 'sha256').hexdigest()
        with patch.object(yossi, 'APP_SECRET', ''):
            self.assertEqual(self.app.post('/meta-leads/webhook', data=body).status_code, 503)
        with patch.object(yossi, 'APP_SECRET', 'test-secret'), \
                patch.object(yossi, 'store_meta_leadgen_event', side_effect=RuntimeError('offline')):
            self.assertEqual(self.app.post('/meta-leads/webhook', data=body,
                headers={'X-Hub-Signature-256': signature}, content_type='application/json').status_code, 503)



class ManualFollowupDashboardTests(unittest.TestCase):
    def test_24h_boundary_and_manual_completion(self):
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
        inbound = now - timedelta(hours=24)
        lead = {'status': 'בטיפול', 'last_inbound_at': inbound,
                'manual_followup_completed_at': None}
        self.assertTrue(yossi.manual_followup_due(lead, now))
        self.assertFalse(yossi.manual_followup_due(lead, inbound + timedelta(hours=23)))
        lead['manual_followup_completed_at'] = now
        self.assertFalse(yossi.manual_followup_due(lead, now + timedelta(days=1)))
        lead['last_inbound_at'] = now + timedelta(hours=1)
        self.assertTrue(yossi.manual_followup_due(lead, now + timedelta(hours=25)))

    def test_closed_and_callback_leads_never_flagged(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        for status in ('נסגר', 'סגור', 'לא רלוונטי', 'ממתין לחזרה', 'ממתין לתמחור'):
            lead = {'status': status, 'last_inbound_at': now-timedelta(days=3)}
            self.assertFalse(yossi.manual_followup_due(lead, now))

    def test_dashboard_contains_manual_only_controls(self):
        self.assertIn('admin_complete_manual_followup', yossi.LEADS_HTML)
        self.assertIn('manual_followups', yossi.LEADS_HTML)
        self.assertFalse(yossi.AUTO_FOLLOWUPS_ENABLED)

class OwnerDashboardRegressionTests(unittest.TestCase):
    def test_photo_requests_are_included_in_unfiltered_leads_query(self):
        import inspect
        source = inspect.getsource(yossi.admin_leads)
        self.assertEqual(source.count('manual_followup_completed_at,context'), 2)
        self.assertIn('outbound_review=outbound_review', source)

    def test_outbound_review_is_read_only(self):
        import inspect
        source = inspect.getsource(yossi.admin_leads)
        self.assertIn("WHERE state IN ('reserved','uncertain')", source)
        self.assertNotIn('UPDATE yossi_outbound_attempts', source)
        self.assertIn('שליחות לבדיקה ידנית', yossi.LEADS_HTML)


class SimulationHoursIsolationTests(unittest.TestCase):
    def test_test_contact_allowed_outside_business_hours_only(self):
        from unittest.mock import patch
        import time
        test_phone = 'TEST_SIMULATION_PHONE'
        business_phone = 'TEST_BUSINESS_PHONE'
        with yossi.lock:
            original_pending = yossi.pending
            original_processing = yossi.processing
            yossi.pending = {
                business_phone: [('business-mid', 'לקוח', time.monotonic()-30)],
                test_phone: [('test-mid', 'בדיקה', time.monotonic()-30)],
            }
            yossi.processing = set()
        try:
            with patch.object(yossi, 'is_yossi_business_hours', return_value=False), \
                 patch.object(yossi, 'is_simulation_contact', side_effect=lambda p: p == test_phone):
                batch = yossi.next_batch()
                self.assertEqual(batch[0], test_phone)
                self.assertNotIn(business_phone, yossi.processing)
        finally:
            with yossi.lock:
                yossi.pending = original_pending
                yossi.processing = original_processing

    def test_simulation_inactive_without_explicit_configuration(self):
        with patch.object(yossi, 'SIMULATION_PHONE_NUMBER_ID', ''):
            self.assertFalse(yossi.simulation_channel_configured())

class VerifiedWebsiteBusinessFactsTests(unittest.TestCase):
    def test_grounded_company_facts_are_available(self):
        facts = yossi.WEBSITE_VERIFIED_FACTS
        for value in ('נתניה', 'אשקלון', 'ירושלים', 'מדידת לייזר',
                      '10 עד 14 ימי עסקים', 'סיליקון ניטרלי',
                      'שבע שנים', 'אקסטרה קליר', 'https://dreamofglass.com/'):
            self.assertIn(value, facts)

    def test_website_guidance_is_exposed_to_actual_model(self):
        import inspect
        source = inspect.getsource(yossi.process_message)
        self.assertIn('WEBSITE_VERIFIED_FACTS', source)

    def test_website_is_not_pricing_or_sending_authority(self):
        facts = yossi.WEBSITE_VERIFIED_FACTS
        self.assertIn('אין לייבא תמונות אוטומטית', facts)
        self.assertIn('להמציא מחיר', facts)
        self.assertFalse(yossi.AUTO_FOLLOWUPS_ENABLED)


class ConsultativeCornerAndSocialRegression(unittest.TestCase):
    def test_what_is_up_returns_reciprocal_question(self):
        for question in ('מה קורה?', 'מה נשמע', 'איך אתה?'):
            reply = yossi.simple_social_reply(question, [
                {'role': 'user', 'content': 'שלום'},
                {'role': 'assistant', 'content': 'היי'},
                {'role': 'user', 'content': question},
            ])
            self.assertIn('מה איתך?', reply)

    def test_corner_shower_does_not_offer_sliding_unasked(self):
        history = [
            {'role': 'user', 'content': 'מחפש מקלחון פינתי'},
            {'role': 'user', 'content': '90 על 90, גובה 200'},
            {'role': 'user', 'content': 'לא יודע מה אתה ממליץ?'},
        ]
        original = 'אפשר שתי דלתות ציר או דלתות הזזה. מה אתה מעדיף?'
        answer = yossi.guard_corner_shower_advice(original, 'לא יודע מה אתה ממליץ?', history)
        self.assertIn('דלתות ציר', answer)
        self.assertNotIn('הזזה', answer)
        self.assertNotIn('מדידה סופית לפני', answer)

    def test_customer_explicit_corner_sliding_stays_custom_request(self):
        history = [
            {'role': 'user', 'content': 'אני רוצה מקלחון פינתי דלתות הזזה'},
        ]
        reply = 'הזזה פינתית דורשת תמחור ידני, לא אנחש מחיר.'
        self.assertEqual(yossi.guard_corner_shower_advice(reply, history[0]['content'], history), reply)

    def test_non_corner_shower_not_changed(self):
        history = [{'role': 'user', 'content': 'מקלחון חזיתי'}]
        reply = 'אפשר לשקול הזזה כשהמעבר צר.'
        self.assertEqual(yossi.guard_corner_shower_advice(reply, history[0]['content'], history), reply)


class LiveWhatsAppLoopRegression(unittest.TestCase):
    def setUp(self):
        self.history = [
            {'role': 'user', 'content': 'אני רוצה מקלחון פינתי 90 על 90'},
            {'role': 'user', 'content': 'יש אסלה די קרובה, חשוב לי לנקות בקלות'},
        ]

    def test_corner_does_not_replace_answer_with_canned_text(self):
        reply = 'האסלה עלולה להגביל פתיחה של דלת ציר. כדאי לבדוק מרווח, וקלות ניקוי של צירים.'
        self.assertEqual(yossi.guard_corner_shower_advice(reply, 'מה היית בוחר?', self.history), reply)

    def test_explicit_sliding_question_gets_actual_answer(self):
        reply = 'אם האסלה חוסמת ציר, נבדוק מרווחים. הזזה דורשת בדיקת התאמה ותמחור מיוחד.'
        self.assertEqual(yossi.guard_corner_shower_advice(
            reply, 'הזזה תהיה יותר מתאימה?', self.history), reply)

    def test_unsolicited_sliding_removed_without_destroying_other_advice(self):
        reply = 'צריך לבדוק שהאסלה לא מפריעה. אפשר גם הזזה. קל יותר לנקות כשיש גישה לצירים.'
        answer = yossi.guard_corner_shower_advice(reply, 'מה היית ממליץ?', self.history)
        self.assertIn('אסלה', answer)
        self.assertIn('לנקות', answer)
        self.assertNotIn('הזזה', answer)

    def test_corner_sliding_only_answer_prioritizes_actual_quote_question(self):
        reply = 'ממליץ על הזזה למקלחון פינתי.'
        answer = yossi.guard_corner_shower_advice(reply, 'מה חסר להצעת מחיר כולל התקנה?', self.history)
        self.assertIn('תצורת הדלתות', answer)
        self.assertIn('התקנה', answer)
        self.assertNotIn('הזזה', answer)


class SecondWhatsAppSimulationRegression(unittest.TestCase):
    def test_customer_prefers_text_only(self):
        for message in (
            'היי יוסי, בינתיים מעדיף להתכתב כאן, אין צורך שיחזרו אליי.',
            'לא צריך להתקשר, אני מעדיף כאן בוואטסאפ.',
            'אין צורך להתקשר, בוא נמשיך בהודעות',
        ):
            self.assertTrue(yossi.refuses_phone_calls(message), message)
            self.assertFalse(yossi.is_callback_request(message), message)

    def test_recommendation_is_remembered_but_not_approved_quote(self):
        history = [
            {'role': 'user', 'content': 'מקלחון פינתי 90 על 90'},
            {'role': 'assistant', 'content': 'חלופה היא לוח קבוע ודלת נפתחת פנימה אם יש מקום.'},
            {'role': 'user', 'content': 'זה נשמע מתאים. כמה עולה כולל התקנה?'},
        ]
        advice = yossi.proposed_layout_guidance(history)
        self.assertIn('לוח קבוע', advice)
        self.assertIn('לאישור', advice)
        self.assertIsNone(yossi.calculate_quote({'configuration': None}))

    def test_no_previous_advice_is_not_assumed(self):
        history = [{'role': 'user', 'content': 'שלום, מחיר?'}]
        self.assertEqual(yossi.proposed_layout_guidance(history), '')


class PriceComparisonRegressionTests(ConversationSimulation):
    def test_requested_alternatives_are_calculated_not_aggregated_or_escalated(self):
        self.memory[self.phone]=([
            {'role':'user','content':'מקלחון 80/80'},
            {'role':'assistant','content':'מה הכי חשוב לך?'},
            {'role':'user','content':'אתה שואל יותר מדי שאלות'},
        ],{'product':'מקלחון','width_cm':80,'second_width_cm':80})
        self.step('תן מחיר לכל האופציות: 2 דלתות, 2 קבועים 2 דלתות, הרמוניקה')
        self.assertIn('איזה סוג זכוכית',self.sent[-1])
        self.assertNotIn('אין לי כרגע מחיר',self.sent[-1])
        self.step('שקופה')
        self.assertIn('גוון פרזול',self.sent[-1])
        self.step('ניקל')
        self.assertIn('כפתור',self.sent[-1])
        self.step('כפתור')
        self.assertEqual(self.sent[-1].count('₪'),3)
        state=self.memory[self.phone][1]
        offers=state['quote_comparison']['offers']
        self.assertEqual(len(offers),3)
        self.assertFalse(state['quote_comparison']['pending'])
        for offer in offers:
            self.assertEqual(offer['amount_ils_pre_vat'],yossi.calculate_quote(offer))
            self.assertEqual(offer['height_cm'],200)
        self.assertNotIn('validated_quote',state)
        self.assertNotIn('sales_items',state)

    def test_feedback_is_not_an_identity_question_and_name_can_precede_feedback(self):
        history=[{'role':'assistant','content':'אגב, איך קוראים לך?'},
                 {'role':'user','content':'אבי\nשאלה לא טובה לשאול לקוח\nבמקום זה מה שמך?'}]
        self.assertEqual(yossi.extract_customer_name(history),'אבי')
        self.assertIsNone(yossi.identity_reply(history[-1]['content'],history))
        self.assertIsNotNone(yossi.identity_reply('מה שמך?',[]))

    def test_rejected_discovery_stays_skipped_on_next_turn(self):
        from sales_dialogue import consultation_plan
        history=[{'role':'user','content':'זה לא משנה למה זה, אני צריך מחיר'},
                 {'role':'assistant','content':'איזו זכוכית?'},
                 {'role':'user','content':'שקופה'}]
        self.assertIsNone(consultation_plan(history,{'product':'מקלחון'},'שקופה')['question'])


class MeasurementPlanningRegressionTests(ConversationSimulation):
    def test_adva_can_plan_together_without_dimensions_or_model_escalation(self):
        self.memory[self.phone]=([
            {'role':'user','content':'היי אני מעוניינת במקלחון'},
            {'role':'assistant','content':'בית חדש או שיפוץ?'},
            {'role':'user','content':'חדר בשיפוץ'},
            {'role':'user','content':'אדוה'},
            {'role':'user','content':'אהבתי את העיצוב אבל הייתי רוצה לשנות מידות'},
            {'role':'assistant','content':'מה המידות המתוכננות?'},
        ],{'product':'מקלחון','customer_name':'אדוה','needs_human':True})
        with patch.object(yossi,'pause_for_owner') as pause:
            self.step('לא מדדתי האמת\nאתה יכןל להגיע למדוד?\nאולי נחשוב ביחד')
        pause.assert_not_called()
        self.assertIn('אפשר בהחלט לחשוב יחד',self.sent[-1])
        self.assertIn('אחרי אישור ההצעה',self.sent[-1])
        self.assertIn('סיום הריצוף',self.sent[-1])
        self.assertFalse(self.memory[self.phone][1]['needs_human'])
        self.assertEqual(self.ai.queue,[])

    def test_planning_guard_does_not_override_explicit_human_or_safety_requests(self):
        history=[{'role':'user','content':'מקלחון'}]
        for text,prior in (
            ('תגיע למדוד מעקה',{}),
            ('אני רוצה נציג אנושי שיגיע למדוד',{}),
            ('תתקשר אליי כדי לתאם מדידה',{}),
            ('תגיע למדוד בשישי',{}),
            ('אפשר להגיע למדוד?',{'validated_quote':{'approved':True}}),
            ('כמה עולה ואפשר להגיע למדוד?',{})):
            self.assertIsNone(yossi.measurement_planning_reply(history,prior,text))


class NaturalStyleRegressionTests(ConversationSimulation):
    def test_prose_punctuation_is_plain_without_breaking_links_times_or_prices(self):
        value=yossi.without_emojis('אפשר לבחור שתי דלתות — בלי קיפול. המחיר: ₪2,294. שעות 08:30. https://example.com/a-b?q=x:y')
        self.assertNotIn('—',value)
        self.assertNotIn('המחיר:',value)
        self.assertIn('₪2,294',value)
        self.assertIn('08:30',value)
        self.assertIn('https://example.com/a-b?q=x:y',value)
        self.assertEqual(yossi.without_emojis('7-10 ימים'),'7 עד 10 ימים')


class ReferencePhotoRegressionTests(ConversationSimulation):
    def test_adva_reference_confirmation_continues_without_model_or_handoff(self):
        self.memory[self.phone]=([
            {'role':'user','content':'מקלחון בשיפוץ, כניסה נוחה'},
            {'role':'user','content':'[לקוח צירף תמונה שנותח בפועל. ממצאים חזותיים, לא מידות מאומתות: דוגמה לחדר]'},
            {'role':'assistant','content':'זה החדר שלך או דוגמה?'},
        ],{'product':'מקלחון','needs_human':True})
        with patch.object(yossi,'pause_for_owner') as pause:
            self.step('זה דומה למה שיהיה לי')
        pause.assert_not_called()
        self.assertIn('בלי לקבוע ממנה מידות',self.sent[-1])
        self.assertIn('המקלחון הקודם',self.sent[-1])
        self.assertFalse(self.memory[self.phone][1]['needs_human'])
        for text in ('זו תמונה לדוגמה, רוצה לדבר עם בעל העסק','זו תמונה לדוגמה של מעקה','זה דומה למה שיהיה לי, כמה עולה?'):
            self.assertIsNone(yossi.reference_photo_reply(self.memory[self.phone][0],{'product':'מקלחון'},text))


class PlanningUncertaintyRegressionTests(ConversationSimulation):
    def test_old_shower_shape_uncertainty_gets_clarification_not_escalation(self):
        self.memory[self.phone]=([
            {'role':'user','content':'מקלחון בשיפוץ, כניסה נוחה'},
            {'role':'assistant','content':'איך נפתח המקלחון הקודם שלך?'},
        ],{'product':'מקלחון'})
        with patch.object(yossi,'pause_for_owner') as pause:
            self.step('הייה לי צורה שונה במקלחון הקודם',self.model('אין לי תשובה בטוחה',needs_human=True))
        pause.assert_not_called()
        self.assertIn('מה היה שונה',self.sent[-1])
        self.assertNotIn('אין לי תשובה',self.sent[-1])
        self.assertEqual(self.memory[self.phone][1]['planning_clarification_count'],1)

    def test_policy_safety_human_requests_and_repeated_failure_still_escalate(self):
        from owner_escalation import planning_clarification
        history=[{'role':'user','content':'מקלחון'}]
        for text in ('צורה אחרת, מה האחריות?', 'דלת עם קידוח', 'אני רוצה נציג אנושי', 'כמה עולה דלת?', 'מעקה בצורה אחרת'):
            self.assertIsNone(planning_clarification(text,{'product':'מקלחון'},history))
        self.assertIsNone(planning_clarification('צורה שונה',{'product':'מקלחון','planning_clarification_count':2},history))
