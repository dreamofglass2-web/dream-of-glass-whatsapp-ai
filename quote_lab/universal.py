"""Offline universal glass quote engine, V1. NEVER imported by production app.py.

This module computes draft quotes for manual review / tests only. It cannot
send WhatsApp messages or modify CRM records. Unknown construction is rejected.
"""
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

GLASS = {
    "שקופה": 150, "אקסטרה קליר": 220, "אנטיסן אפור": 220,
    "פיפיטה": 220, "חלבי": 220, "אסיד": 220,
    "אנטיסן ברונזה": 240, "גלינה קליר": 380, "אסיד קליר": 380,
}
HARDWARE = {
    "ציר קיר זכוכית": 50, "ציר זכוכית זכוכית": 75,
    "ציר הרמוניקה": 85, "ציר פרימה": 100, "ציר סיכורית": 150,
    "ידית כפתור": 30, "ידית מגבת": 80, "ידית 19.2": 80,
    "זווית קיר זכוכית": 25, "זווית זכוכית זכוכית": 30,
    "מוט חיזוק": 65, "מגנט פינתי": 30, "מגנט חזית": 30,
    "אטם בלון": 8, "מגב רצפה": 8, "אטם כיסא": 8,
    "פרופיל אלומיניום": 50,
}
FINISH = {"ניקל": Decimal("1"), **{
    x: Decimal("1.1") for x in
    ("שחור", "ניקל מוברש", "גרפיט", "ברונזה", "זהב", "לבן")
}}
SLIDING_KITS = {"הזזה קבוע + דלת": 600, "הזזה 2 קבועים + 2 דלתות": 1200}
BASE_TEMPLATES = {
    "פינתי 2 קבועים + 2 דלתות": {"ציר זכוכית זכוכית": 4, "זווית קיר זכוכית": 4, "אטם בלון": 2, "מגב רצפה": 1, "מגנט פינתי": 1, "ידית כפתור": 2},
    "פינתי 2 דלתות": {"ציר קיר זכוכית": 4, "ידית כפתור": 2, "מגנט פינתי": 1, "אטם בלון": 2, "מגב רצפה": 1},
    "פינתי קבוע + דלת": {"ציר קיר זכוכית": 2, "זווית קיר זכוכית": 2, "ידית כפתור": 1, "אטם בלון": 1, "מגב רצפה": 1, "מגנט פינתי": 1},
    "חזית קבוע + דלת": {"ציר קיר זכוכית": 2, "זווית קיר זכוכית": 2, "מגנט חזית": 1, "אטם בלון": 1, "מגב רצפה": 1, "ידית כפתור": 1},
    "פינתי הרמוניקה": {"ציר הרמוניקה": 4, "ציר קיר זכוכית": 4, "ידית כפתור": 4, "מגנט פינתי": 1, "אטם בלון": 2, "אטם כיסא": 2, "מגב רצפה": 1},
}
# Additional starter templates copied from the existing business BOM. All quotes
# remain offline drafts, subject to actual fitting and owner review.
BASE_TEMPLATES.update({
    "חזית 2 דלתות": {"ציר קיר זכוכית": 4, "ידית כפתור": 2, "מגנט חזית": 1, "אטם בלון": 2, "מגב רצפה": 1},
    "פינתי 2 קבועים + דלת": {"זווית קיר זכוכית": 4, "ציר זכוכית זכוכית": 2, "ידית כפתור": 1, "אטם בלון": 1, "מגנט פינתי": 1, "מגב רצפה": 1},
    "חצי הרמוניקה + חצי קבוע + דלת": {"ציר קיר זכוכית": 2, "ציר זכוכית זכוכית": 2, "ציר הרמוניקה": 2, "ידית כפתור": 2, "ידית מגבת": 1, "מגנט פינתי": 1, "אטם בלון": 2, "אטם כיסא": 1, "מגב רצפה": 1},
    "קבוע בלבד": {"זווית קיר זכוכית": 2, "מוט חיזוק": 1},
    "אמבטיון קבוע + דלת": {"ציר זכוכית זכוכית": 2, "זווית קיר זכוכית": 2, "ידית כפתור": 1, "אטם בלון": 1, "מגב רצפה": 1},
    "אמבטיון 2 קבועים + דלת": {"ציר זכוכית זכוכית": 2, "זווית קיר זכוכית": 4, "מגנט חזית": 1, "מגב רצפה": 1, "אטם בלון": 1, "ידית כפתור": 1},
    "אמבטיון קבוע + 2 דלתות": {"ציר קיר זכוכית": 2, "ציר זכוכית זכוכית": 2, "זווית קיר זכוכית": 2, "מגנט חזית": 1, "מגב רצפה": 1, "אטם בלון": 2, "ידית כפתור": 2},
})
# Only layouts with an unambiguous number of physical glass panes have an
# automatic count check. Others require an explicitly reviewed panel layout.
PANEL_COUNT = {
    "פינתי 2 קבועים + 2 דלתות": 4, "פינתי 2 דלתות": 2,
    "פינתי קבוע + דלת": 2, "פינתי 2 קבועים + דלת": 3,
    "חזית קבוע + דלת": 2, "חזית 2 דלתות": 2,
    "קבוע בלבד": 1, "אמבטיון קבוע + דלת": 2,
    "אמבטיון 2 קבועים + דלת": 3, "אמבטיון קבוע + 2 דלתות": 3,
}
REVIEW_ONLY_LAYOUTS = {"פינתי הרמוניקה", "חצי הרמוניקה + חצי קבוע + דלת"}

