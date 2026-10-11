# Yossi WhatsApp MCP bridge — setup only

This is a **separate Render web service** that exposes an MCP Streamable HTTP endpoint at `/mcp`.

It currently exposes ONLY two anonymous, static, read-only tools: `bridge_status` and `test_plan`. Neither tool reads or sends WhatsApp messages, handles tokens, accesses customer conversations, or modifies the existing business app.

## Render service configuration
- Runtime: Python
- Build command: `pip install -r mcp_bridge/requirements.txt`
- Start command: `python mcp_bridge/server.py`
- Expected endpoint: `https://<render-service-domain>/mcp`
- Auto-deploy can remain disabled during the first setup.

## Security / rollout gates
1. The current tools contain no private customer data and grant no outbound powers.
2. **Do not** add Meta tokens, production sender credentials, or customer transcript access to this anonymous bridge.
3. Before privileged tools exist, implement MCP-compliant OAuth, explicit authorisation, rate limits, audit logs, scoped test-recipient allowlists, durable history, and a separately approved sender identity.
4. The existing business WhatsApp auto-reply and automated followups must stay disabled.
5. The WhatsApp test-number ID is `1280310741842089`; the real Israeli business number uses a different Meta Phone Number ID. These IDs represent *recipient/sender accounts*, not an interchangeable client identity.

This service provides only the initial connection handshake, not the requested two-way WhatsApp testing yet.
