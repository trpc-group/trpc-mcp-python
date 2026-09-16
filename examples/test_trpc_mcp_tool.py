# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com
"""Standalone example: call MCP **tools** through trpc-mcp's ``McpProxy``.

What this file demonstrates
---------------------------
- Discover the tools a server exposes: ``proxy.list_tools(ctx)``.
- Invoke a tool with an arguments dict and read the result:
  ``proxy.execute_tool(ctx, name, arguments)`` returns an official MCP
  ``CallToolResult`` carrying plain-text ``content`` and (optionally) a
  machine-readable ``structuredContent``.
- Verify a custom HTTP header set via ``set_http_header_to_context`` reaches the
  server end-to-end, using the ``echo_header`` tool to read it back.

Everything is config-driven (same pattern as ``helloworld/test_service_rpc.py``):
backend address / timeout / namespace / filter come from the ``client.service``
block, while the MCP ``base_url`` / default ``transport`` come from
``plugins.mcp.client`` (see ``trpc_python.yaml``). To call your own tools, copy
this file and change ``--service`` and the ``execute_tool`` name/arguments.

How to run
----------
Start the example server first, then run this script with the SAME config:

    # SSE server (Greeter1 + Greeter2)
    venv/bin/python examples/trpc_main.py \
        --conf examples/trpc_python.yaml
    venv/bin/python examples/test_trpc_mcp_tool.py \
        --conf examples/trpc_python.yaml --service trpc.test.mcp.Greeter1

    # Streamable-HTTP server
    venv/bin/python examples/trpc_main.py \
        --conf examples/conf/trpc_python_streamable_http.yaml
    venv/bin/python examples/test_trpc_mcp_tool.py \
        --conf examples/conf/trpc_python_streamable_http.yaml

Expected output (abridged)
--------------------------
    [trpc.test.mcp.Greeter1] tools:
      - add: add tool
      - echo_tool: echo tool
    [trpc.test.mcp.Greeter1] add -> structured={'result': 3}, text=['3']
    [trpc.test.mcp.Greeter1] echo_header -> x-trpc-mcp-client-example=1 (header propagated: True)
"""
import argparse
import asyncio
import pathlib

from mcp.types import CallToolResult

from trpc.client.options import with_namespace
from trpc.client.options import with_protocol
from trpc.config import config as trpc_config
from trpc.context import TrpcContext
from trpc.plugin import plugin as trpc_plugin

import trpc_mcp
from trpc_mcp import set_http_header_to_context

# Importing the filters package registers the client filter and the custom "test"
# selector referenced by the example configs. Must happen before trpc_plugin.setup().
import filters as _

DEFAULT_CONF: str = str(pathlib.Path(__file__).parent.parent / "trpc_python.yaml")
DEFAULT_SERVICE: str = "trpc.test.mcp.Greeter1"
# Custom HTTP header sent from client -> server; the echo_header tool reads it
# back so we can verify set_http_header_to_context really propagates downstream.
HEADER_KEY: str = "x-trpc-mcp-client-example"
HEADER_VALUE: str = "1"


def new_ctx() -> TrpcContext:
    """Build a per-request context; also shows HTTP header passthrough.

    Headers set here are injected into every HTTP request of the MCP connection
    (see TrpcHttpxTransport), and verified end-to-end via the echo_header tool.
    """
    ctx = TrpcContext()
    set_http_header_to_context(ctx, {HEADER_KEY: HEADER_VALUE})
    return ctx


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
        await proxy.initialize(new_ctx())

        tools = await proxy.list_tools(new_ctx())
        print(f"\n[{proxy.name}] tools:")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description}")

        # Call a tool: tool name + arguments dict. ``retries`` is optional.
        result = await proxy.execute_tool(new_ctx(), "add", {"a": 1, "b": 2}, retries=1)
        print(f"\n[{proxy.name}] add -> structured={result.structuredContent}, text={tool_text(result)}")

        # Verify the custom header set via set_http_header_to_context (see new_ctx)
        # actually reaches the server: the echo_header tool reads it back from the
        # raw request and returns it, so we should see HEADER_KEY=HEADER_VALUE.
        header = await proxy.execute_tool(new_ctx(), "echo_header", {"key": HEADER_KEY}, retries=1)
        echoed = "".join(tool_text(header))
        ok = echoed == f"{HEADER_KEY}={HEADER_VALUE}"
        print(f"[{proxy.name}] echo_header -> {echoed} (header propagated: {ok})")
    finally:
        await proxy.cleanup()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test MCP tools via trpc-mcp McpProxy.")
    parser.add_argument("--conf", default=DEFAULT_CONF, help="Path to the trpc config file.")
    parser.add_argument("--service", default=DEFAULT_SERVICE, help="client.service name to call.")
    args = parser.parse_args()

    # trpc-python style: load the global config, then set up plugins.
    trpc_config.load_global_config(args.conf, "utf-8")
    trpc_plugin.setup()
    await run(args.service)


if __name__ == "__main__":
    asyncio.run(main())
