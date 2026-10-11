"""Owner-approved default door hinge selection for offline shower quotes.

Not used by production app.py. Select a *replacement* hinge type, never
stack two hinge types for the same door.
"""
from quote_lab.universal import HARDWARE, NeedsReview

HINGES_PER_DOOR = 2
DOOR_CONNECTION_HINGE = {
    "wall": "ציר קיר זכוכית",
    "fixed_glass": "ציר זכוכית זכוכית",
}


def door_hinge_bill(connection: str, doors: int = 1) -> dict:
    if connection not in DOOR_CONNECTION_HINGE:
        raise NeedsReview("Unknown door attachment; requires layout clarification")
    if not isinstance(doors, int) or isinstance(doors, bool) or doors < 1:
        raise NeedsReview("Invalid number of doors")
    hinge = DOOR_CONNECTION_HINGE[connection]
    quantity = HINGES_PER_DOOR * doors
    return {
        "hinge_type": hinge,
        "quantity": quantity,
        "supplier_cost_nis": HARDWARE[hinge] * quantity,
        "prima_hinge_count": 0,
        "note": "Default bill of materials; final installation adjustments handled by owner",
    }
