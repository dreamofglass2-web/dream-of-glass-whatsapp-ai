"""End-to-end whole-shower design changes; local ledger only."""
import tempfile
import unittest
from pathlib import Path

from quote_lab.builder import NamedPanel
from quote_lab.customer_preview import render_current_preview
from quote_lab.durable_store import DurableQuoteStore, QuoteStoreError
from quote_lab.universal import Draft, NeedsReview, Panel, quote
from quote_lab.workflow import create_offline_quote


class WholeShowerDesignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "quotes.sqlite3"
        self.store = DurableQuoteStore(self.path)
        self.panels = [NamedPanel("door", 90, 200, "אנטיסן ברונזה")] * 2

    def tearDown(self):
        self.temp.cleanup()

    def create(self, design="none", panels=None):
        return create_offline_quote(self.store, "owner-90", "פינתי 2 דלתות",
                                    panels or self.panels, layout_confirmed=True,
                                    decoration=design)

    def preview(self, draft, design="none", panels=None):
        return render_current_preview(self.store, draft, template="פינתי 2 דלתות",
                                      panels=panels or self.panels, finish="ניקל",
                                      decoration=design)["text"]

    def test_both_designs_use_all_glass_once_and_preview_once(self):
        for design, label in [("frosted_stripes", "פסים חלבי"),
                              ("frosted_middle", "חלבי באמצע")]:
            with self.subTest(design=design):
                draft = self.create(design)
                self.assertEqual(draft["price_before_vat"], "3098.00")
                self.assertEqual(draft["calculation"]["frosted_decoration_charge"], "270.00")
                text = self.preview(draft, design)
                self.assertEqual(text.count(label), 1)
                self.assertIn("כל זכוכיות המקלחון", text)
                self.assertNotIn("864", text)
                self.assertFalse(draft["can_send_whatsapp"])

    def test_legacy_and_whole_shower_selection_are_equivalent(self):
        legacy_panels = [NamedPanel("door", 90, 200, "אנטיסן ברונזה",
                                   decoration="frosted_stripes"), self.panels[1]]
        legacy = self.create(panels=legacy_panels)
        modern = self.create("frosted_stripes")
        self.assertEqual(legacy["specification_fingerprint"], modern["specification_fingerprint"])
        self.assertEqual(legacy["price_before_vat"], modern["price_before_vat"])
        self.assertEqual(self.preview(modern, "frosted_stripes"),
                         self.preview(modern, panels=legacy_panels))

    def test_conflicting_legacy_selection_cannot_create_draft(self):
        conflicting = [NamedPanel("door", 90, 200, "אנטיסן ברונזה",
                                  decoration="frosted_middle"), self.panels[1]]
        with self.assertRaises(NeedsReview):
            self.create("frosted_stripes", conflicting)
        self.assertEqual(self.store.history("owner-90"), [])

    def test_design_changes_reset_approval_and_survive_restart(self):
        old = self.create()
        self.store.mark_sent("owner-90", old["version"], "test-delivery-1")
        self.store.mark_approved("owner-90", old["version"],
                                 old["specification_fingerprint"], old["price_before_vat"],
                                 "test-customer-approval-1")
        new = self.create("frosted_middle")
        self.store = DurableQuoteStore(self.path)
        current = self.store.latest("owner-90")
        self.assertEqual(current["state"], "draft")
        self.assertIsNone(current["approval_ref"])
        self.assertIsNone(current["delivery_ref"])
        self.assertNotEqual(old["specification_fingerprint"], new["specification_fingerprint"])
        self.assertEqual(len(self.store.history("owner-90")), 2)
        with self.assertRaises(QuoteStoreError):
            self.store.mark_approved("owner-90", new["version"],
                                     old["specification_fingerprint"], old["price_before_vat"],
                                     "test-customer-approval-1")
        self.assertIn("חלבי באמצע", self.preview(new, "frosted_middle"))
        with self.assertRaises(NeedsReview):
            self.preview(old)

    def test_preview_requires_matching_design(self):
        draft = self.create("frosted_middle")
        for design in ["none", "frosted_stripes", "unknown"]:
            with self.subTest(design=design), self.assertRaises(NeedsReview):
                self.preview(draft, design)

    def test_base_frosted_glass_has_no_automatic_design_surcharge(self):
        panels = [NamedPanel("door", 90, 200, "חלבי")] * 2
        draft = self.create(panels=panels)
        self.assertEqual(draft["calculation"]["frosted_decoration_charge"], "0.00")
        self.assertEqual(draft["price_before_vat"], "2756.00")

    def test_direct_engine_applies_one_selection_to_four_panels(self):
        panels = [Panel(40, 200, "שקופה", decoration="frosted_stripes")] * 4
        result = quote(Draft("פינתי 2 קבועים + 2 דלתות", panels,
                             decoration="frosted_stripes"))
        self.assertEqual(result["frosted_decoration_charge"], "240.00")
        self.assertEqual(result["price_before_vat"], "2884.00")
        with self.assertRaises(NeedsReview):
            quote(Draft("פינתי 2 קבועים + 2 דלתות", panels,
                        decoration="frosted_middle"))
