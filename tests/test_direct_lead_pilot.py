import os, unittest
from unittest.mock import patch, Mock
os.environ.setdefault('OPENAI_API_KEY','sk-offline-test-only')
import app as yossi

class DirectLeadPilotTests(unittest.TestCase):
    def test_direct_leads_remain_disabled_without_explicit_switch(self):
        with patch.dict(os.environ,{'BUSINESS_PILOT_ALL_INBOUND':'false'}),patch.object(yossi,'db_connection') as db:
            self.assertFalse(yossi.persist_verified_direct_inbound('972501234567',{'timestamp':'1793149200'}));db.assert_not_called()
    def test_unsigned_and_wrong_recipient_never_establish_direct_provenance(self):
        from tests.test_verified_inbound_gate import VerifiedInboundGateTests
        harness=VerifiedInboundGateTests();harness.setUp()
        with patch.object(yossi,'persist_verified_direct_inbound') as persist,patch.object(yossi,'APP_SECRET','fake-secret'),patch.object(yossi,'ensure_worker_started'):
            self.assertEqual(harness.client.post('/webhook',json=harness.payload).status_code,403)
            harness.payload['entry'][0]['changes'][0]['value']['metadata']['phone_number_id']='another-recipient'
            self.assertEqual(harness.signed_post().status_code,200);persist.assert_not_called()
    def test_signed_direct_message_uses_shared_pilot_and_queues_without_sending(self):
        from tests.test_verified_inbound_gate import VerifiedInboundGateTests
        harness=VerifiedInboundGateTests();harness.setUp()
        with patch.object(yossi,'HANDOFF_ENABLED',False),patch.object(yossi,'ensure_worker_started'),patch.object(yossi,'finite_business_pilot_requested',return_value=True),patch.object(yossi,'business_auto_reply_allowed',return_value=False),patch.object(yossi,'clear_simulation_for_business_inbound'),patch.object(yossi,'persist_verified_direct_inbound',return_value=True) as provenance,patch.object(yossi,'verified_business_lead',return_value=True),patch.object(yossi,'admit_business_pilot',return_value=True) as admit,patch.object(yossi,'queue_message') as queue,patch.object(yossi,'send_whatsapp') as send:
            self.assertEqual(harness.signed_post().status_code,200)
            provenance.assert_called_once();admit.assert_called_once();queue.assert_called_once();send.assert_not_called()
