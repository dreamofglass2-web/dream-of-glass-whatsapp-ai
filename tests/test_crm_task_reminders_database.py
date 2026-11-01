import os,unittest,uuid
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock,patch
import psycopg2
import crm_task_reminders as r

def connect():return psycopg2.connect(os.environ['DATABASE_URL'],sslmode='disable',connect_timeout=5)
class TaskReminderDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.key=uuid.uuid4().hex;self.item={'key':self.key,'id':'task-test','customerId':'source-test','due':'2026-11-01'}
        self.cfg=patch.object(r,'configuration',return_value=(b'k'*32,'fake-access','fake-bot','123'));self.cfg.start();self.addCleanup(self.cfg.stop)
        self.feed=patch.object(r,'read_feed',return_value=[self.item]);self.feed.start();self.addCleanup(self.feed.stop)
        self.http=Mock();self.http.post.return_value.ok=True;self.http.post.return_value.json.return_value={'ok':True,'result':{'message_id':12,'chat':{'id':123}}}
        self.addCleanup(self.cleanup)
    def cleanup(self):
        with connect() as db,db.cursor() as cur:cur.execute('DELETE FROM crm_task_notifications WHERE task_key=%s',(self.key,))
    def send(self):return r.dispatch(connect,self.http,Mock(),datetime(2026,11,1,8,tzinfo=timezone.utc))
    def test_restart_and_concurrent_claims_send_only_one_owner_message(self):
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.send(),range(2)))
        self.assertEqual(sum(results),1);self.assertEqual(self.send(),0);self.http.post.assert_called_once()
        payload=self.http.post.call_args.kwargs['json'];self.assertEqual(payload['chat_id'],'123');self.assertNotIn('phone',payload['text'])
    def test_timeout_remains_uncertain_and_never_blindly_retries(self):
        self.http.post.side_effect=TimeoutError();self.assertEqual(self.send(),0);self.assertEqual(self.send(),0);self.http.post.assert_called_once()
        with connect() as db,db.cursor() as cur:cur.execute('SELECT status FROM crm_task_notifications WHERE task_key=%s',(self.key,));self.assertEqual(cur.fetchone()[0],'uncertain')
    def test_completed_source_task_is_not_sent(self):
        with patch.object(r,'read_feed',return_value=[]):self.assertEqual(self.send(),0);self.http.post.assert_not_called()
