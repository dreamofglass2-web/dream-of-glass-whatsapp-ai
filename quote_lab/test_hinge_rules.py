import unittest
from quote_lab.hinge_rules import door_hinge_bill
from quote_lab.universal import NeedsReview


class HingesForDoorsTests(unittest.TestCase):
    def test_door_on_fixed_glass(self):
        bill = door_hinge_bill("fixed_glass")
        self.assertEqual(bill["hinge_type"], "ציר זכוכית זכוכית")
        self.assertEqual(bill["quantity"], 2)
        self.assertEqual(bill["supplier_cost_nis"], 150)
        self.assertEqual(bill["prima_hinge_count"], 0)

    def test_door_on_wall(self):
        bill = door_hinge_bill("wall")
        self.assertEqual(bill["hinge_type"], "ציר קיר זכוכית")
        self.assertEqual(bill["supplier_cost_nis"], 100)

    def test_two_glass_mounted_doors(self):
        bill = door_hinge_bill("fixed_glass", 2)
        self.assertEqual(bill["quantity"], 4)
        self.assertEqual(bill["supplier_cost_nis"], 300)

    def test_unapproved_connection_rejected(self):
        with self.assertRaises(NeedsReview):
            door_hinge_bill("prima")
        with self.assertRaises(NeedsReview):
            door_hinge_bill("unknown")


if __name__ == "__main__":
    unittest.main()
