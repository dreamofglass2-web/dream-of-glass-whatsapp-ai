import tempfile
import unittest
from pathlib import Path

from quote_lab.durable_store import DurableQuoteStore, QuoteStoreError


class QuoteApprovalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = DurableQuoteStore(Path(self.temp.name) / "test_quotes.sqlite3")
        self.db.create_draft("q1", "specification-one", "2644.00", "catalog-v1")
        self.db.create_draft("q2", "specification-two", "2828.00", "catalog-v1")
        self.db.mark_sent("q1", 1, "delivery-001")
        self.db.mark_sent("q2", 1, "delivery-002")

    def tearDown(self):
        self.temp.cleanup()

    def test_same_customer_approval_evidence_cannot_approve_two_quotes(self):
        self.db.mark_approved("q1", 1, "specification-one", "2644.00", "customer-approval-001")
        with self.assertRaises(QuoteStoreError):
            self.db.mark_approved("q2", 1, "specification-two", "2828.00", "customer-approval-001")
        self.assertEqual(self.db.latest("q1")["state"], "approved")
        self.assertEqual(self.db.latest("q2")["state"], "sent")

    def test_blank_approval_reference_not_accepted(self):
        for reference in ("", " ", "\t"):
            with self.subTest(reference=reference):
                with self.assertRaises(QuoteStoreError):
                    self.db.mark_approved("q2", 1, "specification-two", "2828.00", reference)
        self.assertEqual(self.db.latest("q2")["state"], "sent")

    def test_blank_delivery_reference_not_accepted(self):
        self.db.create_draft("q3", "specification-three", "2504.00", "catalog-v1")
        for reference in ("", " ", "\t"):
            with self.subTest(reference=reference):
                with self.assertRaises(QuoteStoreError):
                    self.db.mark_sent("q3", 1, reference)
        self.assertEqual(self.db.latest("q3")["state"], "draft")

    def test_approved_quote_remains_approved_after_restart(self):
        self.db.mark_approved("q1", 1, "specification-one", "2644.00", "customer-approval-001")
        restarted = DurableQuoteStore(self.db.path)
        self.assertEqual(restarted.latest("q1")["approval_ref"], "customer-approval-001")
        self.assertEqual(restarted.latest("q1")["state"], "approved")


if __name__ == "__main__":
    unittest.main()
