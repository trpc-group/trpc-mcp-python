# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Standalone example: tool **icons / meta** metadata through trpc-mcp.

What this file demonstrates
---------------------------
- Server side: a tool registered with ``icons=`` (SEP-973, mcp 1.13+) and
  ``meta=`` (mcp 1.16+). See ``branded_tool`` in ``examples/mcp_callback/tools.py``.
- Client side:
  - ``list_tools`` surfaces those fields: ``tool.icons`` (list of ``Icon``) and
    ``tool.meta`` (the tool-definition ``_meta`` dict).
  - ``execute_tool(..., meta=...)`` forwards a per-call request ``_meta`` to the
    server (e.g. OpenAI Apps style passthrough).

Version compatibility
---------------------
``icons``/``meta`` were added to FastMCP/ClientSession in different mcp releases.
trpc-mcp forwards them only when the installed SDK supports them (otherwise they
are ignored with a warning), so this example degrades gracefully on older mcp:
the fields simply come back empty / ``None``.

How to run
----------
Start the example server first, then run this script with the SAME config:

    # SSE
    venv/bin/python examples/trpc_main.py \
        --conf examples/trpc_python.yaml
    venv/bin/python examples/test_mcp/test_trpc_mcp_icons_meta.py \
        --conf examples/trpc_python.yaml --service trpc.test.mcp.Greeter1

    # Streamable-HTTP
    venv/bin/python examples/trpc_main.py \
        --conf examples/conf/trpc_python_streamable_http.yaml
    venv/bin/python examples/test_mcp/test_trpc_mcp_icons_meta.py \
        --conf examples/conf/trpc_python_streamable_http.yaml

Expected output (abridged)
--------------------------
    [trpc.test.mcp.Greeter1] branded_tool.title -> Branded Echo
    [trpc.test.mcp.Greeter1] branded_tool.icons -> [Icon(src='https://example.com/icon-48.png', ...)]
    [trpc.test.mcp.Greeter1] branded_tool.meta  -> {'category': 'demo', 'vendor': 'trpc-mcp'}
    [trpc.test.mcp.Greeter1] branded_tool call   -> ['branded_tool args: hello']
"""
import argparse
import asyncio
import pathlib
import sys

from mcp.types import CallToolResult

from trpc_sdk.client import Options
from trpc_sdk.config import TrpcConfig
from trpc_sdk.abc import TrpcContext
from trpc_sdk.plugin import init_plugins

import trpc_mcp

# Importing the filters package registers the client filter and the custom "test"
# selector referenced by the example configs. Must happen before init_plugins().
CURRENT_DIR = pathlib.Path(__file__).parent
sys.path.append(str(CURRENT_DIR.parent))
import filters as _

DEFAULT_CONF: str = str(CURRENT_DIR.parent / "trpc_python.yaml")
DEFAULT_SERVICE: str = "trpc.test.mcp.Greeter1"


def new_ctx() -> TrpcContext:
    """Build a per-request context."""
    return TrpcContext()


def tool_text(result: CallToolResult) -> list[str]:
    """Collect the plain-text parts of a tool result for printing."""
    return [getattr(content, "text", str(content)) for content in result.content]


async def run(service_name: str) -> None:
    proxy = trpc_mcp.McpProxy(
        name=service_name,
        options=[Options().set_protocol("http_mcp").set_namespace("Development")],
    )
    try:
        await proxy.initialize(new_ctx())

        tools = {tool.name: tool for tool in await proxy.list_tools(new_ctx())}
        branded = tools.get("branded_tool")
        if branded is None:
            print(f"[{proxy.name}] branded_tool not exposed by this service")
            return

        # icons / meta are advertised in the tool definition (Tool.icons / Tool._meta).
        print(f"\n[{proxy.name}] branded_tool.title -> {branded.title}")
        print(f"[{proxy.name}] branded_tool.icons -> {branded.icons}")
        print(f"[{proxy.name}] branded_tool.meta  -> {branded.meta}")

        # Per-call request _meta passthrough (forwarded only when mcp>=1.16).
        result = await proxy.execute_tool(
            new_ctx(),
            "branded_tool",
            {"text": "hello"},
            retries=1,
            meta={"request-id": "demo-123"},
        )
        print(f"[{proxy.name}] branded_tool call   -> {tool_text(result)}")
    finally:
        await proxy.cleanup()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test MCP tool icons/meta via trpc-mcp McpProxy.")
    parser.add_argument("--conf", default=DEFAULT_CONF, help="Path to the trpc config file.")
    parser.add_argument("--service", default=DEFAULT_SERVICE, help="client.service name to call.")
    args = parser.parse_args()

    TrpcConfig.load(args.conf)
    init_plugins()
    await run(args.service)


if __name__ == "__main__":
    asyncio.run(main())
