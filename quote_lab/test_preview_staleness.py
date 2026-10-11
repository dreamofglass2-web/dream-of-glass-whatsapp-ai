import tempfile
import unittest
from pathlib import Path

from quote_lab.builder import NamedPanel
from quote_lab.customer_preview import render_current_preview
from quote_lab.durable_store import DurableQuoteStore
from quote_lab.universal import NeedsReview
from quote_lab.workflow import create_offline_quote


class OfflinePreviewStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DurableQuoteStore(Path(self.temp.name) / "preview.sqlite3")
        self.panels = [NamedPanel("door", 90, 200, "שקופה")] * 2

    def tearDown(self):
        self.temp.cleanup()

    def draft(self, glass="שקופה", finish="ניקל"):
        panels = [NamedPanel("door", 90, 200, glass)] * 2
        result = create_offline_quote(self.store, "customer-example",
                                      "פינתי 2 דלתות", panels,
                                      finish=finish, layout_confirmed=True)
        return result, panels

    def preview(self, record, panels, finish="ניקל"):
        return render_current_preview(self.store, record,
                                      template="פינתי 2 דלתות",
                                      panels=panels, finish=finish)

    def test_current_version_preview_passes(self):
        draft, panels = self.draft()
        self.assertIn("2,504.00", self.preview(draft, panels)["text"])

    def test_old_draft_cannot_be_shown_after_change(self):
        old, panels = self.draft()
        new, updated = self.draft(glass="אנטיסן ברונזה")
        with self.assertRaises(NeedsReview):
            self.preview(old, panels)
        self.assertIn("2,828.00", self.preview(new, updated)["text"])

    def test_sent_version_cannot_be_passed_off_as_draft(self):
        record, panels = self.draft()
        self.store.mark_sent("customer-example", record["version"], "test-receipt")
        with self.assertRaises(NeedsReview):
            self.preview(record, panels)

    def test_tampered_price_or_spec_fails(self):
        record, panels = self.draft()
        modified = dict(record, price_before_vat="9999.00")
        with self.assertRaises(NeedsReview):
            self.preview(modified, panels)
        modified = dict(record, specification_fingerprint="not-the-saved-hash")
        with self.assertRaises(NeedsReview):
            self.preview(modified, panels)


if __name__ == "__main__":
    unittest.main()
