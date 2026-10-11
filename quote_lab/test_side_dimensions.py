import unittest

from quote_lab.builder import NamedPanel, price_proposed_layout
from quote_lab.side_dimensions import validate_corner_sides
from quote_lab.universal import NeedsReview


def pane(role, width, height=200, glass="שקופה"):
    return NamedPanel(role, width, height, glass)


class OverallSideValidationTests(unittest.TestCase):
    def test_verified_80_by_80_four_panel_owner_price(self):
        sides = [
            [pane("fixed", 40), pane("door", 40)],
            [pane("fixed", 40), pane("door", 40)],
        ]
        validated = validate_corner_sides(
            "פינתי 2 קבועים + 2 דלתות", (80, 80), sides)
        quote = price_proposed_layout(
            "פינתי 2 קבועים + 2 דלתות",
            list(validated), layout_confirmed=True)
        self.assertEqual(quote["price_before_vat"], "2644.00")

    def test_verified_90_by_90_bronze_two_doors(self):
        sides = [[pane("door", 90, glass="אנטיסן ברונזה")],
                 [pane("door", 90, glass="אנטיסן ברונזה")]]
        validated = validate_corner_sides(
            "פינתי 2 דלתות", (90, 90), sides)
        quote = price_proposed_layout(
            "פינתי 2 דלתות", list(validated), layout_confirmed=True)
        self.assertEqual(quote["price_before_vat"], "2828.00")

    def test_split_can_vary_if_totals_match(self):
        sides = [[pane("fixed", 30), pane("door", 50)],
                 [pane("fixed", 45), pane("door", 35)]]
        validated = validate_corner_sides(
            "פינתי 2 קבועים + 2 דלתות", (80, 80), sides)
        self.assertEqual(len(validated), 4)

    def test_mismatch_does_not_price(self):
        with self.assertRaises(NeedsReview):
            validate_corner_sides(
                "פינתי 2 קבועים + 2 דלתות", (80, 80),
                [[pane("fixed", 30), pane("door", 40)],
                 [pane("fixed", 40), pane("door", 40)]])

    def test_refuses_unconfirmed_role_and_unsupported_layout(self):
        with self.assertRaises(NeedsReview):
            validate_corner_sides(
                "פינתי 2 קבועים + 2 דלתות", (80, 80),
                [[pane("door", 40), pane("fixed", 40)],
                 [pane("fixed", 40), pane("door", 40)]])
        with self.assertRaises(NeedsReview):
            validate_corner_sides("פינתי הרמוניקה", (80, 80), ([], []))

    def test_refuses_nonfinite_or_missing_total(self):
        for bad in ("NaN", "Infinity", None, -80):
            with self.subTest(bad=bad):
                with self.assertRaises(NeedsReview):
                    validate_corner_sides(
                        "פינתי 2 דלתות", (bad, 90),
                        [[pane("door", 90)], [pane("door", 90)]])


if __name__ == "__main__":
    unittest.main()
