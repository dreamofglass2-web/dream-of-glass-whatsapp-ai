import unittest
from sales_items import item_context, save_item, combined_quote
from sales_visuals import handle_photo_request, handle_photos


class SeparateItemsTests(unittest.TestCase):
    def test_switch_restore_and_clear_pricing_state(self):
        first = dict(width_cm=80, second_width_cm=80, glass_type='גלינה קליר',
                     finish='שחור', handles=['ידית כפתור'], solution_agreed=True,
                     validated_quote={'issued': True, 'amount_ils_pre_vat': 2000})
        state = item_context(first, [{'role':'assistant','content':'נעבור למקלחון השני: מה רוחב הפתח?'},
                                    {'role':'user','content':'160'}], '160')
        self.assertEqual(state['active_sales_item'], '2')
        self.assertNotIn('width_cm', state)
        self.assertNotIn('validated_quote', state)
        state.update(width_cm=160, glass_type='אנטיסן ברונזה', finish='ברונזה')
        save_item(state)
        restored = item_context(state, [{'role':'user','content':'למקלחון הראשון'}], 'למקלחון הראשון')
        self.assertEqual(restored['width_cm'], 80)
        self.assertEqual(restored['glass_type'], 'גלינה קליר')
        self.assertEqual(restored['sales_items']['2']['width_cm'], 160)

    def test_combined_quote_uses_independent_calculator_calls_and_default_height(self):
        items = {'1': dict(width_cm=80, solution_agreed=True),
                 '2': dict(width_cm=160, height_cm=210, solution_agreed=True)}
        seen=[]
        reply=combined_quote({'sales_items':items}, [], 'תחשב מחיר לשניהם',
                             lambda s: seen.append(s) or s['width_cm']*20)
        self.assertIn('4,800', reply)
        self.assertEqual([s['height_cm'] for s in seen], [200,210])
        self.assertNotIn('height_cm', items['1'])
        items['1']['solution_agreed']=False
        reply=combined_quote({'sales_items':items}, [], 'תחשב מחיר לשניהם',lambda _:2000)
        self.assertIn('אין עדיין סכום כולל',reply)
        self.assertIsNone(combined_quote({'sales_items':items}, [], 'תודה',lambda _:2000))

    def test_handle_request_uses_current_question_and_declared_catalog_identity(self):
        history=[{'role':'assistant','content':'ידית כפתור או מגבת?'},
                 {'role':'user','content':'יש לך דוגמה?'}]
        self.assertTrue(handle_photo_request('יש לך דוגמה?',history))
        self.assertFalse(handle_photo_request('בלי תמונות',history))
        catalog=[{'url':'button','product':'מקלחון','handle':'כפתור'},
                 {'url':'towel','product':'מקלחון','handle':'מגבת'},
                 {'url':'unknown','product':'מקלחון'}]
        photos=handle_photos(catalog,'תמונה של ידית מגבת',{})
        self.assertEqual([p['url'] for p in photos],['towel'])
        self.assertIn('ידית מגבת',photos[0]['caption'])
        self.assertEqual(handle_photos([catalog[-1]],'ידיות',{}),[])


class BathHeightBasisTests(unittest.TestCase):
    def test_mixed_order_uses_independent_bath_and_shower_heights(self):
        from sales_items import bundle_offer, preliminary_height, bundle_offer_reply
        specs={'1':dict(product='אמבטיון',configuration='אמבטיון 2 קבועים + דלת',solution_agreed=True,width_cm=181),
               '2':dict(product='מקלחון',configuration='חזית קבוע + דלת',solution_agreed=True,width_cm=100)}
        seen=[]
        offer=bundle_offer({'sales_items':specs},lambda s:seen.append(s) or s['height_cm'])
        self.assertEqual([s['height_cm'] for s in seen],[140,200])
        self.assertEqual(preliminary_height(dict(product='אמבטיון',height_cm=155)),155)
        self.assertNotIn('height_cm',specs['1'])
        self.assertIn('140',bundle_offer_reply(offer))


    def test_panel_count_is_not_a_second_shower(self):
        from sales_items import numbered_item
        self.assertIsNone(numbered_item('שני קבועים ודלת באמצע'))
        self.assertIsNone(numbered_item('שני מקלחונים'))
        self.assertEqual(numbered_item('למקלחון השני'),'2')
