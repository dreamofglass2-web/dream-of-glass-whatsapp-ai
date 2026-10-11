import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from quote_lab.builder import NamedPanel
from quote_lab.customer_preview import render_current_preview
from quote_lab.durable_store import DurableQuoteStore
from quote_lab.universal import NeedsReview
from quote_lab.workflow import create_offline_quote


class FrostedDecorationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DurableQuoteStore(Path(self.temp.name) / "decorations.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def quote(self, decoration="none", other="none"):
        panels = [NamedPanel("door", 90, 200, "שקופה", decoration=decoration),
                  NamedPanel("door", 90, 200, "שקופה", decoration=other)]
        draft = create_offline_quote(self.store, "case-1", "פינתי 2 דלתות",
                                     panels, layout_confirmed=True)
        return draft, panels

    def test_frosted_stripes_both_panels_adds_75_per_square_meter(self):
        plain, _ = self.quote()
        stripes, panels = self.quote("frosted_stripes", "frosted_stripes")
        self.assertEqual(stripes["calculation"]["frosted_decoration_charge"], "270.00")
        self.assertEqual(Decimal(stripes["price_before_vat"]) -
                         Decimal(plain["price_before_vat"]), Decimal("270.00"))
        text = render_current_preview(self.store, stripes, template="פינתי 2 דלתות",
                                      panels=panels, finish="ניקל")["text"]
        self.assertIn("פסים חלבי", text)
        self.assertIn("2,774.00", text)

    def test_middle_frosted_on_one_panel_uses_only_that_panel_area(self):
        plain, _ = self.quote()
        modified, panels = self.quote("frosted_middle")
        self.assertEqual(modified["calculation"]["frosted_decoration_charge"], "135.00")
        self.assertEqual(Decimal(modified["price_before_vat"]) -
                         Decimal(plain["price_before_vat"]), Decimal("135.00"))
        text = render_current_preview(self.store, modified, template="פינתי 2 דלתות",
                                      panels=panels, finish="ניקל")["text"]
        self.assertIn("חלבי באמצע", text)

    def test_decoration_change_creates_new_fingerprint_and_version(self):
        old, _ = self.quote()
        new, _ = self.quote("frosted_stripes")
        self.assertEqual(new["version"], 2)
        self.assertNotEqual(old["specification_fingerprint"],
                            new["specification_fingerprint"])

    def test_both_types_not_charged_twice_for_one_panel(self):
        normal, _ = self.quote()
        other, _ = self.quote("frosted_stripes", "frosted_middle")
        self.assertEqual(Decimal(other["price_before_vat"]) -
                         Decimal(normal["price_before_vat"]), Decimal("270.00"))

    def test_unapproved_decoration_is_rejected(self):
        with self.assertRaises(NeedsReview):
            self.quote("special-unknown")

    def test_two_owner_benchmarks_remain_unchanged_without_decoration(self):
        first = [NamedPanel("fixed", 40, 200, "שקופה")] * 2 + [
                 NamedPanel("door", 40, 200, "שקופה")] * 2
        draft = create_offline_quote(self.store, "case-80",
                                     "פינתי 2 קבועים + 2 דלתות",
                                     first, layout_confirmed=True)
        self.assertEqual(draft["price_before_vat"], "2644.00")
        bronze = [NamedPanel("door", 90, 200, "אנטיסן ברונזה")] * 2
        second = create_offline_quote(self.store, "case-90",
                                      "פינתי 2 דלתות", bronze, layout_confirmed=True)
        self.assertEqual(second["price_before_vat"], "2828.00")


if __name__ == "__main__":
    unittest.main()
