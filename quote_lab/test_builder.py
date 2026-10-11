import unittest
from decimal import Decimal
from quote_lab.builder import NamedPanel, price_proposed_layout, validate_panel_plan
from quote_lab.universal import NeedsReview


def pane(role, width, height=200, glass="שקופה", shape="rectangle"):
    return NamedPanel(role, width, height, glass, shape)


class PaneBuilderTests(unittest.TestCase):
    def test_corner_four_panes_matches_owner_benchmark(self):
        panels = [pane("fixed", 40), pane("fixed", 40),
                  pane("door", 40), pane("door", 40)]
        result = price_proposed_layout("פינתי 2 קבועים + 2 דלתות", panels,
                                       layout_confirmed=True)
        self.assertEqual(result["price_before_vat"], "2644.00")
        self.assertEqual(len(result["panel_breakdown"]), 4)
        self.assertFalse(result["send_authorized"])
        self.assertFalse(result["engineering_approval"])

    def test_bronze_two_doors_matches_owner_benchmark(self):
        panels = [pane("door", 90, glass="אנטיסן ברונזה"),
                  pane("door", 90, glass="אנטיסן ברונזה")]
        result = price_proposed_layout("פינתי 2 דלתות", panels, layout_confirmed=True)
        self.assertEqual(result["price_before_vat"], "2828.00")

    def test_model_suggestion_must_not_be_priced_until_confirmed(self):
        with self.assertRaises(NeedsReview):
            price_proposed_layout("פינתי 2 דלתות",
                                  [pane("door", 90), pane("door", 90)])

    def test_missing_or_misclassified_panels_rejected(self):
        for panels in (
            [pane("door", 90)],
            [pane("fixed", 90), pane("door", 90)],
            [pane("door", 90), pane("door", 90), pane("fixed", 20)],
        ):
            with self.assertRaises(NeedsReview):
                validate_panel_plan("פינתי 2 דלתות", panels, layout_confirmed=True)

    def test_special_glass_and_nonfinite_dimensions_rejected(self):
        for width in ("NaN", "Infinity", -1, 0, None):
            with self.assertRaises(NeedsReview):
                price_proposed_layout("פינתי 2 דלתות",
                                      [pane("door", width), pane("door", 90)],
                                      layout_confirmed=True)
        with self.assertRaises(NeedsReview):
            price_proposed_layout("פינתי 2 דלתות",
                                  [pane("door", 90, shape="slope"), pane("door", 90)],
                                  layout_confirmed=True)

    def test_step_cut_free_but_requires_verified_measurement(self):
        panels = [pane("door", 90, shape="step_notch"), pane("door", 90)]
        with self.assertRaises(NeedsReview):
            price_proposed_layout("פינתי 2 דלתות", panels, layout_confirmed=True)
        result = price_proposed_layout("פינתי 2 דלתות", panels,
                                       layout_confirmed=True, step_notch_measured=True)
        base = price_proposed_layout("פינתי 2 דלתות",
                                     [pane("door", 90), pane("door", 90)], layout_confirmed=True)
        self.assertEqual(result["price_before_vat"], base["price_before_vat"])

    def test_folding_needs_owner_validation(self):
        with self.assertRaises(NeedsReview):
            price_proposed_layout("פינתי הרמוניקה",
                                  [pane("door", 90), pane("door", 90)],
                                  layout_confirmed=True)

    def test_add_on_does_not_change_core_quote(self):
        panels = [pane("door", 90), pane("door", 90)]
        normal = price_proposed_layout("פינתי 2 דלתות", panels, layout_confirmed=True)
        disposal = price_proposed_layout("פינתי 2 דלתות", panels,
                                         layout_confirmed=True,
                                         demolition_and_disposal=True)
        self.assertEqual(
            Decimal(disposal["price_before_vat"]) - Decimal(normal["price_before_vat"]),
            Decimal(250))
        self.assertEqual(disposal["core_price_before_vat"],
                         normal["core_price_before_vat"])


if __name__ == "__main__":
    unittest.main()
