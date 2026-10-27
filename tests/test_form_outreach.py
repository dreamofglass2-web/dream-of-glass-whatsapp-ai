import unittest
from unittest.mock import Mock, patch
import form_outreach as f

ENV={'BUSINESS_PILOT_ID':'unit-test','BUSINESS_PILOT_START_AT':'2026-10-27T09:45:44Z','BUSINESS_PILOT_LIMIT':'3','FORM_OUTREACH_ENABLED':'true','FORM_OUTREACH_FORM_IDS':'123'}
class FormOpeningTests(unittest.TestCase):
    def test_off_by_default_and_requires_finite_pilot_and_verified_forms(self):
        self.assertIsNone(f.configuration({}))
        for changed in ({'BUSINESS_PILOT_ID':''},{'BUSINESS_PILOT_LIMIT':'4'},{'FORM_OUTREACH_FORM_IDS':''},{'FORM_OUTREACH_FORM_IDS':'anything'}):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                f.configuration(dict(ENV,**changed))
    def test_only_exact_approved_hebrew_body_is_allowed(self):
        approved={'name':f.TEMPLATE,'language':'he','status':'APPROVED','components':[{'type':'BODY','text':f.BODY}]}
        http=Mock();http.get.return_value.json.return_value=approved
        self.assertTrue(f.template_approved(http,'fake-token'))
        for changed in ({'status':'PENDING'},{'status':'REJECTED'},{'language':'en_US'},{'name':'other'},{'components':[{'type':'BODY','text':'changed'}]},{'components':[{'type':'BODY','text':f.BODY},{'type':'BUTTONS'}]}):
            http.get.return_value.json.return_value=dict(approved,**changed)
            self.assertFalse(f.template_approved(http,'fake-token'))
    def test_night_disabled_and_pending_never_touch_database_or_send(self):
        for enabled,hours,approved in [(False,True,True),(True,False,True),(True,True,False)]:
            with self.subTest(enabled=enabled,hours=hours,approved=approved),patch.dict('os.environ',dict(ENV,FORM_OUTREACH_ENABLED=str(enabled).lower()),clear=True),patch.object(f,'template_approved',return_value=approved):
                db,http=Mock(),Mock()
                self.assertFalse(f.dispatch(db,http,'fake','123',lambda:hours,Mock()))
                db.assert_not_called();http.post.assert_not_called()
