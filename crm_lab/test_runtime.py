import unittest
from crm_lab.runtime import configuration
class RuntimeTests(unittest.TestCase):
    def fixture(self):return {'CRM_LIVE_READ_ENABLED':'true','CRM_BRIDGE_KEY_HEX':'a'*64,
        'CRM_READER_DATABASE_URL':'postgresql://yossi_crm_reader:explicit-test-password@db.example/crm_db','CRM_REPLAY_PATH':'/var/data/replay.sqlite'}
    def test_explicit_config_uses_only_reader_with_verified_tls(self):
        params,key,path=configuration(self.fixture());self.assertEqual(params['user'],'yossi_crm_reader');self.assertEqual(params['sslmode'],'verify-full');self.assertEqual(len(key),32)
    def test_missing_or_privileged_config_fails_before_connection(self):
        for field,value in [('CRM_LIVE_READ_ENABLED','false'),('CRM_BRIDGE_KEY_HEX','short'),('CRM_READER_DATABASE_URL','postgresql://admin:password@db.example/crm'),('CRM_REPLAY_PATH','/tmp/replay.sqlite')]:
            config=self.fixture();config[field]=value
            with self.assertRaises(ValueError):configuration(config)
