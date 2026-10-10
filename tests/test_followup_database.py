"""Disposable PostgreSQL integration tests for followup SQL. Never contacts customers."""
import os
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test-only")
import psycopg2
import app as yossi


def test_connection():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="disable", connect_timeout=5)


class FollowupPostgresIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection_patcher = patch.object(yossi, "db_connection", side_effect=test_connection)
        cls.connection_patcher.start()
        yossi.ensure_db()
        yossi.ensure_followup_table()
        yossi.ensure_inbound_queue_table()

    @classmethod
    def tearDownClass(cls):
        with test_connection() as db:
            with db.cursor() as cur:
                cur.execute("DELETE FROM yossi_followup_jobs WHERE phone LIKE 'TEST_FOLLOWUP_%'")
                cur.execute("DELETE FROM yossi_inbound_queue WHERE starts_with(phone, 'TEST_FOLLOWUP_')")
                cur.execute("DELETE FROM glass_leads WHERE phone LIKE 'TEST_FOLLOWUP_%'")
        cls.connection_patcher.stop()

    def test_inbound_timestamp_in_disposable_database(self):
        """Verified inbound time persists, advances and does not send WhatsApp."""
        from datetime import datetime, timedelta, timezone
        phone = "TEST_FOLLOWUP_INBOUND"
        with patch.object(yossi, "send_whatsapp") as send:
            self.assertTrue(yossi.record_customer_inbound(phone))
            with test_connection() as db:
                with db.cursor() as cur:
                    cur.execute("SELECT last_inbound_at FROM glass_leads WHERE phone=%s", (phone,))
                    first = cur.fetchone()[0]
                    self.assertIsNotNone(first)
                    self.assertLess(datetime.now(timezone.utc) - first, timedelta(minutes=2))
            self.assertTrue(yossi.record_customer_inbound(phone))
            with test_connection() as db:
                with db.cursor() as cur:
                    cur.execute("SELECT count(*), max(last_inbound_at) FROM glass_leads WHERE phone=%s", (phone,))
                    count, second = cur.fetchone()
                    self.assertEqual(count, 1)
                    self.assertGreaterEqual(second, first)
            send.assert_not_called()

    def test_inbound_queue_survives_restart_and_is_deduplicated(self):
        import time
        phone = "TEST_FOLLOWUP_QUEUE"
        mid = "TEST_FOLLOWUP_MESSAGE_A"
        with patch.object(yossi, 'send_whatsapp') as sender:
            self.assertTrue(yossi.persist_inbound_message(phone, "ערב טוב", mid))
            self.assertFalse(yossi.persist_inbound_message(phone, "ערב טוב", mid))
            with test_connection() as db:
                with db.cursor() as cur:
                    cur.execute("SELECT count(*) FROM yossi_inbound_queue WHERE message_id=%s", (mid,))
                    self.assertEqual(cur.fetchone()[0], 1)
                    cur.execute("SELECT last_inbound_at FROM glass_leads WHERE phone=%s", (phone,))
                    self.assertIsNotNone(cur.fetchone()[0])
            with yossi.lock:
                old_queue = yossi.pending
                old_seen = yossi.seen
                yossi.pending = {}
                yossi.seen = {}
            try:
                yossi.restore_inbound_queue()
                with yossi.lock:
                    recovered = [r for r in yossi.pending[phone] if r[0] == mid]
                self.assertEqual(len(recovered), 1)
                yossi.remove_processed_inbound_messages(phone, recovered)
                with test_connection() as db:
                    with db.cursor() as cur:
                        cur.execute("SELECT count(*) FROM yossi_inbound_queue WHERE message_id=%s", (mid,))
                        self.assertEqual(cur.fetchone()[0], 0)
            finally:
                with yossi.lock:
                    yossi.pending = old_queue
                    yossi.seen = old_seen
            sender.assert_not_called()

    def test_weekend_messages_wait_and_stale_whatsapp_window_is_blocked(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        clock = ZoneInfo("Asia/Jerusalem")
        phone = "TEST_FOLLOWUP_STALE"
        with yossi.lock:
            old_pending = yossi.pending
            old_processing = yossi.processing
            yossi.pending = {
                phone: [("stale-id", "שישי שלום", yossi.time.monotonic()-48*3600)]
            }
            yossi.processing = set()
        try:
            with patch.object(yossi, 'is_yossi_business_hours', return_value=False):
                self.assertIsNone(yossi.next_batch())
            with patch.object(yossi, 'is_yossi_business_hours', return_value=True):
                self.assertIsNone(yossi.next_batch())
        finally:
            with yossi.lock:
                yossi.pending = old_pending
                yossi.processing = old_processing

    def test_persist_reschedule_and_cancel(self):
        phone = "TEST_FOLLOWUP_ELIGIBLE"
        with test_connection() as db:
            with db.cursor() as cur:
                cur.execute("INSERT INTO glass_leads(phone,status) VALUES (%s,'חדש') ON CONFLICT(phone) DO UPDATE SET status='חדש'", (phone,))
        local = ZoneInfo("Asia/Jerusalem")
        with patch.object(yossi, "send_whatsapp") as send:
            yossi.schedule_followup_dry_run(phone, datetime(2026, 10, 12, 10, tzinfo=local))
            with test_connection() as db:
                with db.cursor() as cur:
                    cur.execute("SELECT status, due_at FROM yossi_followup_jobs WHERE phone=%s", (phone,))
                    status, due = cur.fetchone()
                    self.assertEqual(status, "pending")
                    self.assertEqual(due.astimezone(local).hour, 14)
            yossi.schedule_followup_dry_run(phone, datetime(2026, 10, 12, 18, tzinfo=local))
            with test_connection() as db:
                with db.cursor() as cur:
                    cur.execute("SELECT count(*), max(due_at) FROM yossi_followup_jobs WHERE phone=%s", (phone,))
                    count, due = cur.fetchone()
                    self.assertEqual(count, 1)
                    self.assertEqual(due.astimezone(local).strftime("%Y-%m-%d %H:%M"), "2026-10-13 08:00")
            yossi.cancel_followup_dry_run(phone)
            with test_connection() as db:
                with db.cursor() as cur:
                    cur.execute("SELECT status FROM yossi_followup_jobs WHERE phone=%s", (phone,))
                    self.assertEqual(cur.fetchone()[0], "cancelled")
            send.assert_not_called()

    def test_no_followup_after_optout_or_owner_handoff(self):
        cases = [
            ("TEST_FOLLOWUP_OPTOUT", "חדש", '{"no_followups":true}'),
            ("TEST_FOLLOWUP_OWNER", "ממתין לחזרה", '{}'),
            ("TEST_FOLLOWUP_CUSTOM", "ממתין לתמחור", '{}'),
        ]
        with test_connection() as db:
            with db.cursor() as cur:
                for phone, status, context in cases:
                    cur.execute("""
                        INSERT INTO glass_leads(phone,status,context)
                        VALUES (%s,%s,%s::jsonb)
                        ON CONFLICT(phone) DO UPDATE SET
                          status=EXCLUDED.status, context=EXCLUDED.context
                    """, (phone,status,context))
        for phone, _, _ in cases:
            yossi.schedule_followup_dry_run(phone)
        with test_connection() as db:
            with db.cursor() as cur:
                cur.execute("SELECT count(*) FROM yossi_followup_jobs WHERE starts_with(phone, 'TEST_FOLLOWUP_') AND phone<>%s", ("TEST_FOLLOWUP_ELIGIBLE",))
                self.assertEqual(cur.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
