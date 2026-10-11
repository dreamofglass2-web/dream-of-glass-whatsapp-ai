import unittest
from quote_lab.protech_hinge import DEFAULT_WALL_GLASS_HINGE, inspect_wall_hinged_door
from quote_lab.universal import NeedsReview


class ProtechHingeTests(unittest.TestCase):
    def test_owner_approved_model_and_price(self):
        hinge = DEFAULT_WALL_GLASS_HINGE
        self.assertEqual(hinge.model, "PRO-B103")
        self.assertEqual(hinge.plate, "half_plate")
        self.assertEqual(str(hinge.owner_supplier_cost_nis), "50")
        self.assertIsNone(hinge.rated_door_weight_kg)

    def test_8mm_70cm_remains_advisory_only(self):
        response = inspect_wall_hinged_door(width_cm=70, height_cm=200)
        self.assertEqual(response["preferred_two_hinge_count"], 2)
        self.assertEqual(response["width_note"], "typical_owner_preference_70_cm")
        self.assertFalse(response["manufacturer_load_limit_verified"])
        self.assertFalse(response["engineering_approval"])
        self.assertFalse(response["send_authorized"])

    def test_width_above_owner_conditional_threshold_escalates(self):
        r = inspect_wall_hinged_door(width_cm=85, height_cm=200)
        self.assertEqual(r["width_note"], "review_alternative_split_or_engineering")

    def test_nonstandard_thickness_is_rejected(self):
        with self.assertRaises(NeedsReview):
            inspect_wall_hinged_door(width_cm=70, height_cm=200, glass_thickness_mm=12)


if __name__ == "__main__":
    unittest.main()
