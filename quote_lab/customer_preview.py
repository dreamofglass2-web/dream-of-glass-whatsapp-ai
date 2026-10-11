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
    if finish not in FINISH or finish != draft_record.get("preview_finish") or not panels:
        raise NeedsReview("Unpriced or incomplete specification")
    calculation = draft_record.get("calculation") or {}
    if calculation.get("status") != "draft_not_sent":
        raise NeedsReview("Unverified quotation")
    if calculation.get("configuration") != template or draft_record.get("price_before_vat") != calculation.get("price_before_vat"):
        raise NeedsReview("Preview must match the calculated draft")
    expected = calculation.get("panel_breakdown") or []
    if len(expected) != len(panels) or any(
        entry.get("role") != p.role or entry.get("glass") != p.glass
        or Decimal(entry.get("width_cm")) != Decimal(str(p.width_cm))
        or Decimal(entry.get("height_cm")) != Decimal(str(p.height_cm))
        for entry, p in zip(expected, panels)
    ):
        raise NeedsReview("Panel details differ from approved calculation")
    if bool(Decimal(str(calculation.get("removal_and_disposal_before_vat", "0")))) != demolition_and_disposal:
        raise NeedsReview("Removal scope differs from calculated draft")
    amount = Decimal(str(draft_record.get("price_before_vat")))
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


def render_current_preview(store, draft_record, *, template, panels, finish,
                           demolition_and_disposal=False):
    """Only preview the currently stored unsent version and exact fingerprint.

    This is a local/offline preview guard, never a sending authorization.
    """
    current = store.latest(draft_record.get("quote_id"))
    if current is None:
        raise NeedsReview("Quote does not exist in the offline store")
    if current["version"] != draft_record.get("version") or current["state"] != "draft":
        raise NeedsReview("Outdated or already sent quote cannot be previewed")
    if (current["specification"] != draft_record.get("specification_fingerprint")
            or current["price_before_vat"] != draft_record.get("price_before_vat")
            or current["catalog_version"] != draft_record.get("catalog_version")):
        raise NeedsReview("Stored quote differs from the supplied preview data")
    return render_customer_preview(
        draft_record, template=template, panels=panels, finish=finish,
        demolition_and_disposal=demolition_and_disposal)
