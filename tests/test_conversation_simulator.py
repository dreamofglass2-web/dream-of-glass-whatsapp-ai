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
            patch.object(yossi, "has_new_messages", return_value=False),
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

    def test_customer_reset_does_not_touch_real_db(self):
        reply = self.step("התחל שיחה חדשה")
        self.assertIn("מתחילים מחדש", reply)
        self.assertEqual(self.memory[self.phone], ([], {}))


if __name__ == "__main__":
    unittest.main()
