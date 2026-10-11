import unittest
from decimal import Decimal
from quote_lab.universal import Panel, Draft, quote, NeedsReview


def panel(w=90, h=200, shape="rectangle", glass="שקופה"):
    return Panel(Decimal(w), Decimal(h), glass, shape)


class UniversalCalculatorTests(unittest.TestCase):
    def test_two_door_90x90_example(self):
        d = Draft("פינתי 2 דלתות", [panel(), panel()])
        result = quote(d)
        self.assertEqual(result["price_before_vat"], "2504.00")
        self.assertEqual(result["glass_supplier_cost"], "540.00")
        self.assertEqual(result["hardware_supplier_base_cost"], "314.00")
        self.assertEqual(result["status"], "draft_not_sent")

    def test_owner_verified_corner_two_fixed_two_doors_80(self):
        # Owner quote: 80x80, 200 cm, clear glass, nickel, button handles.
        result = quote(Draft("פינתי 2 קבועים + 2 דלתות",
                             [panel(40, 200), panel(40, 200), panel(40, 200), panel(40, 200)],
                             finish="ניקל"))
        self.assertEqual(result["glass_supplier_cost"], "480.00")
        self.assertEqual(result["hardware_supplier_base_cost"], "514.00")
        self.assertEqual(result["price_before_vat"], "2644.00")

    def test_owner_verified_corner_two_doors_90_bronze(self):
        # Owner confirmed that 'bronze' means Antisun bronze.
        result = quote(Draft("פינתי 2 דלתות",
                             [panel(90, 200, glass="אנטיסן ברונזה"),
                              panel(90, 200, glass="אנטיסן ברונזה")],
                             finish="ניקל"))
        self.assertEqual(result["glass_supplier_cost"], "864.00")
        self.assertEqual(result["hardware_supplier_base_cost"], "314.00")
        self.assertEqual(result["price_before_vat"], "2828.00")

    def test_step_cut_uses_full_blank_no_surcharge(self):
        ordinary = quote(Draft("פינתי 2 דלתות", [panel(), panel()]))
        notched = quote(Draft("פינתי 2 דלתות", [panel(shape="step_notch"), panel()], measured_and_engineered=True))
        self.assertEqual(ordinary["glass_supplier_cost"], notched["glass_supplier_cost"])
        self.assertEqual(ordinary["price_before_vat"], notched["price_before_vat"])

    def test_angled_cut_needs_manual_review(self):
        with self.assertRaises(NeedsReview):
            quote(Draft("פינתי 2 דלתות", [panel(shape="slope"), panel()]))

    def test_missing_unknown_components_fail_closed(self):
        for layout in ("unknown", "פינתי חדש בלי מפרט"):
            with self.assertRaises(NeedsReview):
                quote(Draft(layout, [panel()]))

    def test_sliding_kit_not_double_charged(self):
        kit = quote(Draft("הזזה קבוע + דלת", [panel()]))
        self.assertEqual(kit["hardware_supplier_base_cost"], "600.00")
        with self.assertRaises(NeedsReview):
            quote(Draft("הזזה קבוע + דלת", [panel()], hardware_changes={"ידית כפתור": 1}, special_hardware_approved=True))

    def test_removal_option_separate_and_unrequested_absent(self):
        basic = quote(Draft("פינתי 2 דלתות", [panel(), panel()]))
        with_removal = quote(Draft("פינתי 2 דלתות", [panel(), panel()], demolition_and_disposal=True))
        self.assertEqual(Decimal(with_removal["price_before_vat"]) - Decimal(basic["price_before_vat"]), Decimal(250))
        self.assertEqual(basic["removal_and_disposal_before_vat"], "0")
        self.assertEqual(with_removal["removal_and_disposal_before_vat"], "250")

    def test_hardware_adjustment_requires_approval(self):
        with self.assertRaises(NeedsReview):
            quote(Draft("פינתי 2 דלתות", [panel(), panel()], hardware_changes={"ידית מגבת": 2, "ידית כפתור": 0}))
        d = Draft("פינתי 2 דלתות", [panel(), panel()],
                  hardware_changes={"ידית מגבת": 2, "ידית כפתור": 0},
                  special_hardware_approved=True)
        self.assertEqual(quote(d)["hardware_supplier_base_cost"], "414.00")

    def test_special_finish_only_on_hardware(self):
        basic = quote(Draft("פינתי 2 דלתות", [panel(), panel()]))
        special = quote(Draft("פינתי 2 דלתות", [panel(), panel()], finish="שחור"))
        self.assertEqual(Decimal(special["price_before_vat"]) - Decimal(basic["price_before_vat"]), Decimal("31.40"))

    def test_physical_panel_count_rejects_underdescribed_layout(self):
        with self.assertRaises(NeedsReview):
            quote(Draft("פינתי 2 קבועים + 2 דלתות", [panel(80), panel(80)]))

    def test_all_known_standard_layouts_are_in_library(self):
        from quote_lab.universal import BASE_TEMPLATES
        self.assertEqual(len(BASE_TEMPLATES), 12)

    def test_folding_panel_layout_needs_review(self):
        with self.assertRaises(NeedsReview):
            quote(Draft("פינתי הרמוניקה", [panel(), panel()]))

    def test_regular_bathtub_layout_can_be_quoted_offline(self):
        result = quote(Draft("אמבטיון קבוע + דלת", [panel(50), panel(55)]))
        self.assertEqual(result["status"], "draft_not_sent")
        self.assertGreater(Decimal(result["price_before_vat"]), Decimal(2000))

    def test_minimum(self):
        tiny = quote(Draft("פינתי 2 דלתות", [panel(10, 50), panel(10, 50)]))
        self.assertEqual(tiny["core_price_before_vat"], "2000.00")


if __name__ == "__main__":
    unittest.main()
