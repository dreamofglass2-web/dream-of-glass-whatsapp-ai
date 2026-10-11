import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from quote_lab.builder import NamedPanel
from quote_lab.durable_store import DurableQuoteStore, QuoteStoreError
from quote_lab.universal import NeedsReview
from quote_lab.workflow import create_offline_quote


def pane(role, width, glass="שקופה"):
    return NamedPanel(role, width, 200, glass)


class FullOfflineQuoteWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "quote_lab_only.sqlite3"
        self.store = DurableQuoteStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_draft_persists_across_restart_and_matches_owner(self):
        panels = [pane("fixed", 40), pane("fixed", 40),
                  pane("door", 40), pane("door", 40)]
        proposal = create_offline_quote(
            self.store, "lead-test", "פינתי 2 קבועים + 2 דלתות",
            panels, layout_confirmed=True)
        self.assertEqual(proposal["price_before_vat"], "2644.00")
        self.assertEqual(proposal["state"], "draft")
        self.assertFalse(proposal["can_send_whatsapp"])
        self.assertFalse(proposal["can_approve"])
        db_after_restart = DurableQuoteStore(self.path)
        saved = db_after_restart.latest("lead-test")
        self.assertEqual(saved["version"], 1)
        self.assertEqual(saved["state"], "draft")
        self.assertEqual(saved["price_before_vat"], "2644.00")

    def test_reject_incomplete_layout_without_durable_draft(self):
        with self.assertRaises(NeedsReview):
            create_offline_quote(
                self.store, "lead-test", "פינתי 2 קבועים + 2 דלתות",
                [pane("fixed", 40), pane("door", 40)],
                layout_confirmed=True)
        self.assertIsNone(self.store.latest("lead-test"))

    def test_no_quote_before_layout_confirmation(self):
        with self.assertRaises(NeedsReview):
            create_offline_quote(
                self.store, "lead-test", "פינתי 2 דלתות",
                [pane("door", 90), pane("door", 90)])
        self.assertIsNone(self.store.latest("lead-test"))

    def test_new_price_and_material_creates_new_version(self):
        two = [pane("door", 90), pane("door", 90)]
        first = create_offline_quote(self.store, "lead-test", "פינתי 2 דלתות",
                                     two, layout_confirmed=True)
        changed = [pane("door", 90, "אקסטרה קליר"),
                   pane("door", 90, "אקסטרה קליר")]
        second = create_offline_quote(self.store, "lead-test", "פינתי 2 דלתות",
                                      changed, layout_confirmed=True)
        self.assertEqual(second["version"], 2)
        self.assertNotEqual(first["price_before_vat"], second["price_before_vat"])
        self.assertNotEqual(first["specification_fingerprint"],
                            second["specification_fingerprint"])
        with self.assertRaises(QuoteStoreError):
            self.store.mark_sent("lead-test", 1, "old-version-proof")
        self.assertEqual(self.store.latest("lead-test")["state"], "draft")

    def test_removal_is_opt_in_and_quote_has_correct_addition(self):
        two = [pane("door", 90), pane("door", 90)]
        no = create_offline_quote(self.store, "lead-test", "פינתי 2 דלתות",
                                  two, layout_confirmed=True)
        yes = create_offline_quote(self.store, "lead-test", "פינתי 2 דלתות",
                                   two, layout_confirmed=True,
                                   demolition_and_disposal=True)
        self.assertEqual(Decimal(yes["price_before_vat"]) -
                         Decimal(no["price_before_vat"]), Decimal(250))

    def test_fingerprint_stable_for_same_inputs(self):
        panels = [pane("door", 90), pane("door", 90)]
        first = create_offline_quote(self.store, "lead-test", "פינתי 2 דלתות",
                                     panels, layout_confirmed=True)
        second = create_offline_quote(self.store, "lead-test", "פינתי 2 דלתות",
                                      panels, layout_confirmed=True)
        self.assertEqual(first["specification_fingerprint"],
                         second["specification_fingerprint"])


if __name__ == "__main__":
    unittest.main()
