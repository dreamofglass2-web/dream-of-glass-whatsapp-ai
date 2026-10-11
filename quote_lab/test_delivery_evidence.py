import tempfile
import unittest
from pathlib import Path
from quote_lab.durable_store import DurableQuoteStore, QuoteStoreError


class DurableApprovalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DurableQuoteStore(Path(self.temp.name) / "crm_stage.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_delivery_reference_cannot_be_reused_for_another_quote(self):
        self.store.create_draft("q1", "first plan", "2644.00", "v1")
        self.store.create_draft("q2", "second plan", "2828.00", "v1")
        self.store.mark_sent("q1", 1, "verified-delivery-123")
        with self.assertRaises(QuoteStoreError):
            self.store.mark_sent("q2", 1, "verified-delivery-123")
        self.assertEqual(self.store.latest("q2")["state"], "draft")

    def test_approval_price_accepts_equivalent_decimal_formatting(self):
        self.store.create_draft("q1", "corner plan", "2644.00", "v1")
        self.store.mark_sent("q1", 1, "verified-delivery")
        accepted = self.store.mark_approved("q1", 1, "corner plan", "2644.0", "explicit-approval")
        self.assertEqual(accepted["state"], "approved")

    def test_invalid_numeric_approval_never_changes_state(self):
        self.store.create_draft("q1", "corner plan", "2644.00", "v1")
        self.store.mark_sent("q1", 1, "delivered")
        for amount in ("NaN", "Infinity", "not-a-number", None):
            with self.subTest(amount=amount):
                with self.assertRaises(QuoteStoreError):
                    self.store.mark_approved("q1", 1, "corner plan", amount, "yes")
        self.assertEqual(self.store.latest("q1")["state"], "sent")

    def test_in_memory_store_rejected_for_durability(self):
        with self.assertRaises(QuoteStoreError):
            DurableQuoteStore(":memory:")


if __name__ == "__main__":
    unittest.main()
