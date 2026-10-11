"""Customer-readable quote PREVIEW, isolated from WhatsApp and production.

No vendor prices, hardware costs or profitability in the customer text.
"""
from decimal import Decimal
from quote_lab.universal import NeedsReview, FINISH, GLASS


def render_customer_preview(draft_record, *, template, panels, finish,
                            demolition_and_disposal=False):
    if draft_record.get("state") != "draft":
        raise NeedsReview("Only offline draft previews are supported")
    if draft_record.get("can_send_whatsapp") is not False:
        raise NeedsReview("Preview requires an explicitly disabled send flag")
    if finish not in FINISH or not panels:
        raise NeedsReview("Unpriced or incomplete specification")
    calculation = draft_record.get("calculation") or {}
    if calculation.get("status") != "draft_not_sent":
        raise NeedsReview("Unverified quotation")
    if calculation.get("configuration") != template or draft_record.get("price_before_vat") != calculation.get("price_before_vat"):\n        raise NeedsReview("Preview must match the calculated draft")\n    expected = calculation.get("panel_breakdown") or []\n    if len(expected) != len(panels) or any(\n        entry.get("role") != p.role or entry.get("glass") != p.glass\n        or Decimal(entry.get("width_cm")) != Decimal(str(p.width_cm))\n        or Decimal(entry.get("height_cm")) != Decimal(str(p.height_cm))\n        for entry, p in zip(expected, panels)\n    ):\n        raise NeedsReview("Panel details differ from approved calculation")\n    if bool(Decimal(str(calculation.get("removal_and_disposal_before_vat", "0")))) != demolition_and_disposal:\n        raise NeedsReview("Removal scope differs from calculated draft")\n    amount = Decimal(str(draft_record.get("price_before_vat")))
    if not amount.is_finite() or amount <= 0:
        raise NeedsReview("Invalid quote amount")
    glasses = {p.glass for p in panels}
    if any(g not in GLASS for g in glasses):
        raise NeedsReview("Unpriced glass")
    label = ", ".join(sorted(glasses))
    lines = [
        "הצעת מחיר למקלחון — טיוטה לעיון",
        "תצורה: " + template,
        "זכוכית: " + label + " 8 מ״מ",
        "פרזול: " + finish,
        "מידות לוחות לפי המפרט:",
    ]
    for index, panel in enumerate(panels, start=1):
        role = {"fixed": "קבוע", "door": "דלת"}.get(panel.role)
        if role is None:
            raise NeedsReview("Unknown panel role")
        lines.append(f"{index}. {role} — {panel.width_cm}×{panel.height_cm} ס״מ")
    if demolition_and_disposal:
        lines.append("כולל פירוק ופינוי מקלחון ישן, לבקשת הלקוח.")
    lines += [
        f"מחיר כולל לפני מע״מ: {amount:,.2f} ₪",
        "המחיר כפוף למדידה סופית ולאישור המפרט.",
    ]
    return {
        "state": "draft_preview_only",
        "send_authorized": False,
        "text": "\n".join(lines),
        "quote_id": draft_record["quote_id"],
        "version": draft_record["version"],
    }
