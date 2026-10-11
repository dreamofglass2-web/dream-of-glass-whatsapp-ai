"""Offline workflow linking approved layout calculation to durable draft storage.

This intentionally has no WhatsApp, Meta, or production database access.
It cannot mark a quote sent or approved; independent verified evidence is required.
"""
import hashlib
import json

from quote_lab.builder import NamedPanel, price_proposed_layout
from quote_lab.durable_store import DurableQuoteStore, QuoteStoreError
from quote_lab.customer_preview import render_customer_preview, render_current_preview
from quote_lab.universal import CONFIG_VERSION


def create_offline_quote(store: DurableQuoteStore, quote_id: str, template: str,
                         panels: list, *, layout_confirmed: bool = False,
                         finish: str = "ניקל", handle_style: str = "ידית כפתור",
                         demolition_and_disposal: bool = False,
                         step_notch_measured: bool = False,
                         decoration: str = "none") -> dict:
    calculation = price_proposed_layout(
        template, panels, layout_confirmed=layout_confirmed, finish=finish,
        handle_style=handle_style,
        demolition_and_disposal=demolition_and_disposal,
        step_notch_measured=step_notch_measured, decoration=decoration)
    specification = {
        "template": template,
        "finish": finish,
        "handle_style": handle_style,
        "panels": calculation["panel_breakdown"],
        "decoration": calculation["shower_decoration"],
        "removal_and_disposal": demolition_and_disposal,
        "catalog_version": calculation["catalog_version"],
    }
    canonical = json.dumps(specification, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    record = {
        "quote_id": quote_id,
        "version": 0,
        "state": "draft",
        "specification_fingerprint": fingerprint,
        "price_before_vat": calculation["price_before_vat"],
        "catalog_version": calculation["catalog_version"],
        "can_send_whatsapp": False,
        "can_approve": False,
        "preview_finish": finish,
        "preview_handle_style": handle_style,
        "calculation": calculation,
    }
    preview = render_customer_preview(
        record, template=template, panels=panels, finish=finish,
        handle_style=handle_style, demolition_and_disposal=demolition_and_disposal,
        decoration=decoration)
    snapshot = {
        "specification": specification,
        "calculation": calculation,
        "customer_preview_text": preview["text"],
        "step_notch_measured": step_notch_measured,
    }
    record["version"] = store.create_draft(
        quote_id, fingerprint, calculation["price_before_vat"],
        calculation["catalog_version"], snapshot=snapshot)
    record["customer_preview_text"] = preview["text"]
    return record


def restore_offline_quote(store: DurableQuoteStore, quote_id: str) -> dict:
    """Restore only the current offline draft, verifying calculation and display.

    Never restore an old catalog, missing snapshot, or delivery/approval as a draft.
    No network, production database, or sending capability is introduced.
    """
    saved = store.snapshot(quote_id)
    if saved["state"] != "draft" or saved["catalog_version"] != CONFIG_VERSION:
        raise QuoteStoreError("Only current-catalog unsent drafts can be restored")
    try:
        snapshot = saved["snapshot"]
        spec = snapshot["specification"]
        canonical = json.dumps(spec, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False)
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if fingerprint != saved["specification"] or spec["catalog_version"] != saved["catalog_version"]:
            raise QuoteStoreError("Saved specification differs from metadata")
        panels = [NamedPanel(p["role"], p["width_cm"], p["height_cm"], p["glass"],
                             shape=p["shape"], decoration=p["decoration"])
                  for p in spec["panels"]]
        calculation = price_proposed_layout(
            spec["template"], panels, layout_confirmed=True,
            finish=spec["finish"], handle_style=spec["handle_style"],
            demolition_and_disposal=spec["removal_and_disposal"],
            decoration=spec["decoration"],
            step_notch_measured=snapshot["step_notch_measured"])
        if (calculation != snapshot["calculation"]
                or calculation["price_before_vat"] != saved["price_before_vat"]):
            raise QuoteStoreError("Saved calculation differs from verified recalculation")
        record = {
            "quote_id": quote_id, "version": saved["version"], "state": "draft",
            "specification_fingerprint": fingerprint,
            "price_before_vat": saved["price_before_vat"],
            "catalog_version": saved["catalog_version"],
            "can_send_whatsapp": False, "can_approve": False,
            "preview_finish": spec["finish"], "preview_handle_style": spec["handle_style"],
            "calculation": calculation,
        }
        preview = render_current_preview(
            store, record, template=spec["template"], panels=panels, finish=spec["finish"],
            handle_style=spec["handle_style"], decoration=spec["decoration"],
            demolition_and_disposal=spec["removal_and_disposal"])
        if preview["text"] != snapshot["customer_preview_text"]:
            raise QuoteStoreError("Saved customer text differs from verified preview")
        record["customer_preview_text"] = preview["text"]
        return record
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        raise QuoteStoreError("Cannot restore an inconsistent offline quote snapshot") from error
