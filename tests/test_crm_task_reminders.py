import unittest,json,hmac,hashlib
from datetime import datetime,timezone
from unittest.mock import Mock,patch
import crm_task_reminders as r
class TaskReminderTests(unittest.TestCase):
    def test_disabled_and_before_eight_never_touch_data_or_provider(self):
        for cfg,now in [(None,datetime(2026,11,1,10,tzinfo=timezone.utc)),((b'k'*32,'site-access','fake-bot','123'),datetime(2026,11,1,5,59,tzinfo=timezone.utc))]:
            with patch.object(r,'configuration',return_value=cfg):
                db,http=Mock(),Mock();self.assertEqual(r.dispatch(db,http,Mock(),now),0);db.assert_not_called();http.get.assert_not_called();http.post.assert_not_called()
    def test_feed_is_signed_fresh_scoped_and_rejects_future_or_tampered_data(self):
        key=b'k'*32;now=datetime(2026,11,1,7,tzinfo=timezone.utc)
        def response(url,**kw):
            self.assertEqual(url,r.SITE+r.TARGET);self.assertFalse(kw['allow_redirects'])
            self.assertEqual(kw['headers']['OAI-Sites-Authorization'],'Bearer fake-access')
            nonce=kw['headers']['X-CRM-Nonce'];data={'source_scope':'crm-task-reminders-v1','request_nonce':nonce,'generated_at':now.isoformat(),'items':[{'id':'task-test','customerId':'source-test','due':self.due}]}
            raw=json.dumps(data).encode();resp=Mock(status_code=200,content=raw)
            sig='sha256='+hmac.new(key,b'response\n'+nonce.encode()+b'\n'+raw,hashlib.sha256).hexdigest()
            resp.headers={'X-CRM-Response-Signature':sig if not self.tamper else 'sha256='+'0'*64};return resp
        http=Mock();http.get.side_effect=response;self.due='2026-11-01';self.tamper=False
        self.assertEqual(len(r.read_feed(http,key,'fake-access',now)),1)
        self.due='2026-11-02'
        with self.assertRaises(ValueError):r.read_feed(http,key,'fake-access',now)
        self.due='2026-11-01';self.tamper=True
        with self.assertRaises(ValueError):r.read_feed(http,key,'fake-access',now)
