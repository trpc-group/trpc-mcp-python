# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com
"""Standalone example: MCP **roots** (server -> client callback) via ``McpProxy``.

What this file demonstrates
---------------------------
- Registering a client-side ``list_roots_callback`` so the server can ask the
  client "which local root directories may I touch?" (MCP ``roots/list``). The
  callback is passed to the official ``ClientSession`` through
  ``McpProxy.initialize(..., session_args=...)``.
- Triggering that server->client request by calling the ``allowed_directories``
  tool, which internally performs ``session.list_roots()``. This proves the
  bidirectional MCP channel (not just client->server) works through trpc-mcp.

Use roots when a server-side tool needs to access client-local files / repos and
must first learn the allowed scope instead of assuming it. Everything is
config-driven; copy this file and return your own roots from the callback.

How to run
----------
Start the example server first, then run this script with the SAME config:

    # SSE server (Greeter1 + Greeter2)
    venv/bin/python examples/trpc_main.py \
        --conf examples/trpc_python.yaml
    venv/bin/python examples/test_trpc_mcp_roots.py \
        --conf examples/trpc_python.yaml --service trpc.test.mcp.Greeter1

    # Streamable-HTTP server
    venv/bin/python examples/trpc_main.py \
        --conf examples/conf/trpc_python_streamable_http.yaml
    venv/bin/python examples/test_trpc_mcp_roots.py \
        --conf examples/conf/trpc_python_streamable_http.yaml

Expected output (abridged)
--------------------------
    [trpc.test.mcp.Greeter1] allowed_directories -> ['Allowed directories:
    file:///tmp/trpc-mcp-root-a
    file:///tmp/trpc-mcp-root-b']
"""
import argparse
import asyncio
import pathlib
import sys

import mcp.types as types
from mcp.shared.context import RequestContext
from mcp.types import CallToolResult
from pydantic import FileUrl

from trpc.client.options import with_namespace
from trpc.client.options import with_protocol
from trpc.config import config as trpc_config
from trpc.context import TrpcContext
from trpc.plugin import plugin as trpc_plugin

import trpc_mcp
from trpc_mcp import set_http_header_to_context

# Importing the filters package registers the client filter and the custom "test"
# selector referenced by the example configs. Must happen before trpc_plugin.setup().
CURRENT_DIR = pathlib.Path(__file__).parent
sys.path.append(str(CURRENT_DIR.parent))

import filters as _

DEFAULT_CONF: str = str(CURRENT_DIR.parent / "trpc_python.yaml")
DEFAULT_SERVICE: str = "trpc.test.mcp.Greeter1"
# The roots this client is willing to expose to the server.
ROOT_URIS = (
    "file:///tmp/trpc-mcp-root-a",
    "file:///tmp/trpc-mcp-root-b",
)


def new_ctx() -> TrpcContext:
    """Build a per-request context; also shows HTTP header passthrough."""
    ctx = TrpcContext()
    set_http_header_to_context(ctx, {"x-trpc-mcp-client-example": "1"})
    return ctx


async def list_roots_callback(context: RequestContext) -> types.ListRootsResult | types.ErrorData:
    """Reply to the server's ``roots/list`` request with this client's roots."""
    return types.ListRootsResult(roots=[
        types.Root(uri=FileUrl(uri), name=f"trpc-mcp-root-{index}") for index, uri in enumerate(ROOT_URIS, start=1)
    ])


def tool_text(result: CallToolResult) -> list[str]:
    """Collect the plain-text parts of a tool result for printing."""
    return [getattr(content, "text", str(content)) for content in result.content]


async def run(service_name: str) -> None:
    # host / base_url / transport are resolved by McpProxy from configuration;
    # options here only set the protocol (http_mcp) and namespace explicitly.
    proxy = trpc_mcp.McpProxy(
        name=service_name,
        options=[with_protocol("http_mcp"), with_namespace("Development")],
    )
    try:
        # Pass the roots callback into the underlying official ClientSession.
        await proxy.initialize(new_ctx(), session_args={"list_roots_callback": list_roots_callback})

        # This common tool calls roots/list back to us, exercising the callback.
        result = await proxy.execute_tool(new_ctx(), "allowed_directories", {}, retries=1)
        print(f"\n[{proxy.name}] allowed_directories -> {tool_text(result)}")
    finally:
        await proxy.cleanup()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test MCP roots callback via trpc-mcp McpProxy.")
    parser.add_argument("--conf", default=DEFAULT_CONF, help="Path to the trpc config file.")
    parser.add_argument("--service", default=DEFAULT_SERVICE, help="client.service name to call.")
    args = parser.parse_args()

    # trpc-python style: load the global config, then set up plugins.
    trpc_config.load_global_config(args.conf, "utf-8")
    trpc_plugin.setup()
    await run(args.service)


if __name__ == "__main__":
    asyncio.run(main())
