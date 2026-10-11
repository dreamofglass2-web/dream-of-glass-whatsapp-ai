import unittest
from quote_lab.versioning import QuoteLedger


class VersionStateTests(unittest.TestCase):
    def setUp(self):
        self.ledger = QuoteLedger()

    def test_draft_does_not_imply_sent(self):
        initial = self.ledger.draft("case1", "two fixed panels plus two doors", "2644.00")
        self.assertEqual(initial.status, "draft")
        with self.assertRaises(ValueError):
            self.ledger.approve("case1", 1, initial.specification, "2644.00", "customer-yes")

    def test_delivery_then_explicit_approval(self):
        self.ledger.draft("case1", "two fixed panels plus two doors", "2644.00")
        sent = self.ledger.mark_sent("case1", 1, "delivered-001")
        self.assertEqual(sent.status, "sent")
        accepted = self.ledger.approve("case1", 1, sent.specification, "2644.00", "customer-approved-001")
        self.assertEqual(accepted.status, "approved")

    def test_no_approval_on_changed_specification_or_price(self):
        self.ledger.draft("case1", "nickel fitting", "2644.00")
        self.ledger.mark_sent("case1", 1, "delivered")
        with self.assertRaises(ValueError):
            self.ledger.approve("case1", 1, "black fitting", "2644.00", "yes")
        with self.assertRaises(ValueError):
            self.ledger.approve("case1", 1, "nickel fitting", "2500.00", "yes")

    def test_new_revision_invalidates_old_approval_workflow(self):
        self.ledger.draft("case1", "clear glass", "2644.00")
        self.ledger.mark_sent("case1", 1, "delivered")
        next_version = self.ledger.draft("case1", "extra clear glass", "2700.00")
        self.assertEqual(next_version.revision, 2)
        self.assertEqual(next_version.status, "draft")
        with self.assertRaises(ValueError):
            self.ledger.approve("case1", 1, "clear glass", "2644.00", "yes")
        with self.assertRaises(ValueError):
            self.ledger.mark_sent("case1", 1, "delivered-old")

    def test_missing_delivery_and_approval_proof(self):
        self.ledger.draft("case1", "clear", "2644.00")
        with self.assertRaises(ValueError):
            self.ledger.mark_sent("case1", 1, "")


if __name__ == "__main__":
    unittest.main()
