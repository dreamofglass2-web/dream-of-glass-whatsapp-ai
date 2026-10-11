import tempfile
import unittest
from pathlib import Path

from quote_lab.builder import NamedPanel
from quote_lab.customer_preview import render_customer_preview
from quote_lab.durable_store import DurableQuoteStore
from quote_lab.universal import NeedsReview
from quote_lab.workflow import create_offline_quote


class CustomerPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DurableQuoteStore(Path(self.temp.name) / "drafts.db")

    def tearDown(self):
        self.temp.cleanup()

    def _draft(self, glass="שקופה", removal=False):
        panes = [NamedPanel("door", 90, 200, glass)] * 2
        record = create_offline_quote(self.store, "test-001", "פינתי 2 דלתות",
                                      panes, layout_confirmed=True,
                                      demolition_and_disposal=removal)
        return record, panes

    def test_customer_text_hides_vendor_cost_and_shows_final_price(self):
        draft, panels = self._draft(glass="אנטיסן ברונזה")
        preview = render_customer_preview(draft, template="פינתי 2 דלתות",
                                          panels=panels, finish="ניקל")
        self.assertIn("2,828.00 ₪", preview["text"])
        self.assertIn("אנטיסן ברונזה", preview["text"])
        self.assertIn("כפוף למדידה סופית", preview["text"])
        self.assertNotIn("עלות ספק", preview["text"])
        self.assertNotIn("314", preview["text"])
        self.assertNotIn("1,500", preview["text"])
        self.assertFalse(preview["send_authorized"])

    def test_optional_disposal_only_when_requested(self):
        draft, panes = self._draft(removal=True)
        preview = render_customer_preview(draft, template="פינתי 2 דלתות",
                                          panels=panes, finish="ניקל",
                                          demolition_and_disposal=True)
        self.assertIn("פירוק ופינוי", preview["text"])
        with self.assertRaises(NeedsReview):
            render_customer_preview(draft, template="פינתי 2 דלתות",
                                    panels=panes, finish="ניקל")

    def test_changed_glass_or_panel_requires_new_calculation(self):
        draft, panes = self._draft()
        with self.assertRaises(NeedsReview):
            render_customer_preview(draft, template="פינתי 2 דלתות",
                                    panels=[NamedPanel("door", 90, 200, "אקסטרה קליר"),
                                            panes[1]], finish="ניקל")
        with self.assertRaises(NeedsReview):
            render_customer_preview(draft, template="פינתי 2 דלתות",
                                    panels=panes, finish="ניקל",
                                    demolition_and_disposal=True)

    def test_preview_refuses_send_enabled_flag(self):
        draft, panes = self._draft()
        draft["can_send_whatsapp"] = True
        with self.assertRaises(NeedsReview):
            render_customer_preview(draft, template="פינתי 2 דלתות",
                                    panels=panes, finish="ניקל")


if __name__ == "__main__":
    unittest.main()
