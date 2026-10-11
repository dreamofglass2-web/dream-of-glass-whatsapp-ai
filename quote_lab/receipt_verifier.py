"""Pure signed-status verification and synthetic integration; no HTTP listener.

The parser neither sends messages nor updates a database. Its fixture bridge is
restricted to QuoteSimulation and fixture-prefixed identities. No app secrets
or production configuration are read. Live webhook wiring is a separate gate.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import re

from quote_lab.durable_store import QuoteStoreError
from quote_lab.simulator import QuoteSimulation, SimulatedDelivery


class ReceiptError(ValueError):
    pass


@dataclass(frozen=True)
class OutboundBinding:
    message_id: str
    recipient_id: str
    quote_id: str
    version: int
    specification_fingerprint: str
    amount: str


@dataclass(frozen=True)
class VerifiedDelivery:
    binding: OutboundBinding
    status: str
    timestamp: str


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReceiptError("Duplicate JSON keys in signed payload")
        result[key] = value
    return result


def verify_status_webhook(raw_body, signature, *, app_secret, account_id, phone_number_id, bindings):
    """Validate raw bytes first and return only matching delivered/read statuses.

    Unknown messages and other accounts/phone IDs are ignored. A known message
    with inconsistent recipient/shape is rejected before any side effects.
    Unrelated extra provider fields are allowed; no text is interpreted as consent.
    """
    if (not isinstance(raw_body, bytes) or len(raw_body) > 1_000_000
            or not isinstance(app_secret, bytes) or len(app_secret) < 16
            or not isinstance(signature, str) or not re.fullmatch(r"sha256=[0-9a-f]{64}", signature)
            or not isinstance(account_id, str) or not account_id
            or not isinstance(phone_number_id, str) or not phone_number_id):
        raise ReceiptError("Invalid receipt verification input")
    expected = "sha256=" + hmac.new(app_secret, raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ReceiptError("Invalid webhook signature")
    registered = {}
    for binding in bindings:
        if not isinstance(binding, OutboundBinding):
            raise ReceiptError("Typed outbound quote binding required")
        try:
            amount = Decimal(binding.amount)
            if (not all(isinstance(value, str) and value for value in
                        (binding.message_id, binding.recipient_id, binding.quote_id))
                    or type(binding.version) is not int or binding.version < 1
                    or not isinstance(binding.specification_fingerprint, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", binding.specification_fingerprint)
                    or not amount.is_finite() or amount <= 0):
                raise ReceiptError("Invalid outbound quote binding")
        except (TypeError, InvalidOperation):
            raise ReceiptError("Invalid outbound quote amount") from None
        if binding.message_id in registered:
            raise ReceiptError("Ambiguous duplicate outbound message binding")
        registered[binding.message_id] = binding
    try:
        payload = json.loads(raw_body, object_pairs_hook=_unique_object,
                             parse_constant=lambda _: (_ for _ in ()).throw(ReceiptError("Nonfinite JSON")))
        if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
            raise ReceiptError("Wrong webhook object")
        entries = payload["entry"]
        if not isinstance(entries, list):
            raise ReceiptError("Invalid webhook entries")
        receipts = []
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ReceiptError("Invalid webhook entry")
            if entry.get("id") != account_id:
                continue
            changes = entry["changes"]
            if not isinstance(changes, list):
                raise ReceiptError("Invalid webhook changes")
            for change in changes:
                if not isinstance(change, dict):
                    raise ReceiptError("Invalid webhook change")
                if change.get("field") != "messages":
                    continue
                value = change["value"]
                if not isinstance(value, dict) or value.get("messaging_product") != "whatsapp":
                    raise ReceiptError("Wrong messaging product")
                if value["metadata"]["phone_number_id"] != phone_number_id:
                    continue
                statuses = value.get("statuses", [])
                if not isinstance(statuses, list):
                    raise ReceiptError("Invalid status list")
                for status in statuses:
                    if not isinstance(status, dict):
                        raise ReceiptError("Invalid delivery status")
                    message_id = status.get("id")
                    if not isinstance(message_id, str):
                        raise ReceiptError("Invalid provider message identity")
                    binding = registered.get(message_id)
                    if binding is None:
                        continue
                    if status.get("recipient_id") != binding.recipient_id:
                        raise ReceiptError("Known message recipient differs from bound quote")
                    state = status.get("status")
                    if state not in ("sent", "failed", "deleted", "delivered", "read"):
                        raise ReceiptError("Unknown provider status for a bound message")
                    timestamp = status.get("timestamp")
                    if not isinstance(timestamp, str) or not re.fullmatch(r"[0-9]{1,12}", timestamp) or int(timestamp) <= 0:
                        raise ReceiptError("Invalid provider timestamp")
                    if state not in ("delivered", "read"):
                        continue
                    key = (message_id, state, timestamp)
                    if key not in seen:
                        receipts.append(VerifiedDelivery(binding, state, timestamp))
                        seen.add(key)
        return receipts
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ReceiptError("Malformed or inconsistent signed status payload") from error


def apply_signed_fixture(simulation, raw_body, signature, *, app_secret,
                         account_id, phone_number_id, bindings):
    """Verify fixture bytes and update only the existing synthetic quote simulator.

    No production adapter is accepted. Replay/state handling remains transactional
    in the underlying lab store. A stale event is rejected without changing it.
    """
    if (not isinstance(simulation, QuoteSimulation)
            or not isinstance(account_id, str) or not isinstance(phone_number_id, str)
            or not account_id.startswith("fixture-") or not phone_number_id.startswith("fixture-")):
        raise ReceiptError("Fixture-only simulator bridge required")
    bindings = tuple(bindings)
    for binding in bindings:
        if (not isinstance(binding, OutboundBinding)
                or not isinstance(binding.message_id, str) or not isinstance(binding.quote_id, str)
                or not binding.message_id.startswith("fixture-wamid-")
                or not binding.quote_id.startswith("simulation-")):
            raise ReceiptError("Synthetic quote/message bindings required")
    receipts = verify_status_webhook(raw_body, signature, app_secret=app_secret,
                                      account_id=account_id, phone_number_id=phone_number_id,
                                      bindings=bindings)
    events = []
    # Validate the complete batch before the first synthetic status transition.
    for receipt in receipts:
        binding = receipt.binding
        row = simulation._current(binding.quote_id, binding.version)
        if (row["specification"] != binding.specification_fingerprint
                or Decimal(row["price_before_vat"]) != Decimal(binding.amount)):
            raise QuoteStoreError("Outbound binding differs from saved quote")
        events.append(SimulatedDelivery(binding.quote_id, binding.version,
                                        simulation._message_id(row), receipt.status))
    return [simulation.delivery(event) for event in events]
