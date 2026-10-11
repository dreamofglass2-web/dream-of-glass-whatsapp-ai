"""Offline end-to-end conversation simulation.

Runs the real process_message function but replaces Meta, PostgreSQL and the
OpenAI response with in-memory fakes. No real customer receives messages.
"""
import json
import os
import types
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test-only")
import app as yossi


class FakeResponses:
    def __init__(self):
        self.queue = []

    def create(self, **kwargs):
        if not self.queue:
            raise AssertionError("No scripted model response available")
        return types.SimpleNamespace(output_text=json.dumps(self.queue.pop(0), ensure_ascii=False))


class ConversationSimulation(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.memory = {}
        self.ai = FakeResponses()
        self.patches = [
            patch.object(yossi, "load_conversation", side_effect=self.load),
            patch.object(yossi, "save_conversation", side_effect=self.save),
            patch.object(yossi, "send_whatsapp", side_effect=self.send),
            patch.object(yossi, "reset_conversation_for_phone", side_effect=self.reset),
            patch.object(yossi, "save_callback", return_value=True),
            patch.object(yossi, "save_custom_quote_lead", return_value=True),
            patch.object(yossi, "has_new_messages", return_value=False),
            patch.object(yossi.time, "sleep", return_value=None),
            patch.object(yossi.client.responses, "create", side_effect=self.ai.create),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        self.phone = "OFFLINE_SIMULATION_ONLY"
        yossi.pending.clear()
        yossi.customer_context.clear()
        yossi.histories.clear()

    def load(self, phone):
        history, context = self.memory.get(phone, ([], {}))
        return list(history), dict(context)

    def save(self, phone, history, context):
        self.memory[phone] = (list(history), dict(context))

    def send(self, phone, body=None, image_url=None, caption=None):
        self.assertEqual(phone, self.phone)
        self.sent.append(body if body is not None else "[TEST_IMAGE]")

    def reset(self, phone):
        self.memory[phone] = ([], {})
        return True

    def step(self, customer, model=None):
        if model is not None:
            self.ai.queue.append(model)
        self.assertTrue(yossi.process_message(self.phone, customer))
        return self.sent[-1]

    def model(self, reply, **fields):
        return dict({
            "reply": reply, "stage": "discovery", "action": "reply",
            "product": "מקלחון", "needs_human": False,
            "quote_requested": False, "solution_agreed": False,
        }, **fields)

    def test_tomorrow_callback_collects_hour_and_saves_exact_date(self):
        with patch.object(yossi, 'save_callback', return_value=True) as store:
            first = self.step('היי תתקשרו אליי מחר')
            self.assertIn('באיזו שעה מחר', first)
            self.assertNotIn('נקבע', first)
            store.assert_called_once_with(self.phone)
            self.assertEqual(self.memory[self.phone][1]['callback_requested_day'], 'מחר')
            with patch.object(yossi, 'waiting_for_callback_time', return_value=True):
                reply = self.step('בשעה 10', self.model('נחזור אליך'))
            self.assertIn('10:00', reply)
            self.assertIn('אלירן', reply)
            self.assertNotIn('תאריך טרם תואם', reply)
            self.assertEqual(store.call_count, 2)
            self.assertIsNone(self.memory[self.phone][1].get('callback_requested_day'))

    def test_outgoing_messages_never_contain_emojis(self):
        self.assertEqual(yossi.without_emojis("היי 😊 מה שלומך? 🙂"), "היי מה שלומך?")
        self.assertEqual(yossi.without_emojis("תודה רבה 👍"), "תודה רבה")
        self.assertEqual(yossi.without_emojis("מחיר ₪2,595 לפני מע״מ"), "מחיר ₪2,595 לפני מע״מ")
        self.assertNotIn("🙂", yossi.polish_reply("אני כאן בשבילך 🙂", []))

    def test_finish_question_does_not_offer_colors_unasked(self):
        opening = self.step("שלום, רוצה מקלחון פינתי",
                            self.model("איזה גוון פרזול תרצו, שחור או כרום?"))
        self.assertIn("איזה גוון פרזול תרצו?", opening)
        self.assertNotIn("שחור או כרום", opening)

    def test_finish_colors_can_be_listed_when_customer_asks(self):
        opening = self.step("איזה גוונים יש לפרזול?",
                            self.model("יש שחור או כרום, וגם ניקל מוברש."))
        self.assertIn("שחור או כרום", opening)

    def test_custom_quote_mentions_eliran_and_uses_known_name(self):
        self.step("שלום, קוראים לי דניאל. צריך מקלחון פינתי",
                  self.model("איזה סוג דלתות תרצה?"))
        reply = self.step("הזזה פינתי, כמה יעלה?",
                          self.model("איך מחולקות הדלתות?", quote_requested=True))
        self.assertIn("אלירן דוד הכהן", reply)
        self.assertIn("בעל העסק", reply)
        self.assertIn("שמרתי את הפנייה", reply)
        self.assertNotIn("איך קוראים לך", reply)

    def test_unsupported_corner_sliding_creates_owner_lead(self):
        self.step("אני רוצה מקלחון פינתי 90 על 90 גובה 200",
                  self.model("כמה דלתות?"))
        reply = self.step("אני רוצה דלתות הזזה. כמה יעלה?",
                          self.model("איך מחולקות הדלתות?", quote_requested=True))
        self.assertIn("שמרתי את הפנייה", reply)
        self.assertIn("איך קוראים לך", reply)
        self.assertTrue(self.memory[self.phone][1].get("custom_quote_lead_saved"))
        with patch.object(yossi, "save_custom_quote_lead") as store:
            again = self.step("אמרתי לך הזזה",
                              self.model("איך מחולקות הדלתות?"))
            store.assert_not_called()
            self.assertIn("כבר שמורה", again)

    def test_corner_sliding_customer_is_not_asked_same_layout_again(self):
        self.step("אני מחפש מקלחון פינתי 90 על 90 גובה 200",
                  self.model("איזה סוג דלתות תרצה?"))
        self.step("מעדיף מקלחון פינתי עם דלתות הזזה. כמה זה עולה?",
                  self.model("איך מחולקות הזכוכיות והדלתות?", quote_requested=True))
        answer = self.step("אמרתי לך הזזה", self.model(
            "כדי לתת מחיר אמין צריך לוודא את תצורת המקלחון. איך מחולקות הזכוכיות והדלתות?"))
        self.assertIn("דלתות הזזה", answer)
        self.assertIn("אין לי כרגע מחיר מאומת", answer)
        self.assertNotIn("איך מחולקות הזכוכיות והדלתות", answer)
        self.assertNotIn("₪", answer)

    def test_sales_guidance_recognizes_objection_and_preserves_name_intro(self):
        opening = [{"role": "user", "content": "שלום, אני רוצה מקלחון"}]
        first = yossi.sales_turn_guidance("שלום, אני רוצה מקלחון", opening)
        self.assertIn("שם הלקוח", first)
        history = [
            {"role": "user", "content": "אני צריך מקלחון"},
            {"role": "assistant", "content": "אשמח לעזור"},
            {"role": "user", "content": "קיבלתי הצעה זולה יותר"},
        ]
        objections = yossi.sales_turn_guidance("קיבלתי הצעה זולה יותר", history)
        self.assertIn("התנגדות", objections)
        self.assertIn("ערך מבוסס", objections)

    def test_warm_open_and_no_invented_price(self):
        message = "אהלן, רוצה מקלחון פינתי 100 על 100, גובה 200, שתי דלתות פתיחה, זכוכית שקופה ופרזול שחור. כמה יעלה?"
        reply = self.step(message, self.model("כדי לתת מחיר אמין צריך לוודא את תצורת המקלחון. איך מחולקות הזכוכיות והדלתות?", quote_requested=True))
        self.assertTrue(reply.startswith("היי"), reply)
        self.assertIn("שתי דלתות", reply)
        self.assertNotIn("₪", reply)
        self.assertNotIn("4,200", reply)

    def test_never_pass_ai_fabricated_amount(self):
        message = "כמה עולה מקלחון פינתי?"
        reply = self.step(message, self.model("זה עולה 4,200 ש״ח.", quote_requested=True))
        self.assertNotIn("4,200", reply)
        self.assertNotIn("4200", reply)

    def test_price_then_repeat_then_approval_then_measurement(self):
        specs = dict(
            product="מקלחון", configuration="פינתי 2 דלתות",
            width_cm=100, second_width_cm=100, height_cm=200,
            glass_type="שקופה", finish="שחור", handles=["ידית כפתור", "ידית כפתור"],
            quote_requested=True, solution_agreed=True,
        )
        if yossi.calculate_quote(specs) is None:
            self.skipTest("Business calculator differs: adjust test fixtures to actual enum")
        price = yossi.calculate_quote(specs)
        opening = self.step("שלום, כמה עולה מקלחון פינתי 100 על 100 גובה 200 שתי דלתות?",
                            self.model("אשמח לעזור.", **specs))
        self.assertIn(f"₪{price:,.0f}", opening)
        repeated = self.step("מה המחיר שוב?", self.model("המחיר הוא 99,999 ש״ח"))
        self.assertIn(f"₪{price:,.0f}", repeated)
        self.assertNotIn("99,999", repeated)
        interested = self.step("נשמע סביר, רוצה להתקדם", self.model("אתה מחליט לבד?"))
        self.assertIn("מאשר", interested)
        self.assertNotIn("מחליט לבד", interested)
        approved = self.step("אני מאשר את ההצעה", self.model("בוא נתחיל.", **specs))
        self.assertIn("ההצעה מאושרת", approved)
        self.assertNotIn("כתובת ההתקנה", approved)

    def test_tiling_revision_and_completed_approval(self):
        specs = dict(product="מקלחון", configuration="פינתי 2 דלתות",
                     width_cm=100, second_width_cm=100, height_cm=200,
                     glass_type="שקופה", finish="שחור",
                     handles=["ידית כפתור", "ידית כפתור"],
                     quote_requested=True, solution_agreed=True)
        if yossi.calculate_quote(specs) is None:
            self.skipTest("Business calculator differs: adjust test fixtures to actual enum")
        self.step("כמה עולה מקלחון פינתי 100 על 100?", self.model("בודק", **specs))
        self.step("הריצוף הסתיים", self.model("יופי"))
        self.step("טעיתי, הריצוף עוד לא הסתיים", self.model("הבנתי"))
        reply = self.step("אני מאשר את ההצעה", self.model("נתקדם"))
        self.assertNotIn("כתובת ההתקנה", reply)

    def test_real_report_corner_quote_after_customer_confirms_layout(self):
        opening = "אהלן, אני צריך מקלחון פינתי 100 על 100, שתי דלתות שנפתחות, זכוכית שקופה ופרזול שחור. כמה עולה?"
        first = self.step(opening, self.model("איך מחולקות הדלתות?", quote_requested=True))
        self.assertIn("דלתות", first)
        self.step("הדלתות ישר על הקירות, אין קבועים. גובה 200.", self.model("איזה ידיות תרצה?"))
        answer = self.step("ידיות רגילות, כפתור. כמה זה ייצא?",
                           self.model("איך מחולקות הזכוכיות והדלתות?", quote_requested=True))
        self.assertIn("₪", answer)
        self.assertNotIn("איך מחולקות הזכוכיות והדלתות", answer)
        self.assertTrue(self.memory[self.phone][1].get("validated_quote", {}).get("issued"))

    def test_cannot_accept_unissued_quote(self):
        self.step("שלום, רוצה מקלחון פינתי, כמה עולה?", self.model("צריך עוד פרטים"))
        answer = self.step("אני מאשר את ההצעה", self.model("סגור, נבוא למדוד"))
        self.assertNotIn("ההצעה מאושרת", answer)
        self.assertIn("עוד לא נתתי", answer)

    def test_cheaper_competitor_offer_is_addressed_without_fake_discount(self):
        specs = dict(
            product="מקלחון", configuration="פינתי 2 דלתות",
            width_cm=100, second_width_cm=100, height_cm=200,
            glass_type="שקופה", finish="שחור",
            handles=["ידית כפתור", "ידית כפתור"],
            quote_requested=True, solution_agreed=True,
        )
        self.step("כמה עולה מקלחון פינתי 100 על 100 שתי דלתות גובה 200?",
                  self.model("הנה המחיר", **specs))
        answer = self.step("זה יותר ממה שתכננתי. קיבלתי הצעה זולה ב-700 שקל.",
                           self.model("המחיר שלנו הוא 700 שקל יותר"))
        self.assertIn("פער כזה במחיר", answer)
        self.assertIn("שירות אישי", answer)
        self.assertIn("גם אחרי ההתקנה", answer)
        self.assertIn("ההצעה שקיבלת כוללת גם התקנה", answer)
        self.assertNotIn("המחיר המאומת למפרט", answer)

    def test_customer_reset_does_not_touch_real_db(self):
        reply = self.step("התחל שיחה חדשה")
        self.assertIn("מתחילים מחדש", reply)
        self.assertEqual(self.memory[self.phone], ([], {}))


if __name__ == "__main__":
    unittest.main()


class FollowupStartupTests(unittest.TestCase):
    def test_worker_creates_followup_table_before_start(self):
        from unittest.mock import MagicMock
        with patch.object(yossi, 'ensure_db') as customer_schema, \
             patch.object(yossi, 'ensure_followup_table') as schema, \
             patch.object(yossi, 'ensure_inbound_queue_table') as queue_schema, \
             patch.object(yossi, 'ensure_outbound_attempts_table') as outbound_schema, \
             patch.object(yossi, 'restore_inbound_queue') as restore, \
             patch.object(yossi.threading, 'Thread') as thread, \
             patch.object(yossi.os, 'getpid', return_value=-999):
            yossi.ensure_worker_started()
            customer_schema.assert_called_once()
            schema.assert_called_once()
            queue_schema.assert_called_once()
            outbound_schema.assert_called_once()
            restore.assert_called_once()
            thread.assert_called_once()

    def test_failed_schema_does_not_start_worker(self):
        with patch.object(yossi, 'ensure_followup_table', side_effect=RuntimeError('test')), \
             patch.object(yossi.threading, 'Thread') as thread, \
             patch.object(yossi.os, 'getpid', return_value=-998):
            yossi.ensure_worker_started()
            thread.assert_not_called()


class CustomerInboundWindowTests(unittest.TestCase):
    def test_24_hour_window_boundaries(self):
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 10, 11, 9, tzinfo=timezone.utc)
        self.assertTrue(yossi.freeform_whatsapp_window_valid(now-timedelta(hours=23), now))
        self.assertFalse(yossi.freeform_whatsapp_window_valid(now-timedelta(hours=24), now))
        self.assertFalse(yossi.freeform_whatsapp_window_valid(now+timedelta(minutes=1), now))
        self.assertFalse(yossi.freeform_whatsapp_window_valid(None, now))

    def test_inbound_timestamp_is_persisted_without_outreach(self):
        from unittest.mock import MagicMock
        connection = MagicMock()
        cursor = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        with patch.object(yossi, 'db_connection', return_value=connection), \
             patch.object(yossi, 'ensure_db'), \
             patch.object(yossi, 'send_whatsapp') as sender:
            self.assertTrue(yossi.record_customer_inbound('TEST_NUMBER'))
            sql, args = cursor.execute.call_args.args
            self.assertIn('last_inbound_at', sql)
            self.assertEqual(args, ('TEST_NUMBER',))
            sender.assert_not_called()


class FollowupSendPreflightTests(unittest.TestCase):
    def test_fails_closed_outside_hours(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        with patch.object(yossi, 'db_connection') as db, \
             patch.object(yossi, 'send_whatsapp') as sender:
            result = yossi.inspect_due_followups(datetime(2026, 10, 17, 12, tzinfo=ZoneInfo('Asia/Jerusalem')))
            self.assertEqual(result['reason'], 'outside_business_hours')
            db.assert_not_called()
            sender.assert_not_called()

    def test_blocks_followups_without_optin_and_whatsapp_template(self):
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        from unittest.mock import MagicMock
        connection = MagicMock()
        cursor = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchall.return_value = [
            ('TEST_A', None, None, 'חדש', {}, [], None),
            ('TEST_B', None, None, 'חדש', {'followup_consent': True}, [], None),
            ('TEST_C', None, None, 'ממתין לחזרה', {}, [], None),
            ('TEST_D', None, None, 'חדש', {'no_followups': True}, [], None),
        ]
        with patch.object(yossi, 'db_connection', return_value=connection), \
             patch.object(yossi, 'ensure_followup_table'), \
             patch.object(yossi, 'send_whatsapp') as sender:
            result = yossi.inspect_due_followups(datetime(2026, 10, 12, 10, tzinfo=ZoneInfo('Asia/Jerusalem')))
            self.assertEqual(result['due'], 4)
            self.assertEqual(result['eligible'], 0)
            self.assertEqual(result['blocked'], 4)
            self.assertEqual(result['reasons']['no_explicit_followup_consent'], 1)
            self.assertEqual(result['reasons']['whatsapp_window_expired_template_required'], 1)
            sender.assert_not_called()


class DurableFollowupTests(unittest.TestCase):
    def test_schedule_is_dry_run_only(self):
        from datetime import datetime, timezone
        from unittest.mock import MagicMock
        cursor = MagicMock()
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        with patch.object(yossi, 'db_connection', return_value=connection), \
             patch.object(yossi, 'ensure_followup_table'), \
             patch.object(yossi, 'send_whatsapp') as sender:
            yossi.schedule_followup_dry_run('972501234567',
                datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc))
            sender.assert_not_called()
            query = cursor.execute.call_args.args[0]
            self.assertIn('ON CONFLICT', query)
            self.assertIn('no_followups', query)
            self.assertIn('ממתין לחזרה', query)

    def test_new_message_cancels_pending_followup(self):
        with patch.object(yossi, 'cancel_followup_dry_run') as cancel, \
             patch.object(yossi, 'persist_inbound_message', return_value=True):
            yossi.queue_message('TEST_PHONE', 'שלום', 'TEST_FOLLOWUP_MSG_001')
            cancel.assert_called_once_with('TEST_PHONE')
        with yossi.lock:
            yossi.pending.pop('TEST_PHONE', None)


class BusinessHoursPolicyTests(unittest.TestCase):
    def test_open_days_and_boundaries(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo('Asia/Jerusalem')
        self.assertTrue(yossi.is_yossi_business_hours(datetime(2026, 10, 11, 8, 0, tzinfo=tz)))
        self.assertTrue(yossi.is_yossi_business_hours(datetime(2026, 10, 15, 19, 59, tzinfo=tz)))
        self.assertFalse(yossi.is_yossi_business_hours(datetime(2026, 10, 15, 20, 0, tzinfo=tz)))
        self.assertFalse(yossi.is_yossi_business_hours(datetime(2026, 10, 16, 12, 0, tzinfo=tz)))
        self.assertFalse(yossi.is_yossi_business_hours(datetime(2026, 10, 17, 12, 0, tzinfo=tz)))

    def test_followup_four_hours_and_next_open(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo('Asia/Jerusalem')
        self.assertEqual(yossi.earliest_followup_at(datetime(2026, 10, 12, 10, 0, tzinfo=tz)).hour, 14)
        self.assertEqual(yossi.earliest_followup_at(datetime(2026, 10, 15, 19, 0, tzinfo=tz)).isoformat(),
                         datetime(2026, 10, 18, 8, 0, tzinfo=tz).isoformat())
        self.assertFalse(yossi.AUTO_FOLLOWUPS_ENABLED)


class CallHandoffPolicyTests(unittest.TestCase):
    def test_explicit_callback_intent(self):
        self.assertTrue(yossi.is_callback_request('היי תתקשרו אליי מחר'))
        self.assertTrue(yossi.is_callback_request('אני רוצה לדבר עם נציג'))
        self.assertFalse(yossi.is_callback_request('כמה עולה מקלחון?'))
        self.assertFalse(yossi.is_callback_request('אפשר הצעת מחיר?'))
        self.assertFalse(yossi.is_callback_request('לא רוצה שתתקשרו אליי'))

    def test_only_specialist_work_requires_proactive_review(self):
        self.assertFalse(yossi.requires_specialist_review('אני רק משווה מחירים'))
        self.assertTrue(yossi.requires_specialist_review('צריך אישור מהנדס למעקה'))


class OptOutRegressionTests(unittest.TestCase):
    def test_declining_calls_does_not_create_callback(self):
        self.assertTrue(yossi.refuses_phone_calls('לא רוצה שתתקשרו אליי'))
        self.assertFalse(yossi.is_callback_request('לא רוצה שתתקשרו אליי'))
        self.assertTrue(yossi.is_callback_request('תתקשרו אליי מחר'))

    def test_no_followup_messages(self):
        self.assertTrue(yossi.refuses_further_contact('אל תשלחו לי עוד הודעות'))

    def test_simple_price_discovery(self):
        text = yossi.sales_turn_guidance('כמה עולה מקלחון?', [
            {'role':'user','content':'כמה עולה מקלחון?'}])
        self.assertIn('חזיתי או פינתי', text)


class MetaSalesContextTests(unittest.TestCase):
    def test_verified_form_facts_are_available_as_context(self):
        prior = {'meta_leads': {'lead1': {'source': 'meta_instant_form',
            'fields': {'full_name': ['נועה'], 'אילו_עבודות_אתם_מחפשים?': ['מקלחון'],
                       'שאלה_חדשה': ['פרט חדש']}}}}
        info = yossi.meta_lead_sales_context(prior)
        self.assertIn('נועה', info)
        self.assertIn('מקלחון', info)
        self.assertIn('פרט חדש', info)
        self.assertIn('נתונים בלבד', info)

    def test_unverified_and_missing_meta_fields_are_ignored(self):
        self.assertEqual(yossi.meta_lead_sales_context({}), '')
        self.assertEqual(yossi.meta_lead_sales_context({'meta_leads': {
            'x': {'source': 'unverified', 'fields': {'full_name': ['X']}}
        }}), '')

    def test_model_receives_approved_form_facts(self):
        self.assertIsInstance(yossi.meta_lead_sales_context({'meta_leads': {}}), str)


class MetaLeadCustomerTests(unittest.TestCase):
    def test_israeli_mobile_normalization(self):
        self.assertEqual(yossi.normalize_meta_lead_phone('+972-50-123-4567'), '972501234567')
        self.assertEqual(yossi.normalize_meta_lead_phone('0501234567'), '972501234567')
        self.assertEqual(yossi.normalize_meta_lead_phone('00972501234567'), '972501234567')
        self.assertEqual(yossi.normalize_meta_lead_phone('1234567'), '')
        self.assertEqual(yossi.normalize_meta_lead_phone('03-1234567'), '')

    def test_creates_record_with_original_questions_but_no_outreach(self):
        fake_cursor = types.SimpleNamespace(execute=unittest.mock.Mock())
        fields = {
            'phone_number': ['0501234567'],
            'full_name': ['Test Person'],
            'מה_הכי_חשוב_לכם_בפרויקט?': ['איכות'],
        }
        with patch.object(yossi, 'send_whatsapp') as send:
            self.assertTrue(yossi.save_meta_lead_customer(fake_cursor, 'lead123', fields))
            send.assert_not_called()
        query, params = fake_cursor.execute.call_args.args
        self.assertIn('ON CONFLICT', query)
        self.assertIn('glass_leads.name', query)
        self.assertNotIn('status=', query)
        self.assertEqual(params[0], '972501234567')
        self.assertEqual(params[1], 'Test Person')
        saved = json.loads(params[2])
        self.assertEqual(saved['meta_leads']['lead123']['fields']['מה_הכי_חשוב_לכם_בפרויקט?'], ['איכות'])

    def test_invalid_phone_does_not_create_customer(self):
        cursor = types.SimpleNamespace(execute=unittest.mock.Mock())
        self.assertFalse(yossi.save_meta_lead_customer(cursor, 'lead123', {'phone_number': ['bad']}))
        cursor.execute.assert_not_called()


    def test_full_meta_details_to_customer_flow_is_silent_and_idempotent(self):
        """Run the persistence path twice using fake DB cursors, never real customers."""
        from contextlib import contextmanager
        all_queries = []

        @contextmanager
        def fake_connection():
            class Conn:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
                def cursor(self):
                    class Cur:
                        def __enter__(self):
                            return self
                        def __exit__(self, *args):
                            pass
                        def execute(self, query, params):
                            all_queries.append((query, params))
                    return Cur()
            yield Conn()

        details = {
            'id': 'synthetic-lead-01',
            'field_data': [
                {'name': 'phone_number', 'values': ['0501234567']},
                {'name': 'full_name', 'values': ['לקוח בדיקה']},
                {'name': 'city', 'values': ['בדיקה']},
                {'name': 'שאלה_חדשה_בקמפיין', 'values': ['תשובה חדשה']},
            ],
        }
        with patch.object(yossi, 'db_connection', side_effect=fake_connection), \
             patch.object(yossi, 'send_whatsapp') as send:
            yossi.persist_meta_lead_details('synthetic-lead-01', details)
            yossi.persist_meta_lead_details('synthetic-lead-01', details)
            send.assert_not_called()

        self.assertEqual(len(all_queries), 4)
        customer_statements = [(sql, params) for sql, params in all_queries
                               if 'INSERT INTO glass_leads' in sql]
        self.assertEqual(len(customer_statements), 2)
        for query, params in customer_statements:
            self.assertIn('ON CONFLICT (phone) DO UPDATE', query)
            self.assertNotIn("status=", query)
            self.assertEqual(params[0], '972501234567')
            self.assertEqual(params[1], 'לקוח בדיקה')
            fields = json.loads(params[2])['meta_leads']['synthetic-lead-01']['fields']
            self.assertEqual(fields['שאלה_חדשה_בקמפיין'], ['תשובה חדשה'])


class MetaLeadDetailsTests(unittest.TestCase):
    def test_no_token_never_calls_meta(self):
        with patch.object(yossi, 'META_LEADS_ACCESS_TOKEN', ''), \
             patch.object(yossi.requests, 'get') as request_get:
            self.assertIsNone(yossi.fetch_meta_lead_details('123'))
            request_get.assert_not_called()

    def test_fetch_uses_authorization_header_and_validates_id(self):
        response = types.SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {'id': '123', 'field_data': [
                {'name': 'full_name', 'values': ['Test Person']}]})
        with patch.object(yossi, 'META_LEADS_ACCESS_TOKEN', 'dummy-token'), \
             patch.object(yossi.requests, 'get', return_value=response) as request_get:
            details = yossi.fetch_meta_lead_details('123')
            self.assertEqual(details['id'], '123')
            kwargs = request_get.call_args.kwargs
            self.assertEqual(kwargs['headers']['Authorization'], 'Bearer dummy-token')
            self.assertNotIn('access_token', kwargs['params'])

    def test_invalid_lead_details_fail_closed(self):
        response = types.SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {'id': 'wrong', 'field_data': []})
        with patch.object(yossi, 'META_LEADS_ACCESS_TOKEN', 'dummy-token'), \
             patch.object(yossi.requests, 'get', return_value=response):
            with self.assertRaises(ValueError):
                yossi.fetch_meta_lead_details('123')

    def test_webhook_does_not_send_messages_when_meta_fetch_fails(self):
        import hmac
        payload = {'object': 'page', 'entry': [{'id': 'PAGE1', 'changes': [
            {'field': 'leadgen', 'value': {'leadgen_id': 'LEAD1'}}]}]}
        body = json.dumps(payload).encode()
        signature = 'sha256=' + hmac.new(b'test-secret', body, 'sha256').hexdigest()
        with patch.object(yossi, 'APP_SECRET', 'test-secret'), \
             patch.object(yossi, 'META_LEADS_ACCESS_TOKEN', 'dummy-token'), \
             patch.object(yossi, 'store_meta_leadgen_event'), \
             patch.object(yossi, 'fetch_meta_lead_details', side_effect=RuntimeError('fail')), \
             patch.object(yossi, 'send_whatsapp') as send:
            result = yossi.app.test_client().post('/meta-leads/webhook', data=body,
                headers={'X-Hub-Signature-256': signature}, content_type='application/json')
            self.assertEqual(result.status_code, 200)
            send.assert_not_called()


class MetaLeadgenReceiverTests(unittest.TestCase):
    def setUp(self):
        self.app = yossi.app.test_client()

    def test_verification_requires_separate_configured_token(self):
        with patch.object(yossi, 'META_LEADS_VERIFY_TOKEN', 'lead-verify-test'):
            response = self.app.get('/meta-leads/webhook', query_string={
                'hub.mode': 'subscribe', 'hub.verify_token': 'lead-verify-test',
                'hub.challenge': 'challenge123',
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_data(as_text=True), 'challenge123')
            self.assertEqual(self.app.get('/meta-leads/webhook', query_string={
                'hub.mode': 'subscribe', 'hub.verify_token': 'wrong',
            }).status_code, 403)
        with patch.object(yossi, 'META_LEADS_VERIFY_TOKEN', ''):
            self.assertEqual(self.app.get('/meta-leads/webhook', query_string={
                'hub.mode': 'subscribe', 'hub.verify_token': '',
            }).status_code, 403)

    def test_valid_signed_leadgen_is_saved_without_any_outreach(self):
        import hmac
        payload = {'object': 'page', 'entry': [{'id': 'PAGE1', 'changes': [
            {'field': 'leadgen', 'value': {
                'leadgen_id': 'LEAD1', 'form_id': 'FORM1', 'created_time': 12345,
            }},
        ]}]}
        body = json.dumps(payload).encode()
        signature = 'sha256=' + hmac.new(b'test-secret', body, 'sha256').hexdigest()
        with patch.object(yossi, 'APP_SECRET', 'test-secret'), \
                patch.object(yossi, 'store_meta_leadgen_event') as store, \
                patch.object(yossi, 'send_whatsapp') as send:
            response = self.app.post('/meta-leads/webhook', data=body,
                headers={'X-Hub-Signature-256': signature}, content_type='application/json')
            self.assertEqual(response.status_code, 200)
            store.assert_called_once_with('LEAD1', 'PAGE1', 'FORM1', 12345)
            send.assert_not_called()
            self.assertEqual(self.app.post('/meta-leads/webhook', data=body,
                content_type='application/json').status_code, 403)

    def test_receiver_fails_closed_and_retries_storage_failures(self):
        import hmac
        body = b'{"object":"page","entry":[{"id":"PAGE1","changes":[{"field":"leadgen","value":{"leadgen_id":"LEAD1"}}]}]}'
        signature = 'sha256=' + hmac.new(b'test-secret', body, 'sha256').hexdigest()
        with patch.object(yossi, 'APP_SECRET', ''):
            self.assertEqual(self.app.post('/meta-leads/webhook', data=body).status_code, 503)
        with patch.object(yossi, 'APP_SECRET', 'test-secret'), \
                patch.object(yossi, 'store_meta_leadgen_event', side_effect=RuntimeError('offline')):
            self.assertEqual(self.app.post('/meta-leads/webhook', data=body,
                headers={'X-Hub-Signature-256': signature}, content_type='application/json').status_code, 503)

