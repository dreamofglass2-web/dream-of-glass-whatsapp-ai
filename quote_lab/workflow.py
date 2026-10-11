"""Offline workflow linking approved layout calculation to durable draft storage.

This intentionally has no WhatsApp, Meta, or production database access.
It cannot mark a quote sent or approved; independent verified evidence is required.
"""
import hashlib
import json
from decimal import Decimal

from quote_lab.builder import price_proposed_layout
from quote_lab.durable_store import DurableQuoteStore


def create_offline_quote(store: DurableQuoteStore, quote_id: str, template: str,
                         panels: list, *, layout_confirmed: bool = False,
                         finish: str = "ניקל", demolition_and_disposal: bool = False,
                         step_notch_measured: bool = False) -> dict:
    calculation = price_proposed_layout(
        template, panels, layout_confirmed=layout_confirmed, finish=finish,
        demolition_and_disposal=demolition_and_disposal,
        step_notch_measured=step_notch_measured)
    specification = {
        "template": template,
        "finish": finish,
        "panels": calculation["panel_breakdown"],
        "removal_and_disposal": demolition_and_disposal,
        "catalog_version": calculation["catalog_version"],
    }
    canonical = json.dumps(specification, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    version = store.create_draft(
        quote_id, fingerprint, calculation["price_before_vat"],
        calculation["catalog_version"])
    return {
        "quote_id": quote_id,
        "version": version,
        "state": "draft",
        "specification_fingerprint": fingerprint,
        "price_before_vat": calculation["price_before_vat"],
        "catalog_version": calculation["catalog_version"],
        "can_send_whatsapp": False,
        "can_approve": False,
        "preview_finish": finish,\n        "calculation": calculation,
    }
