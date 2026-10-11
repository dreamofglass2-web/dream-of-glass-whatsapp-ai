import copy
import tempfile
import unittest
from pathlib import Path

from quote_lab.builder import NamedPanel
from quote_lab.customer_preview import render_current_preview
from quote_lab.durable_store import DurableQuoteStore
from quote_lab.universal import NeedsReview
from quote_lab.workflow import create_offline_quote


class PreviewFingerprintIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DurableQuoteStore(Path(self.temp.name) / "quotes.db")
        self.panes = [NamedPanel("door", 90, 200, "שקופה")] * 2
        self.record = create_offline_quote(
            self.store, "fingerprint-case", "פינתי 2 דלתות",
            self.panes, layout_confirmed=True)

    def tearDown(self):
        self.temp.cleanup()

    def preview(self, record=None, panels=None):
        return render_current_preview(
            self.store, record if record is not None else self.record,
            template="פינתי 2 דלתות",
            panels=panels if panels is not None else self.panes,
            finish="ניקל")

    def test_untouched_approved_draft_is_previewable(self):
        result = self.preview()
        self.assertIn("2,504.00", result["text"])
        self.assertFalse(result["send_authorized"])

    def test_modified_panel_shape_fails_even_when_area_unchanged(self):
        panes = [NamedPanel("door", 90, 200, "שקופה", shape="step_notch"), self.panes[1]]
        with self.assertRaises(NeedsReview):
            self.preview(panels=panes)

    def test_modified_calculated_glass_fails_fingerprint(self):
        modified = copy.deepcopy(self.record)
        modified["calculation"]["panel_breakdown"][0]["glass"] = "אקסטרה קליר"
        panes = [NamedPanel("door", 90, 200, "אקסטרה קליר"), self.panes[1]]
        with self.assertRaises(NeedsReview):
            self.preview(record=modified, panels=panes)

    def test_price_catalog_tamper_fails(self):
        modified = copy.deepcopy(self.record)
        modified["calculation"]["catalog_version"] = "unapproved-later"
        with self.assertRaises(NeedsReview):
            self.preview(record=modified)


if __name__ == "__main__":
    unittest.main()
