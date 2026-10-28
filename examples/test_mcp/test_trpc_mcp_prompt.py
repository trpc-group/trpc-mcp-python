# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Standalone example: use MCP **prompts** through trpc-mcp's ``McpProxy``.

What this file demonstrates
---------------------------
- Discover the prompts a server exposes: ``proxy.list_prompts(ctx)``.
- Render a prompt with arguments: ``proxy.get_prompts(ctx, name, arguments)``
  returns an official MCP ``GetPromptResult`` whose ``messages`` carry the
  rendered prompt content.

Everything is config-driven (same pattern as ``helloworld/test_service_rpc.py``):
backend address / timeout / namespace / filter come from the ``client.service``
block, while the MCP ``base_url`` / default ``transport`` come from
``plugins.mcp.client`` (see ``trpc_python.yaml``). To render your own prompts,
copy this file and change ``--service`` and the ``get_prompts`` name/arguments.

How to run
----------
Start the example server first, then run this script with the SAME config:

    # SSE server (Greeter1 + Greeter2)
    venv/bin/python examples/trpc_main.py \
        --conf examples/trpc_python.yaml
    venv/bin/python examples/test_trpc_mcp_prompt.py \
        --conf examples/trpc_python.yaml --service trpc.test.mcp.Greeter1

    # Streamable-HTTP server
    venv/bin/python examples/trpc_main.py \
        --conf examples/conf/trpc_python_streamable_http.yaml
    venv/bin/python examples/test_trpc_mcp_prompt.py \
        --conf examples/conf/trpc_python_streamable_http.yaml

Expected output (abridged)
--------------------------
    [trpc.test.mcp.Greeter1] prompts:
      - echo_prompt: echo prompt
      - common_prompt: common prompt
    [trpc.test.mcp.Greeter1] common_prompt -> ['mcp_name: trpc.test.mcp.Greeter1-...']
"""
import argparse
import asyncio
import pathlib
import sys

from mcp.types import GetPromptResult

from trpc_sdk.client import Options
from trpc_sdk.config import TrpcConfig
from trpc_sdk.abc import TrpcContext
from trpc_sdk.plugin import init_plugins

import trpc_mcp
from trpc_mcp import set_http_header_to_context

CURRENT_DIR = pathlib.Path(__file__).parent

sys.path.append(str(CURRENT_DIR.parent))

# Importing the filters package registers the client filter and the custom "test"
# selector referenced by the example configs. Must happen before init_plugins().
import filters as _

DEFAULT_CONF: str = str(CURRENT_DIR.parent / "trpc_python.yaml")
DEFAULT_SERVICE: str = "trpc.test.mcp.Greeter1"


def new_ctx() -> TrpcContext:
    """Build a per-request context; also shows HTTP header passthrough."""
    ctx = TrpcContext()
    set_http_header_to_context(ctx, {"x-trpc-mcp-client-example": "1"})
    return ctx


def prompt_text(result: GetPromptResult) -> list[str]:
    """Collect the rendered text of each prompt message for printing."""
    return [getattr(message.content, "text", str(message.content)) for message in result.messages]


async def run(service_name: str) -> None:
    # host / base_url / transport are resolved by McpProxy from configuration;
    # options here only set the protocol (http_mcp) and namespace explicitly.
    proxy = trpc_mcp.McpProxy(
        name=service_name,
        options=[Options().set_protocol("http_mcp").set_namespace("Development")],
    )
    try:
        await proxy.initialize(new_ctx())

        prompts = await proxy.list_prompts(new_ctx())
        print(f"\n[{proxy.name}] prompts:")
        for prompt in prompts:
            print(f"  - {prompt.name}: {prompt.description}")

        # Render a prompt: prompt name + arguments dict. ``retries`` is optional.
        result = await proxy.get_prompts(
            new_ctx(),
            "common_prompt",
            {"prompt": "hello from common prompt"},
            retries=1,
        )
        print(f"\n[{proxy.name}] common_prompt -> {prompt_text(result)}")
    finally:
        await proxy.cleanup()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test MCP prompts via trpc-mcp McpProxy.")
    parser.add_argument("--conf", default=DEFAULT_CONF, help="Path to the trpc config file.")
    parser.add_argument("--service", default=DEFAULT_SERVICE, help="client.service name to call.")
    args = parser.parse_args()

    # trpc_sdk style: load the global config, then initialize plugins.
    TrpcConfig.load(args.conf)
    init_plugins()
    await run(args.service)


if __name__ == "__main__":
    asyncio.run(main())
