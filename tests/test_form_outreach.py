import unittest
from unittest.mock import Mock, patch
import form_outreach as f

ENV={'BUSINESS_PILOT_ID':'unit-test','BUSINESS_PILOT_START_AT':'2026-10-27T09:45:44Z','BUSINESS_PILOT_LIMIT':'3','FORM_OUTREACH_ENABLED':'true','FORM_OUTREACH_FORM_IDS':'123'}
class FormOpeningTests(unittest.TestCase):
    def test_off_by_default_and_requires_finite_pilot_and_verified_forms(self):
        self.assertIsNone(f.configuration({}))
        for changed in ({'BUSINESS_PILOT_ID':''},{'BUSINESS_PILOT_LIMIT':'6'},{'FORM_OUTREACH_FORM_IDS':''},{'FORM_OUTREACH_FORM_IDS':'anything'}):
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
        for enabled,hours,approved in [(False,True,True),(True,False,True)]:
            with self.subTest(enabled=enabled,hours=hours,approved=approved),patch.dict('os.environ',dict(ENV,FORM_OUTREACH_ENABLED=str(enabled).lower()),clear=True),patch.object(f,'template_approved',return_value=approved):
                db,http=Mock(),Mock()
                self.assertFalse(f.dispatch(db,http,'fake',f.BUSINESS_NUMBER_ID,lambda:hours,Mock()))
                db.assert_not_called();http.post.assert_not_called()

    def test_all_forms_is_explicit_and_production_number_is_required(self):
        self.assertEqual(f.configuration(dict(ENV,FORM_OUTREACH_FORM_IDS='*'))[1],['*'])
        with patch.dict('os.environ',ENV,clear=True),patch.object(f,'template_approved') as approval:
            http,db=Mock(),Mock()
            self.assertFalse(f.dispatch(db,http,'fake','wrong-number',lambda:True,Mock()))
            approval.assert_not_called();http.post.assert_not_called();db.assert_not_called()

    def test_approval_failure_backs_off_and_never_logs_provider_body_or_credentials(self):
        import requests
        http=Mock();response=Mock();response.status_code=400
        response.json.return_value={'error':{'code':4,'error_subcode':99,'message':'sensitive-body'}}
        http.get.side_effect=requests.HTTPError('sensitive-url',response=response)
        logger=Mock()
        with patch.dict(f._approval_retry_after,{},clear=True),patch.object(f.time,'monotonic',side_effect=[10,20,311]):
            self.assertFalse(f.approval_ready(http,'fake-only-token',logger))
            self.assertFalse(f.approval_ready(http,'fake-only-token',logger))
            self.assertFalse(f.approval_ready(http,'fake-only-token',logger))
        self.assertEqual(http.get.call_count,2)
        self.assertNotIn('sensitive',str(logger.mock_calls));self.assertNotIn('fake-only-token',str(logger.mock_calls))
        self.assertIn('400',str(logger.mock_calls));self.assertIn('99',str(logger.mock_calls))
