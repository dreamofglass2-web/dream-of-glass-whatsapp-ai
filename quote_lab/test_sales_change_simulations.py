"""Offline sales conversation changes, without any messaging adapter or customer data."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from quote_lab.builder import NamedPanel
from quote_lab.customer_preview import render_current_preview
from quote_lab.durable_store import DurableQuoteStore, QuoteStoreError
from quote_lab.universal import NeedsReview
from quote_lab.workflow import create_offline_quote


class SalesChangeSimulationTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.store = DurableQuoteStore(Path(self.workspace.name) / "simulated_quotes.db")

    def tearDown(self):
        self.workspace.cleanup()

    def quote_case(self, *, glass="שקופה", finish="ניקל",
                   layout="פינתי 2 דלתות", demolition=False):
        roles = (("fixed", "fixed", "door", "door")
                 if layout == "פינתי 2 קבועים + 2 דלתות" else ("door", "door"))
        pane_width = 40 if len(roles) == 4 else 90
        panes = [NamedPanel(role, pane_width, 200, glass) for role in roles]
        draft = create_offline_quote(
            self.store, "simulation-1", layout, panes,
            layout_confirmed=True, finish=finish,
            demolition_and_disposal=demolition)
        return draft, panes

    def preview(self, draft, panes, *, layout="פינתי 2 דלתות",
                finish="ניקל", demolition=False):
        return render_current_preview(
            self.store, draft, template=layout, panels=panes,
            finish=finish, demolition_and_disposal=demolition)["text"]

    def test_customer_switches_from_clear_to_bronze(self):
        old, old_panes = self.quote_case()
        self.assertIn("2,504.00", self.preview(old, old_panes))
        new, new_panes = self.quote_case(glass="אנטיסן ברונזה")
        with self.assertRaises(NeedsReview):
            self.preview(old, old_panes)
        shown = self.preview(new, new_panes)
        self.assertIn("2,828.00", shown)
        self.assertIn("אנטיסן ברונזה", shown)
        self.assertEqual(new["version"], 2)

    def test_customer_changes_nickel_to_black_finish(self):
        old, panes = self.quote_case()
        new, panes = self.quote_case(finish="שחור")
        self.assertEqual(
            Decimal(new["price_before_vat"]) - Decimal(old["price_before_vat"]),
            Decimal("31.40"))
        with self.assertRaises(NeedsReview):
            self.preview(old, panes)
        shown = self.preview(new, panes, finish="שחור")
        self.assertIn("פרזול: שחור", shown)
        with self.assertRaises(NeedsReview):
            self.preview(new, panes, finish="ניקל")

    def test_demolition_only_after_explicit_request(self):
        first, panes = self.quote_case()
        self.assertNotIn("פירוק ופינוי", self.preview(first, panes))
        second, panes = self.quote_case(demolition=True)
        self.assertEqual(
            Decimal(second["price_before_vat"]) - Decimal(first["price_before_vat"]),
            Decimal("250.00"))
        self.assertIn("פירוק ופינוי",
                      self.preview(second, panes, demolition=True))

    def test_layout_change_replaces_old_version(self):
        first, panes = self.quote_case()
        updated, updated_panes = self.quote_case(
            layout="פינתי 2 קבועים + 2 דלתות")
        self.assertEqual(updated["price_before_vat"], "2644.00")
        self.assertEqual(updated["version"], 2)
        with self.assertRaises(NeedsReview):
            self.preview(first, panes)
        self.assertIn("4. דלת", self.preview(
            updated, updated_panes, layout="פינתי 2 קבועים + 2 דלתות"))

    def test_unsent_quote_cannot_be_customer_approved(self):
        draft, panes = self.quote_case()
        with self.assertRaises(QuoteStoreError):
            self.store.mark_approved("simulation-1", draft["version"],
                                     draft["specification_fingerprint"],
                                     draft["price_before_vat"], "yes")
        self.assertEqual(self.store.latest("simulation-1")["state"], "draft")


if __name__ == "__main__":
    unittest.main()
