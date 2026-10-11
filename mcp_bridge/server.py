"""Public, non-sensitive bootstrap MCP for isolated Yossi WhatsApp test setup.

IMPORTANT: This server deliberately has NO WhatsApp API credentials,
message-sending tool, conversation-reading tool, or customer data access.
OAuth authorization and a separate test-sender integration are required
before privileged tools can be introduced.
"""
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Yossi WhatsApp Test Bridge", host="0.0.0.0", port=int(os.getenv("PORT", "10000")), stateless_http=True, json_response=True)


@mcp.tool()
def bridge_status() -> dict:
    """Read-only status of the test bridge, with no customer data."""
    return {
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
