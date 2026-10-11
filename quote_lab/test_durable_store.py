import tempfile
import unittest
from pathlib import Path

from quote_lab.durable_store import DurableQuoteStore, QuoteStoreError


class DurableStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "quotes.sqlite3"
        self.db = DurableQuoteStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_persists_across_restarts(self):
        version = self.db.create_draft("q1", "2 fixed 2 doors clear", "2644.00", "v1")
        self.assertEqual(version, 1)
        again = DurableQuoteStore(self.path)
        self.assertEqual(again.latest("q1")["state"], "draft")
        again.mark_sent("q1", 1, "meta-receipt-1")
        third = DurableQuoteStore(self.path)
        self.assertEqual(third.latest("q1")["state"], "sent")
        third.mark_approved("q1", 1, "2 fixed 2 doors clear", "2644.00", "explicit-yes")
        self.assertEqual(DurableQuoteStore(self.path).latest("q1")["state"], "approved")

    def test_no_approval_without_confirmed_send(self):
        self.db.create_draft("q1", "corner", "2828.00", "v1")
        with self.assertRaises(QuoteStoreError):
            self.db.mark_approved("q1", 1, "corner", "2828.00", "yes")
        with self.assertRaises(QuoteStoreError):
            self.db.mark_sent("q1", 1, "")
        self.assertEqual(self.db.latest("q1")["state"], "draft")

    def test_new_version_does_not_inherit_approval(self):
        self.db.create_draft("q1", "clear", "2644.00", "v1")
        self.db.mark_sent("q1", 1, "delivery")
        self.db.mark_approved("q1", 1, "clear", "2644.00", "customer-yes")
        self.assertEqual(self.db.create_draft("q1", "extra-clear", "2868.00", "v1"), 2)
        with self.assertRaises(QuoteStoreError):
            self.db.mark_approved("q1", 1, "clear", "2644.00", "again")
        self.assertEqual(self.db.latest("q1")["state"], "draft")
        self.assertEqual(len(self.db.history("q1")), 2)

    def test_changed_price_or_spec_cannot_be_approved(self):
        self.db.create_draft("q1", "nickel", "2644.00", "v1")
        self.db.mark_sent("q1", 1, "delivered")
        for spec, amount in (("black", "2644.00"), ("nickel", "2645.00")):
            with self.assertRaises(QuoteStoreError):
                self.db.mark_approved("q1", 1, spec, amount, "yes")
        self.assertEqual(self.db.latest("q1")["state"], "sent")

    def test_invalid_values_rejected(self):
        for amount in ("NaN", "Infinity", "-1", "0", "not_a_number"):
            with self.assertRaises(QuoteStoreError):
                self.db.create_draft("q1", "clear", amount, "v1")


if __name__ == "__main__":
    unittest.main()
