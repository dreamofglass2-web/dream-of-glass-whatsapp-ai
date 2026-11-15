"""Compare current production arithmetic with the frozen historical lab catalog.

A single production shower now uses 1500 instead of the lab's historical 1650.
The lab catalog and its existing saved versions remain historical snapshots.

This does not call the running service, create leads, or send customer messages.
"""
import ast
import unittest
from pathlib import Path

from quote_lab.builder import NamedPanel, price_proposed_layout
from sliding_policy import disallowed_slider
from sales_items import pricing_shower_count


def isolated_production_calculator():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text())
    names = {"GLASS_COSTS", "HARDWARE_COSTS", "FINISH_MULTIPLIERS", "BOM", "SLIDING"}
    constants = {}
    calculate = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    constants[target.id] = ast.literal_eval(node.value)
        if isinstance(node, ast.FunctionDef) and node.name == "calculate_quote":
            calculate = node
    if set(constants) != names or calculate is None:
        raise AssertionError("Production calculator structure changed; review comparison")
    constants["disallowed_slider"] = disallowed_slider
    constants["pricing_shower_count"] = pricing_shower_count
    exec(compile(ast.Module(body=[calculate], type_ignores=[]), "<offline pricing comparison>", "exec"), constants)
    return constants["calculate_quote"]


class ProductionArithmeticComparisonTests(unittest.TestCase):
    def setUp(self):
        self.active = isolated_production_calculator()
        self.bronze = [NamedPanel("door", 90, 200, "אנטיסן ברונזה")] * 2
        self.active_input = dict(configuration="פינתי 2 דלתות", glass_type="אנטיסן ברונזה",
                                 finish="ניקל", handles=["ידית כפתור"] * 2,
                                 width_cm=90, second_width_cm=90, height_cm=200)

    def test_owner_benchmarks_match_current_source(self):
        self.assertEqual(self.active(self.active_input), 2678)
        new = price_proposed_layout("פינתי 2 דלתות", self.bronze, layout_confirmed=True)
        self.assertEqual(new["price_before_vat"], "2828.00")
        old_four = dict(self.active_input, configuration="פינתי 2 קבועים + 2 דלתות",
                        glass_type="שקופה", width_cm=80, second_width_cm=80)
        panels = [NamedPanel("fixed", 40, 200, "שקופה")] * 2 + [NamedPanel("door", 40, 200, "שקופה")] * 2
        self.assertEqual(self.active(old_four), 2494)
        self.assertEqual(price_proposed_layout(old_four["configuration"], panels,
                                              layout_confirmed=True)["price_before_vat"], "2644.00")

    def test_frosted_design_is_an_offline_addition(self):
        for design in ["frosted_stripes", "frosted_middle"]:
            self.assertEqual(self.active(dict(self.active_input, decoration=design)), 2678)
            new = price_proposed_layout("פינתי 2 דלתות", self.bronze,
                                        layout_confirmed=True, decoration=design)
            self.assertEqual(new["price_before_vat"], "3098.00")

    def test_explicit_removal_is_an_offline_addition(self):
        self.assertEqual(self.active(dict(self.active_input, demolition_and_disposal=True)), 2678)
        new = price_proposed_layout("פינתי 2 דלתות", self.bronze, layout_confirmed=True,
                                    demolition_and_disposal=True)
        self.assertEqual(new["price_before_vat"], "3078.00")

    def test_towel_handle_replacement_matches_current_source(self):
        self.assertEqual(self.active(dict(self.active_input, handles=["ידית מגבת"] * 2)), 2778)
        new = price_proposed_layout("פינתי 2 דלתות", self.bronze, layout_confirmed=True,
                                    handle_style="ידית מגבת")
        self.assertEqual(new["price_before_vat"], "2928.00")
