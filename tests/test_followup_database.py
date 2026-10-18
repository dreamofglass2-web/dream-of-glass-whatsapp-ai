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
        yossi.ensure_outbound_attempts_table()

    @classmethod
    def tearDownClass(cls):
        with test_connection() as db:
            with db.cursor() as cur:
                cur.execute("DELETE FROM yossi_outbound_attempts WHERE phone LIKE 'TEST_FOLLOWUP_%'")
                cur.execute("DELETE FROM yossi_followup_jobs WHERE phone LIKE 'TEST_FOLLOWUP_%'")
                cur.execute("DELETE FROM yossi_inbound_queue WHERE starts_with(phone, 'TEST_FOLLOWUP_')")
                cur.execute("DELETE FROM glass_leads WHERE phone LIKE 'TEST_FOLLOWUP_%'")
        cls.connection_patcher.stop()

    def test_missing_photo_creates_durable_owner_request_and_telegram_job(self):
        import json
        import types
        from unittest.mock import Mock
        from owner_notifications import dispatch_owner_alerts
        phone = 'TEST_FOLLOWUP_MISSING_PHOTO'
        history = [{'role': 'assistant', 'content': 'מצרף תמונת ברונזה'}]
        context = {'product': 'אמבטיון', 'sales_discovery_completed': True}
        with test_connection() as db:
            with db.cursor() as cur:
                yossi.ensure_handoff_tables(cur)
                cur.execute("INSERT INTO glass_leads(phone, conversation, context, status) VALUES(%s,%s::jsonb,%s::jsonb,'ממתין לחזרה')",
                            (phone, json.dumps(history), json.dumps(context)))
        try:
            response = types.SimpleNamespace(output_text=json.dumps({
                'reply': 'שמרתי פנייה לאלירן', 'product': 'אמבטיון',
                'needs_human': False, 'quote_requested': False, 'action': 'reply'}))
            with patch.object(yossi, 'HANDOFF_ENABLED', True), patch.object(yossi, 'PHOTO_CATALOG', []), \
                 patch.object(yossi, 'GLASS_SAMPLE_IMAGES', {}), patch.object(yossi.time, 'sleep'), \
                 patch.object(yossi, 'has_new_messages', return_value=False), \
                 patch.object(yossi.client.responses, 'create', return_value=response), \
                 patch.object(yossi, 'send_whatsapp') as customer_send, \
                 patch.object(yossi, 'save_conversation') as stale_save:
                self.assertTrue(yossi.process_message(phone, 'הברונזה לא נשלח'))
                customer_send.assert_not_called()
                stale_save.assert_not_called()
            with test_connection() as db:
                with db.cursor() as cur:
                    state = yossi.read_handoff_state(cur, phone)
                    cur.execute('SELECT context,conversation FROM glass_leads WHERE phone=%s', (phone,))
                    saved_context, conversation = cur.fetchone()
            self.assertEqual(saved_context, context)
            self.assertEqual(conversation[-1]['content'], 'הברונזה לא נשלח')
            self.assertEqual(state['owner'], 'operator')
            self.assertTrue(state['escalation']['active'])
            self.assertEqual(state['escalation']['reason'], 'תמונה מבוקשת אינה זמינה בקטלוג')
            self.assertEqual(state['escalation']['notificationStatus'], 'not_configured')
            # This is the same signed control collection consumed by the CRM.
            import time, hmac, hashlib
            key = '19'*32
            stamp, nonce = str(int(time.time())), 'd'*32
            canonical = '\n'.join(['GET', '/v1/handoff', stamp, nonce, hashlib.sha256(b'').hexdigest()]).encode()
            headers = {'X-CRM-Timestamp': stamp, 'X-CRM-Nonce': nonce,
                       'X-CRM-Signature': 'sha256=' + hmac.new(bytes.fromhex(key), canonical, hashlib.sha256).hexdigest()}
            with patch.object(yossi, 'HANDOFF_ENABLED', True), patch.dict(os.environ, {'CRM_CONTROL_KEY_HEX': key}):
                result = yossi.app.test_client().get('/v1/handoff', headers=headers)
            self.assertEqual(result.status_code, 200)
            control = next(c for c in result.json['controls'] if c['phone'] == phone)
            self.assertTrue(control['escalation']['active'])
            self.assertEqual(control['owner'], 'operator')
            http = Mock()
            http.post.return_value.ok = True
            http.post.return_value.json.return_value = {'ok': True, 'result': {'message_id': 44, 'chat': {'id': 123456}}}
            config = {'OWNER_ALERT_ENABLED': 'true', 'OWNER_ALERT_CHANNEL': 'telegram',
                      'OWNER_TELEGRAM_BOT_TOKEN': '123456789:' + 'a'*35, 'OWNER_TELEGRAM_CHAT_ID': '123456'}
            with patch.dict(os.environ, config):
                dispatch_owner_alerts(test_connection, http, '', 'unused', Mock())
                dispatch_owner_alerts(test_connection, http, '', 'unused', Mock())
            http.post.assert_called_once()
            self.assertIn('CRM', http.post.call_args.kwargs['json']['text'])
            with test_connection() as db:
                with db.cursor() as cur:
                    self.assertEqual(yossi.read_handoff_state(cur, phone)['escalation']['notificationStatus'], 'accepted')
        finally:
            with test_connection() as db:
                with db.cursor() as cur:
                    cur.execute('DELETE FROM yossi_handoffs WHERE phone=%s', (phone,))
                    cur.execute('DELETE FROM glass_leads WHERE phone=%s', (phone,))
            yossi.histories.pop(phone, None)
            yossi.customer_context.pop(phone, None)

    def test_dialog_reset_preserves_channel_provenance_and_optouts(self):
        import json
        phone = '972500000999'
        protected = {'simulation_recipient_id': 'meta-test-number',
                     'meta_leads': {'test-lead': {'source': 'meta_instant_form'}},
                     'whatsapp_referral': {'source': 'meta_click_to_whatsapp_ad'},
                     'no_followups': True, 'no_phone_calls': True}
        try:
            with test_connection() as db:
                with db.cursor() as cur:
                    cur.execute("INSERT INTO glass_leads(phone,context,conversation,status,callback_time) "
                                "VALUES(%s,%s::jsonb,%s::jsonb,'ממתין לחזרה','מחר')",
                                (phone, json.dumps({**protected, 'validated_quote': {'issued': True}}),
                                 json.dumps([{'role':'user','content':'old dialogue'}])))
            with patch.object(yossi, 'SIMULATION_PHONE_NUMBER_ID', 'meta-test-number'), \
                 patch.object(yossi, 'SIMULATION_ALLOWED_SENDERS', frozenset({phone})):
                self.assertTrue(yossi.is_simulation_contact(phone))
                self.assertTrue(yossi.reset_conversation_for_phone(phone))
                self.assertTrue(yossi.is_simulation_contact(phone))
            with test_connection() as db:
                with db.cursor() as cur:
                    cur.execute("SELECT context,conversation,status,callback_time FROM glass_leads WHERE phone=%s", (phone,))
                    context, conversation, status, callback = cur.fetchone()
            self.assertEqual(context, protected)
            self.assertEqual(conversation, [])
            self.assertEqual(status, 'ממתין לחזרה')
            self.assertEqual(callback, 'מחר')
            self.assertEqual(yossi.customer_context[phone], protected)
        finally:
            with test_connection() as db:
                with db.cursor() as cur:
                    cur.execute("DELETE FROM glass_leads WHERE phone=%s", (phone,))

    def test_meta_provenance_gate_in_disposable_database(self):
        """A lead row alone cannot authorize outgoing customer messages."""
        import json
        cases = [
            ("TEST_FOLLOWUP_UNVERIFIED", {}, False),
            ("TEST_FOLLOWUP_VERIFIED", {"meta_leads": {"lead-1": {"source": "meta_instant_form"}}}, True),
            ("TEST_FOLLOWUP_WRONG_SOURCE", {"meta_leads": {"lead-2": {"source": "manual"}}}, False),
            ("TEST_FOLLOWUP_OPTOUT_SOURCE", {"meta_leads": {"lead-3": {"source": "meta_instant_form"}}, "no_followups": True}, False),
        ]
        # Authenticated lead must also have a valid Israeli mobile phone.
        with test_connection() as db:
            with db.cursor() as cur:
                for phone, context, _ in cases:
                    cur.execute("INSERT INTO glass_leads(phone, context) VALUES (%s,%s::jsonb) "
                                "ON CONFLICT(phone) DO UPDATE SET context=EXCLUDED.context",
                                (phone, json.dumps(context)))
        for phone, _, _ in cases:
            self.assertFalse(yossi.verified_business_lead(phone))
        real_phone = "972501234567"
        with test_connection() as db:
            with db.cursor() as cur:
                cur.execute("INSERT INTO glass_leads(phone, context) VALUES (%s,%s::jsonb) "
                            "ON CONFLICT(phone) DO UPDATE SET context=EXCLUDED.context",
                            (real_phone, json.dumps({"meta_leads": {"test": {"source": "meta_instant_form"}}})))
        try:
            self.assertTrue(yossi.verified_business_lead(real_phone))
            with test_connection() as db:
                with db.cursor() as cur:
                    cur.execute("UPDATE glass_leads SET context=jsonb_set(context, '{no_followups}', 'true'::jsonb) WHERE phone=%s", (real_phone,))
            self.assertFalse(yossi.verified_business_lead(real_phone))
            # Opt-out also overrides a signed click-to-WhatsApp ad referral.
            self.assertTrue(yossi.persist_verified_whatsapp_ad(
                real_phone, {"referral": {"source_type": "ad", "source_id": "test-ad-id"}}))
            self.assertFalse(yossi.verified_business_lead(real_phone))
            with test_connection() as db:
                with db.cursor() as cur:
                    cur.execute("UPDATE glass_leads SET context=context-'no_followups' "
                                "WHERE phone=%s", (real_phone,))
            self.assertTrue(yossi.verified_business_lead(real_phone))
        finally:
            with test_connection() as db:
                with db.cursor() as cur:
                    cur.execute("DELETE FROM glass_leads WHERE phone=%s", (real_phone,))

    def test_distributed_advisory_phone_claim(self):
        phone = "TEST_FOLLOWUP_LOCK"
        first = yossi.claim_phone_processing(phone)
        self.assertIsNotNone(first)
        try:
            self.assertIsNone(yossi.claim_phone_processing(phone))
        finally:
            first.close()
        second = yossi.claim_phone_processing(phone)
        self.assertIsNotNone(second)
        second.close()

    def test_outbound_retry_is_suppressed_after_success(self):
        from unittest.mock import Mock
        phone = "TEST_FOLLOWUP_OUTBOUND_OK"
        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        with patch.object(yossi, "BUSINESS_AUTO_REPLY_ENABLED", True), \
             patch.object(yossi, "verified_business_lead", return_value=True), \
             patch.object(yossi, "customer_freeform_send_allowed", return_value=True), \
             patch.object(yossi.requests, "post", return_value=response) as send, \
             patch.object(yossi, "schedule_followup_dry_run"):
            try:
                for _ in range(2):
                    yossi._delivery_scope.current = {"fingerprint": "TEST_FOLLOWUP_BATCH_OK",
                                                     "ordinal": 0}
                    yossi.send_whatsapp(phone, body="מענה בדיקה (לא נשלח ל-Meta)")
                self.assertEqual(send.call_count, 1)
                with test_connection() as db:
                    with db.cursor() as cur:
                        cur.execute("SELECT state FROM yossi_outbound_attempts WHERE phone=%s", (phone,))
                        self.assertEqual(cur.fetchone()[0], "sent")
            finally:
                yossi._delivery_scope.current = None

    def test_network_uncertainty_never_retries_outbound(self):
        phone = "TEST_FOLLOWUP_OUTBOUND_UNCERTAIN"
        with patch.object(yossi, "BUSINESS_AUTO_REPLY_ENABLED", True), \
             patch.object(yossi, "verified_business_lead", return_value=True), \
             patch.object(yossi, "customer_freeform_send_allowed", return_value=True), \
             patch.object(yossi.requests, "post", side_effect=OSError("simulated network")) as send, \
             patch.object(yossi, "schedule_followup_dry_run"):
            try:
                yossi._delivery_scope.current = {"fingerprint": "TEST_FOLLOWUP_BATCH_UNCERTAIN",
                                                 "ordinal": 0}
                with self.assertRaises(OSError):
                    yossi.send_whatsapp(phone, body="מענה בדיקה")
                yossi._delivery_scope.current = {"fingerprint": "TEST_FOLLOWUP_BATCH_UNCERTAIN",
                                                 "ordinal": 0}
                yossi.send_whatsapp(phone, body="מענה בדיקה")
                self.assertEqual(send.call_count, 1)
                with test_connection() as db:
                    with db.cursor() as cur:
                        cur.execute("SELECT state FROM yossi_outbound_attempts WHERE phone=%s", (phone,))
                        self.assertEqual(cur.fetchone()[0], "uncertain")
            finally:
                yossi._delivery_scope.current = None

    def test_send_boundary_checks_inbound_window_against_disposable_db(self):
        from datetime import timedelta, timezone
        phone = "TEST_FOLLOWUP_WINDOW"
        now = datetime.now(timezone.utc)
        with test_connection() as db:
            with db.cursor() as cur:
                cur.execute("""
                    INSERT INTO glass_leads(phone,last_inbound_at)
                    VALUES (%s,%s)
                    ON CONFLICT(phone) DO UPDATE SET last_inbound_at=EXCLUDED.last_inbound_at
                """, (phone, now - timedelta(hours=25)))
        self.assertFalse(yossi.customer_freeform_send_allowed(phone))
        with test_connection() as db:
            with db.cursor() as cur:
                cur.execute("UPDATE glass_leads SET last_inbound_at=%s WHERE phone=%s",
                            (now - timedelta(minutes=15), phone))
        self.assertTrue(yossi.customer_freeform_send_allowed(phone))

    def test_expired_window_never_calls_whatsapp_api(self):
        phone = "TEST_FOLLOWUP_SEND_EXPIRED"
        with patch.object(yossi, "verified_business_lead", return_value=True), \
             patch.object(yossi, "customer_freeform_send_allowed", return_value=False), \
             patch.object(yossi.requests, "post") as post:
            yossi._delivery_scope.current = {"fingerprint": "TEST_FOLLOWUP_EXPIRED_BATCH",
                                             "ordinal": 0}
            try:
                with self.assertRaises(PermissionError):
                    yossi.send_whatsapp(phone, body="synthetic test")
            finally:
                yossi._delivery_scope.current = None
            post.assert_not_called()

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
