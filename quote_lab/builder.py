"""Offline, conservative panel-by-panel quote builder.

This module never sends a quote, reads WhatsApp or modifies the live CRM.
A suggestion is not a verified, customer-accepted layout. No invented panel widths.
"""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from quote_lab.universal import Draft, NeedsReview, Panel, PANEL_COUNT, REVIEW_ONLY_LAYOUTS, quote

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
    result = quote(Draft(template=template, panels=list(checked), finish=finish,
                         demolition_and_disposal=demolition_and_disposal,
                         measured_and_engineered=step_notch_measured))
    return {
        **result, "panel_breakdown": [
            {"role": p.role, "width_cm": str(decimal_dimension(p.width_cm)),
             "height_cm": str(decimal_dimension(p.height_cm)), "glass": p.glass,
             "shape": p.shape}
            for p in panels],
        "layout_confirmed_for_draft": True,
        "engineering_approval": False,
        "send_authorized": False,
    }
