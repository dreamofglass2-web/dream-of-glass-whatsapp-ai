"""Offline, conservative panel-by-panel quote builder.

This module never sends a quote, reads WhatsApp or modifies the live CRM.
A suggestion is not a verified, customer-accepted layout. No invented panel widths.
"""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from quote_lab.universal import Draft, NeedsReview, Panel, PANEL_COUNT, REVIEW_ONLY_LAYOUTS, BASE_TEMPLATES, quote
from quote_lab.hinge_rules import door_hinge_bill

PANEL_ROLES = {
    "פינתי 2 קבועים + 2 דלתות": ("fixed", "fixed", "door", "door"),
    "פינתי 2 דלתות": ("door", "door"),
    "פינתי קבוע + דלת": ("fixed", "door"),
    "חזית קבוע + דלת": ("fixed", "door"),
    "חזית 2 דלתות": ("door", "door"),
    "פינתי 2 קבועים + דלת": ("fixed", "fixed", "door"),
    "קבוע בלבד": ("fixed",),
    "אמבטיון קבוע + דלת": ("fixed", "door"),
    "אמבטיון 2 קבועים + דלת": ("fixed", "fixed", "door"),
    "אמבטיון קבוע + 2 דלתות": ("fixed", "door", "door"),
}


# Approved defaults inherited from the existing price templates. This controls
# item selection, not structural engineering, and needs no customer questionnaire.
DEFAULT_DOOR_ATTACHMENTS = {
    "פינתי 2 קבועים + 2 דלתות": ("fixed_glass", "fixed_glass"),
    "פינתי 2 דלתות": ("wall", "wall"),
    "פינתי קבוע + דלת": ("wall",),
    "חזית קבוע + דלת": ("wall",),
    "חזית 2 דלתות": ("wall", "wall"),
    "פינתי 2 קבועים + דלת": ("fixed_glass",),
    "קבוע בלבד": (),
    "אמבטיון קבוע + דלת": ("fixed_glass",),
    "אמבטיון 2 קבועים + דלת": ("fixed_glass",),
    "אמבטיון קבוע + 2 דלתות": ("wall", "fixed_glass"),
}


def verify_default_door_hardware(template: str) -> list[dict]:
    """Require the counted door hinges to exactly match the approved template."""
    if template not in DEFAULT_DOOR_ATTACHMENTS:
        raise NeedsReview("No approved hinge mapping for this layout")
    mappings = DEFAULT_DOOR_ATTACHMENTS[template]
    expected_doors = PANEL_ROLES[template].count("door")
    if len(mappings) != expected_doors:
        raise NeedsReview("Door attachment count does not match glass plan")
    bills = [door_hinge_bill(mount) for mount in mappings]
    from collections import Counter as HardwareCounter
    aggregate = HardwareCounter()
    for bill in bills:
        aggregate[bill["hinge_type"]] += bill["quantity"]
    bom = BASE_TEMPLATES[template]
    for hinge in ("ציר קיר זכוכית", "ציר זכוכית זכוכית", "ציר פרימה"):
        if aggregate[hinge] != bom.get(hinge, 0):
            raise NeedsReview("Hinge attachments contradict approved hardware template")
    return bills


@dataclass(frozen=True)
class NamedPanel:
    role: str
    width_cm: object
    height_cm: object
    glass: str
    shape: str = "rectangle"


def decimal_dimension(value) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        raise NeedsReview("Panel dimension is missing or not numeric") from None
    if not parsed.is_finite() or parsed <= 0:
        raise NeedsReview("Panel dimension must be positive and finite")
    return parsed


def validate_panel_plan(template: str, panels: list[NamedPanel], *,
                        layout_confirmed: bool = False) -> tuple[Panel, ...]:
    """Validate explicit pane roles and quantities; never infer a split."""
    if template in REVIEW_ONLY_LAYOUTS or template not in PANEL_ROLES:
        raise NeedsReview("Layout requires owner-approved panel-role mapping")
    expected = Counter(PANEL_ROLES[template])
    actual = Counter(p.role for p in panels)
    if expected != actual or len(panels) != PANEL_COUNT[template]:
        raise NeedsReview("Missing or inconsistent fixed/door panels")
    result = []
    for pane in panels:
        if pane.shape not in ("rectangle", "step_notch"):
            raise NeedsReview("Special glass shape requires personal review")
        result.append(Panel(width_cm=decimal_dimension(pane.width_cm),
                            height_cm=decimal_dimension(pane.height_cm),
                            glass=pane.glass, shape=pane.shape))
    # Even with an adequate quote draft, a real installation still requires site verification.
    if not layout_confirmed:
        raise NeedsReview("Proposed panel dimensions must be confirmed before calculating a draft price")
    return tuple(result)


def price_proposed_layout(template: str, panels: list[NamedPanel], *,
                          layout_confirmed: bool = False,
                          step_notch_measured: bool = False,
                          finish: str = "ניקל",
                          demolition_and_disposal: bool = False) -> dict:
    """Calculate an offline DRAFT after explicit layout confirmation only."""
    checked = validate_panel_plan(template, panels, layout_confirmed=layout_confirmed)
    hinge_bills = verify_default_door_hardware(template)
    result = quote(Draft(template=template, panels=list(checked), finish=finish,
                         demolition_and_disposal=demolition_and_disposal,
                         measured_and_engineered=step_notch_measured))
    return {
        **result, "door_hinge_breakdown": hinge_bills, "panel_breakdown": [
            {"role": p.role, "width_cm": str(decimal_dimension(p.width_cm)),
             "height_cm": str(decimal_dimension(p.height_cm)), "glass": p.glass,
             "shape": p.shape}
            for p in panels],
        "layout_confirmed_for_draft": True,
        "engineering_approval": False,
        "send_authorized": False,
    }
