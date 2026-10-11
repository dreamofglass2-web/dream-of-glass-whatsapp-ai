import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from quote_lab.builder import NamedPanel, price_proposed_layout
from quote_lab.workflow import create_offline_quote
from quote_lab.customer_preview import render_current_preview
from quote_lab.durable_store import DurableQuoteStore
from quote_lab.universal import Draft, Panel, NeedsReview, quote


class ApprovedHandleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DurableQuoteStore(Path(self.temp.name) / "handles.sqlite3")
        self.panels = [NamedPanel("door", 90, 200, "שקופה")] * 2

    def tearDown(self):
        self.temp.cleanup()

    def test_changes_are_replacements_not_additions(self):
        original = price_proposed_layout("פינתי 2 דלתות", self.panels, layout_confirmed=True)
        replacement = price_proposed_layout("פינתי 2 דלתות", self.panels,
                                             layout_confirmed=True, handle_style="ידית מגבת")
        self.assertEqual(Decimal(replacement["hardware_supplier_base_cost"])
                         - Decimal(original["hardware_supplier_base_cost"]), Decimal("100"))
        self.assertEqual(Decimal(replacement["price_before_vat"])
                         - Decimal(original["price_before_vat"]), Decimal("100"))

    def test_replacement_options_share_approved_price(self):
        for style in ("ידית מגבת", "ידית 19.2"):
            with self.subTest(style=style):
                calculated = price_proposed_layout("פינתי 2 דלתות",
                                                    self.panels, layout_confirmed=True,
                                                    handle_style=style)
                self.assertEqual(calculated["price_before_vat"], "2604.00")

    def test_changing_handle_creates_new_quote_version(self):
        original = create_offline_quote(self.store, "customer1", "פינתי 2 דלתות",
                                        self.panels, layout_confirmed=True)
        updated = create_offline_quote(self.store, "customer1", "פינתי 2 דלתות",
                                       self.panels, layout_confirmed=True,
                                       handle_style="ידית מגבת")
        self.assertEqual(updated["version"], 2)
        self.assertNotEqual(original["specification_fingerprint"],
                            updated["specification_fingerprint"])
        preview = render_current_preview(self.store, updated, template="פינתי 2 דלתות",
                                         panels=self.panels, finish="ניקל",
                                         handle_style="ידית מגבת")
        self.assertIn("ידיות: ידית מגבת", preview["text"])
        with self.assertRaises(NeedsReview):
            render_current_preview(self.store, updated, template="פינתי 2 דלתות",
                                   panels=self.panels, finish="ניקל",
                                   handle_style="ידית כפתור")

    def test_sliding_kit_cannot_double_charge_handle(self):
        with self.assertRaises(NeedsReview):
            quote(Draft("הזזה קבוע + דלת",
                        [Panel(Decimal(50), Decimal(200), "שקופה")],
                        handle_style="ידית מגבת"))

    def test_complex_handle_kit_requires_review(self):
        with self.assertRaises(NeedsReview):
            quote(Draft("חצי הרמוניקה + חצי קבוע + דלת",
                        [Panel(Decimal(50), Decimal(200), "שקופה")],
                        handle_style="ידית מגבת"))

    def test_existing_verified_price_unchanged(self):
        standard = price_proposed_layout("פינתי 2 דלתות", self.panels, layout_confirmed=True)
        self.assertEqual(standard["price_before_vat"], "2504.00")


if __name__ == "__main__":
    unittest.main()
