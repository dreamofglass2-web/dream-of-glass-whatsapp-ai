"""Owner-confirmed Protech default hinge; technical limits are intentionally unknown.

Offline-only metadata. Never imported by production app.py and never changes
the approved supplier cost or authorizes WhatsApp quotation delivery.
"""
from dataclasses import dataclass
from decimal import Decimal
from quote_lab.universal import NeedsReview


@dataclass(frozen=True)
class Hinge:
    brand: str
    model: str
    mounting: str
    plate: str
    min_glass_mm: int
    max_glass_mm: int
    owner_supplier_cost_nis: Decimal
    rated_door_weight_kg: None = None
    rated_max_door_width_cm: None = None
    rated_max_door_height_cm: None = None


DEFAULT_WALL_GLASS_HINGE = Hinge(
    brand="Protech", model="PRO-B103", mounting="wall_to_glass_90",
    plate="half_plate", min_glass_mm=6, max_glass_mm=10,
    owner_supplier_cost_nis=Decimal("50"),
)


def inspect_wall_hinged_door(*, width_cm, height_cm, glass_thickness_mm=8):
    """Return conservative offline advisory, not an engineering approval."""
    hinge = DEFAULT_WALL_GLASS_HINGE
    if not hinge.min_glass_mm <= glass_thickness_mm <= hinge.max_glass_mm:
        raise NeedsReview("Glass thickness outside supplier-listed compatibility")
    if width_cm <= 0 or height_cm <= 0:
        raise NeedsReview("Missing valid door dimensions")
    # Owner practice, not a manufacturer load rating.
    if width_cm <= 70:
        width_note = "typical_owner_preference_70_cm"
    elif width_cm <= 80:
        width_note = "owner_conditional_range_up_to_80_cm"
    else:
        width_note = "review_alternative_split_or_engineering"
    return {
        "manufacturer": hinge.brand,
        "model": hinge.model,
        "plate": hinge.plate,
        "owner_cost_nis": str(hinge.owner_supplier_cost_nis),
        "glass_thickness_compatible": True,
        "preferred_two_hinge_count": 2,
        "width_note": width_note,
        "rated_weight_known": False,
        "manufacturer_load_limit_verified": False,
        "requires_final_site_measurement": True,
        "engineering_approval": False,
        "send_authorized": False,
    }
