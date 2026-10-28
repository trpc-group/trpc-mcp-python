# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Standalone example: MCP **structured output** through trpc-mcp's ``McpProxy``.

What this file demonstrates
---------------------------
- A tool that declares an ``outputSchema`` (the example ``get_weather`` tool
  returns a Pydantic ``WeatherData`` model with ``structured_output=True``).
- Reading the typed result: ``CallToolResult.structuredContent`` is a
  schema-validated JSON object (machine-readable, accessed by field), while the
  plain-text ``content`` stays available for humans/LLMs. The official
  ``ClientSession`` validates ``structuredContent`` against the tool schema.

Use structured output when the caller (e.g. an agent) needs to read specific
fields reliably instead of parsing free-form text. Everything is config-driven;
copy this file and point ``execute_tool`` at your own schema-returning tool.

How to run
----------
Start the example server first, then run this script with the SAME config:

    # SSE server (Greeter1 + Greeter2)
    venv/bin/python examples/trpc_main.py \
        --conf examples/trpc_python.yaml
    venv/bin/python examples/test_trpc_mcp_structured_output.py \
        --conf examples/trpc_python.yaml --service trpc.test.mcp.Greeter1

    # Streamable-HTTP server
    venv/bin/python examples/trpc_main.py \
        --conf examples/conf/trpc_python_streamable_http.yaml
    venv/bin/python examples/test_trpc_mcp_structured_output.py \
        --conf examples/conf/trpc_python_streamable_http.yaml

Expected output (abridged)
--------------------------
    [trpc.test.mcp.Greeter1] get_weather.outputSchema -> {'title': 'WeatherData', ...}
    [trpc.test.mcp.Greeter1] get_weather text       -> ['{ ... }']
    [trpc.test.mcp.Greeter1] get_weather structured -> {'temperature': 22.5, ...}
    [trpc.test.mcp.Greeter1] get_weather fields     -> location=Shenzhen, temperature=22.5, ...
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
from trpc_mcp import set_http_header_to_context

# Importing the filters package registers the client filter and the custom "test"
# selector referenced by the example configs. Must happen before init_plugins().
CURRENT_DIR = pathlib.Path(__file__).parent
sys.path.append(str(CURRENT_DIR.parent))
import filters as _

DEFAULT_CONF: str = str(CURRENT_DIR.parent / "trpc_python.yaml")
DEFAULT_SERVICE: str = "trpc.test.mcp.Greeter1"


def new_ctx() -> TrpcContext:
    """Build a per-request context; also shows HTTP header passthrough."""
    ctx = TrpcContext()
    set_http_header_to_context(ctx, {"x-trpc-mcp-client-example": "1"})
    return ctx


def tool_text(result: CallToolResult) -> list[str]:
    """Collect the plain-text parts of a tool result for printing."""
    return [getattr(content, "text", str(content)) for content in result.content]


async def run(service_name: str) -> None:
    # host / base_url / transport are resolved by McpProxy from configuration;
    # options here only set the protocol (http_mcp) and namespace explicitly.
    proxy = trpc_mcp.McpProxy(
        name=service_name,
        options=[Options().set_protocol("http_mcp").set_namespace("Development")],
    )
    try:
        await proxy.initialize(new_ctx())

        # The tool's outputSchema is advertised in list_tools (Tool.outputSchema).
        tools = {tool.name: tool for tool in await proxy.list_tools(new_ctx())}
        weather = tools.get("get_weather")
        if weather is None:
            print(f"[{proxy.name}] get_weather not exposed by this service")
            return

        print(f"\n[{proxy.name}] get_weather.outputSchema -> {weather.outputSchema}")

        result = await proxy.execute_tool(new_ctx(), "get_weather", {"city": "Shenzhen"}, retries=1)
        print(f"[{proxy.name}] get_weather text       -> {tool_text(result)}")
        # structuredContent is a plain dict validated against the output schema.
        print(f"[{proxy.name}] get_weather structured -> {result.structuredContent}")
        fields = result.structuredContent or {}
        print(f"[{proxy.name}] get_weather fields     -> "
              f"location={fields.get('location')}, temperature={fields.get('temperature')}, "
              f"condition={fields.get('condition')}")
    finally:
        await proxy.cleanup()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test MCP structured output via trpc-mcp McpProxy.")
    parser.add_argument("--conf", default=DEFAULT_CONF, help="Path to the trpc config file.")
    parser.add_argument("--service", default=DEFAULT_SERVICE, help="client.service name to call.")
    args = parser.parse_args()

    # trpc_sdk style: load the global config, then initialize plugins.
    TrpcConfig.load(args.conf)
    init_plugins()
    await run(args.service)


if __name__ == "__main__":
    asyncio.run(main())
