"""Synthetic end-to-end quote simulation. No WhatsApp, AI or customer access.

Delivery/approval events here are deliberately simulated evidence. This is NOT a
Meta webhook verifier or permission to mark real customer quotes delivered.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import tempfile

from quote_lab.builder import NamedPanel
from quote_lab.durable_store import DurableQuoteStore, QuoteStoreError
from quote_lab.workflow import create_offline_quote, restore_offline_quote


@dataclass(frozen=True)
class SimulatedDelivery:
    quote_id: str
    version: int
    message_id: str
    status: str


@dataclass(frozen=True)
class SimulatedApproval:
    quote_id: str
    version: int
    event_id: str
    specification_fingerprint: str
    amount: str
    accepts_price: bool
    accepts_specification: bool


class QuoteSimulation:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _identity(quote_id):
        if not isinstance(quote_id, str) or not quote_id.startswith("simulation-"):
            raise QuoteStoreError("Simulation quote identity required")

    def create(self, quote_id, template, panels, **preferences):
        self._identity(quote_id)
        return create_offline_quote(self.store, quote_id, template, panels, **preferences)

    def _current(self, quote_id, version):
        self._identity(quote_id)
        row = self.store.latest(quote_id)
        if row is None or row["version"] != version:
            raise QuoteStoreError("Simulated event references an old or missing quote")
        return row

    @staticmethod
    def _message_id(row):
        binding = json.dumps([row["quote_id"], row["version"], row["specification"],
                              row["price_before_vat"]], separators=(",", ":"))
        return "sim-message-" + hashlib.sha256(binding.encode()).hexdigest()

    def queue_preview(self, quote_id, version):
        row = self._current(quote_id, version)
        record = restore_offline_quote(self.store, quote_id)
        return {"quote_id": quote_id, "version": version,
                "message_id": self._message_id(row), "text": record["customer_preview_text"],
                "transport": "simulated_only", "status": "queued",
                "send_authorized": False}

    def delivery(self, event: SimulatedDelivery):
        if not isinstance(event, SimulatedDelivery):
            raise QuoteStoreError("Typed simulated delivery required")
        row = self._current(event.quote_id, event.version)
        if event.message_id != self._message_id(row):
            raise QuoteStoreError("Simulated message must match exact quote version")
        if event.status not in ("queued", "accepted", "sent", "failed", "delivered", "read"):
            raise QuoteStoreError("Unknown simulated delivery status")
        if event.status in ("queued", "accepted", "sent", "failed"):
            return row  # API acceptance and transport 'sent' do not prove delivery.
        if row["state"] in ("sent", "approved") and row["delivery_ref"] == event.message_id:
            return row  # Repeat receipt is idempotent, never a status downgrade.
        restore_offline_quote(self.store, event.quote_id)
        return self.store.mark_sent(event.quote_id, event.version, event.message_id)

    def approve(self, event: SimulatedApproval):
        if not isinstance(event, SimulatedApproval):
            raise QuoteStoreError("Typed simulated customer approval required")
        row = self._current(event.quote_id, event.version)
        if (not isinstance(event.event_id, str) or not event.event_id.startswith("sim-approval-")
                or not event.event_id.removeprefix("sim-approval-").strip()
                or event.accepts_price is not True or event.accepts_specification is not True):
            raise QuoteStoreError("Explicit synthetic approval of both price and specification required")
        try:
            amount = Decimal(str(event.amount))
        except (TypeError, InvalidOperation):
            raise QuoteStoreError("Invalid simulated approval price") from None
        if (not amount.is_finite() or event.specification_fingerprint != row["specification"]
                or amount != Decimal(row["price_before_vat"])):
            raise QuoteStoreError("Simulated approval differs from exact quote price or specification")
        if row["state"] == "approved" and row["approval_ref"] == event.event_id:
            return row
        return self.store.mark_approved(event.quote_id, event.version,
                                        event.specification_fingerprint, event.amount, event.event_id)


def run_owner_simulation(store, *, quote_id="simulation-owner-review"):
    """Run owner benchmarks and revisions, returning customer-safe review evidence."""
    simulation = QuoteSimulation(store)
    panels = [NamedPanel("door", 90, 200, "אנטיסן ברונזה")] * 2
    template = "פינתי 2 דלתות"
    original = simulation.create(quote_id, template, panels, layout_confirmed=True)
    if original["version"] != 1:
        raise QuoteStoreError("Use a fresh synthetic quote ID for a review run")
    checks = []
    def blocked(label, action):
        try:
            action()
        except QuoteStoreError:
            checks.append({"check": label, "result": "blocked_as_expected"})
        else:
            raise AssertionError("Unsafe simulated operation was not blocked: " + label)
    approval = SimulatedApproval(quote_id, 1, "sim-approval-" + quote_id,
                                 original["specification_fingerprint"], "2828.00", True, True)
    blocked("approval_before_delivery", lambda: simulation.approve(approval))
    queued = simulation.queue_preview(quote_id, 1)
    message_id = queued["message_id"]
    for status in ("queued", "accepted", "sent", "failed"):
        row = simulation.delivery(SimulatedDelivery(quote_id, 1, message_id, status))
        if row["state"] != "draft":
            raise AssertionError("Non-delivery transport status changed quote state")
    checks.append({"check": "api_acceptance_is_not_delivery", "result": "passed"})
    delivered = SimulatedDelivery(quote_id, 1, message_id, "delivered")
    if simulation.delivery(delivered)["state"] != "sent":
        raise AssertionError("Simulated delivery must mark quote sent")
    blocked("price_only_approval", lambda: simulation.approve(SimulatedApproval(
        quote_id, 1, "sim-approval-price-only", original["specification_fingerprint"], "2828", True, False)))
    if simulation.approve(approval)["state"] != "approved":
        raise AssertionError("Exact explicit simulated approval must be recorded")
    if simulation.delivery(delivered)["state"] != "approved" or simulation.approve(approval)["state"] != "approved":
        raise AssertionError("Duplicate evidence must not downgrade or change approval")
    checks.append({"check": "duplicate_receipts_and_approval_are_idempotent", "result": "passed"})
    changes = [dict(decoration="frosted_middle"),
               dict(decoration="frosted_middle", handle_style="ידית מגבת"),
               dict(decoration="frosted_middle", handle_style="ידית מגבת", demolition_and_disposal=True)]
    records = [original]
    for options in changes:
        records.append(simulation.create(quote_id, template, panels, layout_confirmed=True, **options))
    blocked("old_version_approval_after_change", lambda: simulation.approve(approval))
    blocked("old_delivery_after_change", lambda: simulation.delivery(delivered))
    latest = records[-1]
    current = store.latest(quote_id)
    if current["state"] != "draft" or current["delivery_ref"] is not None or current["approval_ref"] is not None:
        raise AssertionError("Changed specification inherited delivery or approval")
    restored = restore_offline_quote(store, quote_id)
    if restored != latest:
        raise AssertionError("Current draft did not restore exactly")
    checks.append({"check": "latest_draft_restores_exactly", "result": "passed"})
    if [r["price_before_vat"] for r in records] != ["2828.00", "3098.00", "3198.00", "3448.00"]:
        raise AssertionError("Owner simulation prices changed")
    four = [NamedPanel("fixed", 40, 200, "שקופה")] * 2 + [NamedPanel("door", 40, 200, "שקופה")] * 2
    second = simulation.create(quote_id + "-four", "פינתי 2 קבועים + 2 דלתות", four, layout_confirmed=True)
    if second["price_before_vat"] != "2644.00":
        raise AssertionError("Four-panel owner benchmark changed")
    return {"mode": "simulation_only", "real_messages_sent": 0,
            "delivery_and_approval_evidence": "synthetic_only",
            "price_basis": "ILS before VAT", "checks": checks,
            "versions": [{"version": record["version"], "price_before_vat": record["price_before_vat"],
                          "state": store.history(quote_id)[record["version"] - 1]["state"],
                          "customer_text": record["customer_preview_text"]} for record in records],
            "four_panel_reference": {"price_before_vat": second["price_before_vat"],
                                     "customer_text": second["customer_preview_text"]}}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        result = run_owner_simulation(DurableQuoteStore(Path(directory) / "simulation.sqlite3"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