CONFIG_VERSION = "offline-v1-2026-10-11"
MINIMUM = Decimal("2000")
FIXED = Decimal("1500")
CONTINGENCY = Decimal("150")
REMOVAL = Decimal("250")


@dataclass(frozen=True)
class Panel:
    width_cm: Decimal
    height_cm: Decimal
    glass: str
    shape: str = "rectangle"  # "step_notch" is billed as full rectangle.
    thickness_mm: int = 8


@dataclass
class Draft:
    template: str
    panels: list[Panel]
    hardware_changes: dict[str, int] = field(default_factory=dict)
    finish: str = "ניקל"
    demolition_and_disposal: bool = False
    measured_and_engineered: bool = False
    special_hardware_approved: bool = False


class NeedsReview(ValueError):
    """Manual review required; never quote on an unsupported assumption."""


def money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def quote(draft: Draft) -> dict:
    if draft.template not in BASE_TEMPLATES and draft.template not in SLIDING_KITS:
        raise NeedsReview("Unknown shower layout; needs approved hardware specification")
    if draft.template in REVIEW_ONLY_LAYOUTS:
        raise NeedsReview("Folding configuration requires panel-layout and fitting review")
    expected_panels = PANEL_COUNT.get(draft.template)
    if expected_panels is not None and len(draft.panels) != expected_panels:
        raise NeedsReview("Number of panels does not match the chosen layout")
    if draft.finish not in FINISH:
        raise NeedsReview("Unpriced hardware finish")
    if not draft.panels:
        raise NeedsReview("Missing glass panel dimensions")
    glass_total = Decimal("0")
    for p in draft.panels:
        if p.glass not in GLASS or p.thickness_mm != 8:
            raise NeedsReview("Glass grade or thickness not approved")
        if p.shape not in ("rectangle", "step_notch"):
            raise NeedsReview("Special cut/angled glass requires professional measurement")
        if p.shape == "step_notch" and not draft.measured_and_engineered:
            raise NeedsReview("Step notch requires verified dimensions before quotation")
        w, h = money(p.width_cm), money(p.height_cm)
        if not (Decimal("0") < w <= 200 and Decimal("0") < h <= 220):
            raise NeedsReview("Panel dimensions outside provisional bounds")
        # Supplier bills the full rectangular blank for a step notch, at no cutting surcharge.
        glass_total += w * h / Decimal("10000") * Decimal(GLASS[p.glass])
    if draft.template in SLIDING_KITS:
        if draft.hardware_changes:
            raise NeedsReview("Sliding kit includes all hardware; do not add parts twice")
        hardware_cost = Decimal(SLIDING_KITS[draft.template])
    else:
        items = BASE_TEMPLATES[draft.template].copy()
        if draft.hardware_changes:
            if not draft.special_hardware_approved:
                raise NeedsReview("Custom hardware list requires approved fitting rules")
            for item, count in draft.hardware_changes.items():
                if item not in HARDWARE or not isinstance(count, int) or count < 0:
                    raise NeedsReview("Unknown or invalid hardware component")
                items[item] = count
        hardware_cost = sum((Decimal(HARDWARE[item]) * count for item, count in items.items()), Decimal("0"))
    # A 10% special-finish retail adjustment; cost and sales are separate in a later margin report.
    hardware_charged = money(hardware_cost * FINISH[draft.finish])
    core = max(MINIMUM, money(glass_total + hardware_charged + FIXED + CONTINGENCY))
    add_on = REMOVAL if draft.demolition_and_disposal else Decimal("0")
    return {
        "status": "draft_not_sent",
        "price_before_vat": str(money(core + add_on)),
        "glass_supplier_cost": str(money(glass_total)),
        "hardware_supplier_base_cost": str(money(hardware_cost)),
        "hardware_retail_charge": str(hardware_charged),
        "core_price_before_vat": str(money(core)),
        "removal_and_disposal_before_vat": str(add_on),
        "catalog_version": CONFIG_VERSION,
        "subject_to_final_measurement": True,
        "no_expiration_promised": True,
        "requires_customer_approval": True,
        "configuration": draft.template,
    }
