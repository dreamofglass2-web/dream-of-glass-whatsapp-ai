"""Validate customer-provided overall spans against explicitly described panes.

Offline-only. It never guesses the door/fixed split and does not certify fitting.
"""
from decimal import Decimal
from quote_lab.builder import NamedPanel, decimal_dimension
from quote_lab.universal import NeedsReview

# Each inner tuple lists the exact expected roles for one side.
CORNER_SIDE_LAYOUTS = {
    "פינתי 2 דלתות": (("door",), ("door",)),
    "פינתי 2 קבועים + 2 דלתות": (("fixed", "door"), ("fixed", "door")),
}


def validate_corner_sides(template: str, side_widths_cm, side_panels):
    """Validate side widths and component sums; return flattened panel plan."""
    if template not in CORNER_SIDE_LAYOUTS:
        raise NeedsReview("Overall side validation not approved for this configuration")
    if len(side_widths_cm) != 2 or len(side_panels) != 2:
        raise NeedsReview("Two corner side measurements and panel groups required")
    flattened = []
    for target, declared, expected_roles in zip(
            side_widths_cm, side_panels, CORNER_SIDE_LAYOUTS[template]):
        expected_width = decimal_dimension(target)
        if expected_width > Decimal("200"):
            raise NeedsReview("Side outside provisional glass bounds")
        if len(declared) != len(expected_roles):
            raise NeedsReview("Pane count doesn't match side")
        if tuple(p.role for p in declared) != expected_roles:
            raise NeedsReview("Fixed/door division must be explicit and correct")
        actual_width = sum((decimal_dimension(p.width_cm) for p in declared), Decimal(0))
        if actual_width != expected_width:
            raise NeedsReview("Pane widths do not add up to the customer's total")
        heights = {decimal_dimension(p.height_cm) for p in declared}
        if len(heights) != 1:
            raise NeedsReview("Height mismatch on the same side needs review")
        flattened.extend(declared)
    return tuple(flattened)
