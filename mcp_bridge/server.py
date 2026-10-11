"""Public, non-sensitive bootstrap MCP for isolated Yossi WhatsApp test setup.

IMPORTANT: This server deliberately has NO WhatsApp API credentials,
message-sending tool, conversation-reading tool, or customer data access.
OAuth authorization and a separate test-sender integration are required
before privileged tools can be introduced.
"""
import os
from mcp.server.fastmcp import FastMCP

TEST_RECIPIENT = "15556371022"
TEST_RECIPIENT_PHONE_ID = "1280310741842089"
BUSINESS_PHONE_ID = "456765487527572"


def bridge_readiness() -> dict:
    """Fail-closed configuration audit; never return credentials."""
    sender_id = os.getenv("MCP_TEST_SENDER_PHONE_ID", "").strip()
    authorized = (os.getenv("MCP_TEST_SENDING_APPROVED", "") == "true")
    token_present = bool(os.getenv("MCP_TEST_SENDER_META_TOKEN"))
    auth_present = bool(os.getenv("MCP_AUTH_ISSUER_URL")) and bool(os.getenv("MCP_AUTH_RESOURCE_URL"))
    sender_separate = bool(sender_id) and sender_id not in {BUSINESS_PHONE_ID, TEST_RECIPIENT_PHONE_ID}
    blockers = []
    if not sender_separate:
        blockers.append("A distinct approved test-sender Phone Number ID is required.")
    if not token_present:
        blockers.append("A scoped test-sender Meta API credential is required.")
    if not auth_present:
        blockers.append("MCP OAuth issuer and resource configuration is required.")
    if not authorized:
        blockers.append("Explicit approval of the test-sender identity is required.")
    return {
        "connection_stage": "setup_only",
        "test_recipient": "+" + TEST_RECIPIENT,
        "test_recipient_phone_id": TEST_RECIPIENT_PHONE_ID,
        "business_auto_replies": "unchanged_disabled",
        "sending_active": False,
        "transcript_reading_active": False,
        "blockers": blockers,
    }


mcp = FastMCP("Yossi WhatsApp Test Bridge", host="0.0.0.0", port=int(os.getenv("PORT", "10000")), stateless_http=True, json_response=True)


@mcp.tool()
def bridge_status() -> dict:
    """Read-only status of the test bridge, with no customer data."""
    return {
        **bridge_readiness(),
        "status": "setup_only",
        "whatsapp_connected": False,
        "can_send_whatsapp": False,
        "can_read_whatsapp": False,
        "test_recipient": "+15556371022",
        "test_phone_number_id": "1280310741842089",
        "business_outbound_enabled": False,
        "next_step": "Configure OAuth and an approved separate test-sender channel.",
    }


@mcp.tool()
def connection_requirements() -> dict:
    """Show the remaining safe configuration steps without exposing secrets."""
    return bridge_readiness()


@mcp.tool()
def test_plan() -> dict:
    """Read-only sales evaluation plan; never sends WhatsApp messages."""
    return {
        "scope": "test_number_only",
        "steps": [
            "Ask about a corner shower without volunteering dimensions immediately",
            "Disclose a nearby toilet and concern about ease of cleaning",
            "Ask for a price inclusive of installation",
            "Check that each answer references the newest customer message",
            "Request a human consultant, verify durable handoff only when available",
        ],
        "forbidden": [
            "Sending messages to real customers",
            "Enabling production WhatsApp automatic replies",
            "Enabling automated followups",
            "Inventing a price",
        ],
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
