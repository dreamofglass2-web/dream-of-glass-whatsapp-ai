import unittest
from sales_visuals import implicit_visual_request, consultation_photos, consultation_photo_intro


class IllustrationTests(unittest.TestCase):
    def test_visual_difficulty_is_a_request(self):
        for text in ('קשה לי לדמיין איך זה ייראה', 'אני לא מצליח לדמיין',
                     'אני לא מבינה איך זה נראה', 'צריך לראות איך זה ייראה'):
            with self.subTest(text=text):
                self.assertTrue(implicit_visual_request(text))

    def test_confusion_or_refusal_does_not_send_unsolicited_media(self):
        for text in ('אני לא מבין במחיר', 'לא רוצה תמונות, קשה לי לדמיין אבל תסביר',
                     'אין לי תמונה', 'לא שלחתי תמונה', 'חשוב לי לנקות'):
            with self.subTest(text=text):
                self.assertFalse(implicit_visual_request(text))

    def test_layout_match_is_preferred_and_honestly_identified(self):
        catalog = [
            dict(url='https://example.test/corner', product='מקלחון', glass='שקופה', configuration='פינתי'),
            dict(url='https://example.test/front', product='מקלחון', glass='שקופה', configuration='חזית קבוע + דלת'),
            dict(url='https://example.test/mirror', product='מראה', glass='שקופה', configuration='חזית קבוע + דלת'),
        ]
        context = dict(product='מקלחון', configuration='חזית קבוע + דלת', glass_type='שקופה')
        selected = consultation_photos(catalog, context, 1)
        self.assertEqual(selected[0]['url'], 'https://example.test/front')
        self.assertIn('חזית קבוע + דלת', consultation_photo_intro(selected, context))
        self.assertIn('נבדוק בנפרד', consultation_photo_intro(selected, context))

    def test_mismatch_is_not_presented_as_the_proposed_layout(self):
        photos = [dict(url='https://example.test/a', product='מקלחון', glass='שקופה', configuration='פינתי')]
        intro = consultation_photo_intro(photos, dict(configuration='חזית קבוע + דלת'))
        self.assertIn('יכולים להיות שונים', intro)
        self.assertNotIn('לתצורה חזית', intro)

    def test_empty_product_match_does_not_send_another_product(self):
        self.assertEqual(consultation_photos([dict(url='x', product='מראה')], dict(product='מקלחון')), [])

    def test_catalog_duplicates_are_not_sent_twice(self):
        item = dict(url='x', product='מקלחון', glass='שקופה', configuration='חזית')
        self.assertEqual(len(consultation_photos([item,item], dict(product='מקלחון'))), 1)


class CatalogHandleExamplesTests(unittest.TestCase):
    def test_explicit_handle_tags_do_not_depend_on_singular_product_label(self):
        from sales_visuals import handle_photos
        for product in ('מקלחונים', 'אמבטיון', ''):
            with self.subTest(product=product):
                catalog = [{'url':'https://example.test/button', 'product':product, 'handles':['ידית כפתור']},
                           {'url':'https://example.test/towel', 'product':product, 'handle_type':'ידית מגבת'}]
                photos = handle_photos(catalog, 'כפתור יש לך דוגמאות?', {}, '', '')
                self.assertEqual([p['url'] for p in photos], ['https://example.test/button'])
                self.assertIn('כפתור', photos[0]['caption'])
                self.assertNotIn('מגבת', photos[0]['caption'])
                self.assertEqual(handle_photos(catalog, 'מגבת', {})[0]['url'], 'https://example.test/towel')

    def test_unlabelled_photo_is_not_invented_as_a_handle_example(self):
        from sales_visuals import handle_photos
        self.assertEqual(handle_photos([{'url':'x', 'product':'מקלחון', 'configuration':'קבוע ודלת'}], 'כפתור', {}), [])
