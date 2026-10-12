import os, unittest, hmac, hashlib, json
from unittest.mock import patch
os.environ.setdefault('OPENAI_API_KEY','sk-offline-test-only')
import app as yossi


class ControlAuthenticationTests(unittest.TestCase):
    def test_disabled_and_unsigned_requests_never_read_database(self):
        with patch.object(yossi,'HANDOFF_ENABLED',False), patch.object(yossi,'db_connection') as db:
            self.assertEqual(yossi.app.test_client().get('/v1/handoff').status_code,503)
            db.assert_not_called()
        with patch.object(yossi,'HANDOFF_ENABLED',True), patch.dict(os.environ,{'CRM_CONTROL_KEY_HEX':'19'*32}), patch.object(yossi,'db_connection') as db:
            self.assertEqual(yossi.app.test_client().get('/v1/handoff').status_code,401)
            db.assert_not_called()

    def test_modified_signed_body_and_replayed_old_timestamp_are_rejected(self):
        import time
        key=bytes.fromhex('19'*32);raw=json.dumps({'phone':'972501234567','expectedRevision':0,'action':{'type':'takeover'}}).encode()
        for stamp,body in [(str(int(time.time())),raw+b' '),(str(int(time.time())-301),raw)]:
            nonce='a'*32;canonical='\n'.join(['POST','/v1/handoff',stamp,nonce,hashlib.sha256(raw).hexdigest()]).encode()
            headers={'X-CRM-Timestamp':stamp,'X-CRM-Nonce':nonce,'X-CRM-Signature':'sha256='+hmac.new(key,canonical,hashlib.sha256).hexdigest()}
            with patch.object(yossi,'HANDOFF_ENABLED',True),patch.dict(os.environ,{'CRM_CONTROL_KEY_HEX':'19'*32}),patch.object(yossi,'db_connection') as db:
                response=yossi.app.test_client().post('/v1/handoff',data=body,content_type='application/json',headers=headers)
                self.assertEqual(response.status_code,401);db.assert_not_called()
