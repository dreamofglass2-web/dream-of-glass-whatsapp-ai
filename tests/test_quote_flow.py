import ast
import pathlib
import re
import unittest

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "app.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
FUNCTIONS = {n.name: n for n in TREE.body if isinstance(n, ast.FunctionDef)}
SELECTED = ("quote_intent", "closing_intent", "explicit_quote_approval",
            "tiling_completed", "contains_ils_amount", "close_validated_quote", "missing_quote_detail", "helpful_quote_followup")
scope = {"re": re, "customer_written_text": lambda s: s, "BOM": {"פינתי 2 דלתות": {"ידית כפתור": 2}}, "SLIDING": {}}
code = compile(ast.Module(body=[FUNCTIONS[n] for n in SELECTED], type_ignores=[]), "<extracted helpers>", "exec")
exec(code, scope)


class QuoteFlowTests(unittest.TestCase):
    def test_source_syntax(self):
        self.assertGreater(len(TREE.body), 30)

    def test_first_customer_turn_has_final_greeting_guard(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("if len(history) == 1 and re.search", source)
        self.assertIn("reply = 'היי, מה שלומך? 🙂 ' + reply", source)

    def test_friendly_corner_opening(self):
        message = "אהלן, אני רוצה מקלחון פינתי 100 על 100, גובה 200, שתי דלתות פתיחה, זכוכית שקופה ופרזול שחור. כמה יעלה לי?"
        answer = scope["helpful_quote_followup"]({}, message, first_message=True)
        self.assertIn("היי, מה שלומך", answer)
        self.assertIn("שתי דלתות", answer)
        self.assertIn("יש לצדן גם זכוכיות קבועות", answer)
        self.assertNotIn("איך מחולקות הזכוכיות והדלתות", answer)

    def test_quote_intent(self):
        self.assertTrue(scope["quote_intent"]("כמה עולה מקלחון?"))
        self.assertFalse(scope["quote_intent"]("אני רוצה להתקדם איתכם"))

    def test_approval_vs_interest(self):
        self.assertFalse(scope["explicit_quote_approval"]("נשמע סביר, רוצה להתקדם"))
        self.assertTrue(scope["explicit_quote_approval"]("אני מאשר את ההצעה"))

    def test_close_intent(self):
        self.assertTrue(scope["closing_intent"]("מה השלב הבא?"))
        self.assertTrue(scope["closing_intent"]("אני רוצה לסגור"))
        self.assertFalse(scope["closing_intent"]("שלום"))

    def test_price_pattern(self):
        self.assertTrue(scope["contains_ils_amount"]("4200 ש״ח"))
        self.assertTrue(scope["contains_ils_amount"]("₪4,200"))
        self.assertFalse(scope["contains_ils_amount"]("אין לי מחיר עדיין"))

    def test_close_without_approval(self):
        out = scope["close_validated_quote"]({"issued": True, "approved": False},
                [{"role": "user", "content": "הריצוף הסתיים"}],
                "נשמע סביר, רוצה להתקדם")
        self.assertIn("מאשר", out)
        self.assertNotIn("מה כתובת", out)

    def test_close_with_approval_and_finished_tiling(self):
        out = scope["close_validated_quote"]({"issued": True, "approved": False},
                [{"role": "user", "content": "הריצוף הסתיים"}],
                "אני מאשר את ההצעה")
        self.assertIn("כתובת ההתקנה", out)

    def test_legacy_rewrites_do_not_override_validated_quote(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("if not quote_record.get('issued') and generic_price_question", source)
        self.assertIn("if not quote_record.get('issued') and re.search", source)

    def test_quote_change_requires_customer_input(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("prior_quote and explicit_spec_change and any(", source)
        self.assertIn("next_context.pop('validated_quote', None)", source)

    def test_existing_lead_and_media_paths_preserved(self):
        source = SOURCE.read_text(encoding="utf-8")
        for key in ("def save_callback(", "def pick_portfolio_photos(",
                    "def analyze_customer_media(", "def send_whatsapp(",
                    "def admin_leads(", "def calculate_quote("):
            self.assertIn(key, source)

    def test_latest_tiling_correction_wins(self):
        self.assertFalse(scope["tiling_completed"]([
            {"role": "user", "content": "הריצוף הסתיים"},
            {"role": "assistant", "content": "מעולה"},
            {"role": "user", "content": "טעיתי, הריצוף עוד לא הסתיים"}
        ]))
        self.assertTrue(scope["tiling_completed"]([
            {"role": "user", "content": "אנחנו עדיין בשיפוץ"},
            {"role": "user", "content": "הריצוף הסתיים"}
        ]))

    def test_future_tiling_not_completed(self):
        self.assertFalse(scope["tiling_completed"]([
            {"role": "user", "content": "הריצוף יסתיים בעוד שבוע"}
        ]))

    def test_no_early_measurement(self):
        out = scope["close_validated_quote"]({"issued": True, "approved": True},
                [{"role": "user", "content": "הריצוף עוד לא הסתיים"}],
                "מה עושים?")
        self.assertNotIn("מה כתובת", out)


if __name__ == "__main__":
    unittest.main()
