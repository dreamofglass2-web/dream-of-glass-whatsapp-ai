"""Real disposable PostgreSQL only; external HTTP is fully mocked."""
import os,unittest
from datetime import datetime,timezone
from unittest.mock import MagicMock,patch
import psycopg2
import whatsapp_delivery as delivery


def connect():
    return psycopg2.connect(os.environ['DATABASE_URL'],sslmode='disable',connect_timeout=5)

class DeliveryPostgres(unittest.TestCase):
    def setUp(self):
        self.phone='972501234567'
        with connect() as db,db.cursor() as cur:
            delivery.ensure_tables(cur)
            cur.execute("DELETE FROM yossi_message_receipts WHERE message_id='wamid.disposable-delivery'")
            cur.execute("DELETE FROM yossi_delivery_probes WHERE id='disposable-delivery-probe'")
        self.addCleanup(self.cleanup)
    def cleanup(self):
        with connect() as db,db.cursor() as cur:
            cur.execute("DELETE FROM yossi_message_receipts WHERE message_id='wamid.disposable-delivery'")
            cur.execute("DELETE FROM yossi_delivery_probes WHERE id='disposable-delivery-probe'")
    def test_receipts_idempotent_out_of_order_and_phone_collision_rejected(self):
        now=datetime.now(timezone.utc)
        with connect() as db,db.cursor() as cur:
            for status in ('read','delivered','sent','read'):
                delivery.record(cur,[('wamid.disposable-delivery',self.phone,status,now,[])])
            delivery.record(cur,[('wamid.disposable-delivery','972509999999','read',now,[999])])
            cur.execute("SELECT status,phone,error_codes FROM yossi_message_receipts WHERE message_id='wamid.disposable-delivery'")
            rows=cur.fetchall();self.assertEqual(len(rows),3)
            self.assertTrue(all(r[1]==self.phone and r[2]==[] for r in rows))
    def test_committed_probe_reservation_blocks_restart_duplicate(self):
        http=MagicMock();http.get.return_value.status_code=200
        http.get.return_value.json.return_value={'display_phone_number':'+972508554415'}
        http.post.return_value.status_code=200;http.post.return_value.json.return_value={'messages':[{'id':'wamid.disposable-delivery'}]}
        env={'WHATSAPP_DELIVERY_PROBE_ID':'disposable-delivery-probe','WHATSAPP_DELIVERY_PROBE_PHONE':self.phone}
        with patch.object(delivery.form_outreach,'approval_ready',return_value=True):
            for _ in range(2):
                delivery.dispatch_probe(connect,http,'offline-token','456765487527572',lambda:True,MagicMock(),env=env)
        self.assertEqual(http.post.call_count,1)
        with connect() as db,db.cursor() as cur:
            cur.execute("SELECT state,message_id FROM yossi_delivery_probes WHERE id='disposable-delivery-probe'")
            self.assertEqual(cur.fetchone(),('accepted','wamid.disposable-delivery'))
