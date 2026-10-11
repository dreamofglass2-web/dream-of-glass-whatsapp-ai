"""Offline pre-release acceptance tests for the proposed universal calculator.

This module does not launch WhatsApp, access customer records or deploy anything.
"""
import ast
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from quote_lab.builder import NamedPanel
from quote_lab.customer_preview import render_current_preview
from quote_lab.durable_store import DurableQuoteStore, QuoteStoreError
from quote_lab.workflow import create_offline_quote
from quote_lab.universal import NeedsReview


def pane(role, width, glass="שקופה"):
    return NamedPanel(role, width, 200, glass)


class OwnerAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DurableQuoteStore(Path(self.temp.name) / "acceptance.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_reference_two_fixed_two_doors(self):
        panes = [pane("fixed", 40), pane("fixed", 40),
                 pane("door", 40), pane("door", 40)]
        draft = create_offline_quote(self.store, "reference1",
                                     "פינתי 2 קבועים + 2 דלתות", panes,
                                     layout_confirmed=True)
        self.assertEqual(draft["price_before_vat"], "2644.00")
        preview = render_current_preview(self.store, draft,
                                         template="פינתי 2 קבועים + 2 דלתות",
                                         panels=panes, finish="ניקל")
        self.assertIn("2,644.00", preview["text"])
        self.assertFalse(preview["send_authorized"])

    def test_exact_reference_two_bronze_doors(self):
        panes = [pane("door", 90, "אנטיסן ברונזה")] * 2
        draft = create_offline_quote(self.store, "reference2",
                                     "פינתי 2 דלתות", panes,
                                     layout_confirmed=True)
        self.assertEqual(draft["price_before_vat"], "2828.00")
        preview = render_current_preview(self.store, draft,
                                         template="פינתי 2 דלתות",
                                         panels=panes, finish="ניקל")
        self.assertIn("2,828.00", preview["text"])
        self.assertNotIn("עלות ספק", preview["text"])

    def test_customer_only_sees_opted_in_removal(self):
        panes = [pane("door", 90)] * 2
        draft = create_offline_quote(self.store, "removal",
                                     "פינתי 2 דלתות", panes,
                                     layout_confirmed=True)
        result = render_current_preview(self.store, draft,
                                        template="פינתי 2 דלתות",
                                        panels=panes, finish="ניקל")
        self.assertNotIn("פירוק ופינוי", result["text"])
        other = create_offline_quote(self.store, "removal",
                                     "פינתי 2 דלתות", panes,
                                     layout_confirmed=True,
                                     demolition_and_disposal=True)
        with self.assertRaises(NeedsReview):
            render_current_preview(self.store, draft, template="פינתי 2 דלתות",
                                   panels=panes, finish="ניקל")
        self.assertEqual(Decimal(other["price_before_vat"]) -
                         Decimal(draft["price_before_vat"]), Decimal(250))

    def test_never_approve_unsent_quote(self):
        panes = [pane("door", 90)] * 2
        draft = create_offline_quote(self.store, "approval",
                                     "פינתי 2 דלתות", panes,
                                     layout_confirmed=True)
        with self.assertRaises(QuoteStoreError):
            self.store.mark_approved("approval", draft["version"],
                                     draft["specification_fingerprint"],
                                     draft["price_before_vat"], "yes")


class IsolationAcceptanceTests(unittest.TestCase):
    def test_production_app_never_imports_quote_lab(self):
        app_path = Path(__file__).resolve().parent.parent / "app.py"
        app = ast.parse(app_path.read_text(encoding="utf-8"))
        for node in ast.walk(app):
            if isinstance(node, ast.Import):
                self.assertFalse(any(alias.name.startswith("quote_lab") for alias in node.names))
            if isinstance(node, ast.ImportFrom):
                self.assertFalse((node.module or "").startswith("quote_lab"))

    def test_offline_lab_has_no_meta_or_crm_network_imports(self):
        root = Path(__file__).resolve().parent
        for name in ("universal.py", "builder.py", "workflow.py",
                     "customer_preview.py", "durable_store.py", "simulator.py",
                     "hinge_rules.py", "side_dimensions.py"):
            source = (root / name).read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    packages = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    packages = [(node.module or "").split(".")[0]]
                else:
                    continue
                self.assertFalse(set(packages) & {"requests", "httpx", "psycopg2", "psycopg", "flask"},
                                 f"Network import in offline file {name}")


if __name__ == "__main__":
    unittest.main()
