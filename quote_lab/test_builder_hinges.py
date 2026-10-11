import unittest

from quote_lab.builder import (
    DEFAULT_DOOR_ATTACHMENTS, NamedPanel, PANEL_ROLES,
    price_proposed_layout, verify_default_door_hardware,
)
from quote_lab.universal import HARDWARE


class HingeBuilderIntegrationTests(unittest.TestCase):
    def test_every_supported_layout_reconciles_with_approved_hinges(self):
        for template in DEFAULT_DOOR_ATTACHMENTS:
            with self.subTest(template=template):
                bills = verify_default_door_hardware(template)
                self.assertEqual(len(bills), PANEL_ROLES[template].count("door"))
                self.assertTrue(all(b["prima_hinge_count"] == 0 for b in bills))
                self.assertTrue(all(b["quantity"] == 2 for b in bills))

    def test_two_fixed_two_doors_counts_four_glass_hinges_once(self):
        panes = [NamedPanel(role, 40, 200, "שקופה")
                 for role in PANEL_ROLES["פינתי 2 קבועים + 2 דלתות"]]
        result = price_proposed_layout("פינתי 2 קבועים + 2 דלתות",
                                       panes, layout_confirmed=True)
        bills = result["door_hinge_breakdown"]
        self.assertEqual(sum(b["quantity"] for b in bills), 4)
        self.assertEqual(sum(b["supplier_cost_nis"] for b in bills), 300)
        self.assertEqual(result["price_before_vat"], "2644.00")

    def test_two_wall_hinged_doors_match_bronze_owner_quote(self):
        panes = [NamedPanel("door", 90, 200, "אנטיסן ברונזה")] * 2
        result = price_proposed_layout("פינתי 2 דלתות",
                                       panes, layout_confirmed=True)
        bills = result["door_hinge_breakdown"]
        self.assertEqual(sum(b["supplier_cost_nis"] for b in bills), 4 * HARDWARE["ציר קיר זכוכית"])
        self.assertEqual(result["price_before_vat"], "2828.00")

    def test_bath_screen_mixed_mounting(self):
        bills = verify_default_door_hardware("אמבטיון קבוע + 2 דלתות")
        self.assertEqual({b["hinge_type"] for b in bills},
                         {"ציר קיר זכוכית", "ציר זכוכית זכוכית"})


if __name__ == "__main__":
    unittest.main()
