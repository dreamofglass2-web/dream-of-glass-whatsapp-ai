import unittest
from mirror_policy import curved_mirror,curved_frame_request,guard_mirror_frame,FRAME_POLICY
class MirrorPolicyTests(unittest.TestCase):
    def history(self,text):return [{'role':'user','content':text}]
    def test_curved_customer_shapes_and_diameter_do_not_allow_frame(self):
        for shape in ['עגולה','אובלית','צורתית','אסימטרית','קוטר 60']:
            h=self.history('אני רוצה מראה '+shape+' עם מסגרת')
            self.assertTrue(curved_frame_request(h[0]['content'],h,'מראה'))
    def test_straight_and_corrected_shape_allow_frame(self):
        for shape in ['ישרה','מלבנית','מרובעת']:
            h=self.history('מראה עגולה')+self.history('בעצם מראה '+shape+' עם מסגרת')
            self.assertFalse(curved_frame_request(h[-1]['content'],h,'מראה'))
            self.assertEqual(guard_mirror_frame('אפשר עם מסגרת שחורה.',h,'מראה'),'אפשר עם מסגרת שחורה.')
    def test_known_diameter_does_not_get_a_frame_suggestion(self):
        h=self.history('מראה קוטר 60')
        answer=guard_mirror_frame('למראה יפה הייתי מציע לשקול מסגרת דקה. איפה בבית היא מיועדת להתקנה?',h,'מראה')
        self.assertIn(FRAME_POLICY,answer);self.assertIn('איפה בבית',answer);self.assertNotIn('מסגרת דקה',answer)
    def test_frameless_led_is_not_blocked(self):
        h=self.history('מראה עגולה')
        self.assertFalse(curved_frame_request('ללא מסגרת עם תאורה',h,'מראה'))
        self.assertEqual(guard_mirror_frame('אפשר עם תאורת לד ללא מסגרת.',h,'מראה'),'אפשר עם תאורת לד ללא מסגרת.')
    def test_assistant_shape_and_other_product_are_not_customer_evidence(self):
        self.assertFalse(curved_mirror([{'role':'assistant','content':'מראה עגולה'}],'מראה'))
        self.assertFalse(curved_mirror(self.history('מקלחון עגול'),'מקלחון'))
    def test_actual_process_routes_invalid_frame_before_model_and_without_quote(self):
        from tests.test_owner_requests import OwnerRequestTests
        harness=OwnerRequestTests()
        send,save,callback,work,pause,ai=harness.run_turn('אני צריך מראה עגולה עם מסגרת שחורה')
        self.assertIn(FRAME_POLICY,send.call_args.kwargs['body'])
        ai.assert_not_called();work.assert_not_called();pause.assert_not_called()
