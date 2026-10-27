import os,unittest
from unittest.mock import patch,MagicMock
os.environ.setdefault('OPENAI_API_KEY','sk-offline-test-only')
import app as yossi
import business_pilot
ENV={'BUSINESS_PILOT_ID':'test-three','BUSINESS_PILOT_START_AT':'2026-10-27T09:45:44Z','BUSINESS_PILOT_LIMIT':'3'}
class FinitePilotTests(unittest.TestCase):
    def test_configuration_is_off_by_default_and_never_allows_more_than_three(self):
        self.assertIsNone(business_pilot.configuration({}))
        self.assertEqual(business_pilot.configuration(ENV)[2],3)
        for key,value in [('BUSINESS_PILOT_LIMIT','4'),('BUSINESS_PILOT_LIMIT','0'),('BUSINESS_PILOT_START_AT','2026-10-27T09:45:44')]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):business_pilot.configuration(dict(ENV,**{key:value}))
    def test_pilot_membership_overrides_accidental_global_enable_and_fails_closed(self):
        with patch.dict(os.environ,ENV),patch.object(yossi,'BUSINESS_AUTO_REPLY_ENABLED',True),patch.object(yossi,'BUSINESS_REPLY_TEST_SENDERS',frozenset()),patch.object(yossi,'ensure_db'),patch.object(yossi,'db_connection',return_value=MagicMock()),patch('business_pilot.allows',return_value=False):
            self.assertFalse(yossi.business_auto_reply_allowed('972501234567'))
        with patch.dict(os.environ,dict(ENV,BUSINESS_PILOT_LIMIT='99')),patch.object(yossi,'BUSINESS_AUTO_REPLY_ENABLED',True):
            self.assertFalse(yossi.business_auto_reply_allowed('972501234567'))
    def test_signed_verified_inbound_is_queued_only_when_a_slot_is_admitted(self):
        from tests.test_verified_inbound_gate import VerifiedInboundGateTests
        harness=VerifiedInboundGateTests();harness.setUp()
        for admitted in [True,False]:
            with self.subTest(admitted=admitted),patch.object(yossi,'HANDOFF_ENABLED',False),patch.object(yossi,'ensure_worker_started'),patch.object(yossi,'business_auto_reply_allowed',return_value=False),patch.object(yossi,'finite_business_pilot_requested',return_value=True),patch.object(yossi,'clear_simulation_for_business_inbound'),patch.object(yossi,'verified_business_lead',return_value=True),patch.object(yossi,'admit_business_pilot',return_value=admitted) as admit,patch.object(yossi,'queue_message') as queue,patch.object(yossi,'send_whatsapp') as send:
                self.assertEqual(harness.signed_post().status_code,200)
                admit.assert_called_once()
                self.assertEqual(queue.call_count,1 if admitted else 0)
                send.assert_not_called()
    def test_unverified_sender_never_claims_a_slot(self):
        from tests.test_verified_inbound_gate import VerifiedInboundGateTests
        harness=VerifiedInboundGateTests();harness.setUp()
        with patch.object(yossi,'HANDOFF_ENABLED',False),patch.object(yossi,'ensure_worker_started'),patch.object(yossi,'business_auto_reply_allowed',return_value=False),patch.object(yossi,'finite_business_pilot_requested',return_value=True),patch.object(yossi,'clear_simulation_for_business_inbound'),patch.object(yossi,'verified_business_lead',return_value=False),patch.object(yossi,'admit_business_pilot') as admit,patch.object(yossi,'queue_message') as queue:
            self.assertEqual(harness.signed_post().status_code,200)
            admit.assert_not_called();queue.assert_not_called()
    def test_test_senders_do_not_consume_live_slots(self):
        with patch.object(yossi,'BUSINESS_REPLY_TEST_SENDERS',frozenset({'972501234567'})),patch('business_pilot.admit') as admit:
            self.assertTrue(yossi.admit_business_pilot('972501234567',{}));admit.assert_not_called()
