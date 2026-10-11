"""Independent regression tests for the read-only MCP setup service."""
import importlib.util
import os
import pathlib
import unittest
from unittest.mock import patch

SERVER_PATH = pathlib.Path(__file__).with_name("server.py")


class BridgeSecurityTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("yossi_mcp_bridge", SERVER_PATH)
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)

    def test_missing_secrets_is_fail_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            result = self.server.bridge_readiness()
        self.assertFalse(result["sending_active"])
        self.assertFalse(result["transcript_reading_active"])
        self.assertEqual(len(result["blockers"]), 4)

    def test_business_id_cannot_be_test_sender(self):
        with patch.dict(os.environ, {
            "MCP_TEST_SENDER_PHONE_ID": self.server.BUSINESS_PHONE_ID,
            "MCP_TEST_SENDER_META_TOKEN": "not-a-real-token",
            "MCP_AUTH_ISSUER_URL": "https://example.invalid",
            "MCP_AUTH_RESOURCE_URL": "https://example.invalid/mcp",
            "MCP_TEST_SENDING_APPROVED": "true",
        }, clear=True):
            result = self.server.bridge_readiness()
        self.assertTrue(any("distinct" in reason for reason in result["blockers"]))
        self.assertFalse(result["sending_active"])

    def test_credentials_are_not_exposed(self):
        with patch.dict(os.environ, {"MCP_TEST_SENDER_META_TOKEN": "secret-sentinel"}, clear=True):
            result = self.server.bridge_readiness()
        self.assertNotIn("secret-sentinel", str(result))

    def test_no_send_or_read_tool_is_exposed(self):
        import inspect
        source = inspect.getsource(self.server)
        self.assertNotIn("def send_whatsapp(", source)
        self.assertNotIn("def read_customer_conversation(", source)


if __name__ == "__main__":
    unittest.main()
