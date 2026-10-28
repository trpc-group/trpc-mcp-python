# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Standalone example: read MCP **resources** through trpc-mcp's ``McpProxy``.

What this file demonstrates
---------------------------
- Discover static resources: ``proxy.list_resources(ctx)``.
- Discover resource templates (parameterised URIs):
  ``proxy.list_resource_templates(ctx)``.
- Read a resource by URI: ``proxy.read_resource(ctx, uri)`` returns an official
  MCP ``ReadResourceResult`` whose ``contents`` carry the resource payload.
  Template resources are read by filling the template, e.g.
  ``common://trpc-mcp-client`` for a ``common://{data}`` template.

Everything is config-driven (same pattern as ``helloworld/test_service_rpc.py``):
backend address / timeout / namespace / filter come from the ``client.service``
block, while the MCP ``base_url`` / default ``transport`` come from
``plugins.mcp.client`` (see ``trpc_python.yaml``). To read your own resources,
copy this file and change ``--service`` and the ``read_resource`` URI.

How to run
----------
Start the example server first, then run this script with the SAME config:

    # SSE server (Greeter1 + Greeter2)
    venv/bin/python examples/trpc_main.py \
        --conf examples/trpc_python.yaml
    venv/bin/python examples/test_trpc_mcp_resource.py \
        --conf examples/trpc_python.yaml --service trpc.test.mcp.Greeter1

    # Streamable-HTTP server
    venv/bin/python examples/trpc_main.py \
        --conf examples/conf/trpc_python_streamable_http.yaml
    venv/bin/python examples/test_trpc_mcp_resource.py \
        --conf examples/conf/trpc_python_streamable_http.yaml

Expected output (abridged)
--------------------------
    [trpc.test.mcp.Greeter1] resources:
      - echo://static: echo resource
    [trpc.test.mcp.Greeter1] resource templates:
      - common://{data}: Common template resource handler ...
    [trpc.test.mcp.Greeter1] common://trpc-mcp-client -> ['this is template: ...']
"""
import argparse
import asyncio
import pathlib
import sys

from mcp.types import ReadResourceResult

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
DEFAULT_SERVICE = "trpc.test.mcp.Greeter1"
# A template resource (common://{data}) filled with a concrete value.
DEFAULT_RESOURCE_URI = "common://trpc-mcp-client"


def new_ctx() -> TrpcContext:
    """Build a per-request context; also shows HTTP header passthrough."""
    ctx = TrpcContext()
    set_http_header_to_context(ctx, {"x-trpc-mcp-client-example": "1"})
    return ctx


def resource_text(result: ReadResourceResult) -> list[str]:
    """Collect the text payloads of a resource read for printing."""
    return [getattr(content, "text", str(content)) for content in result.contents]


async def run(service_name: str, resource_uri: str) -> None:
    # host / base_url / transport are resolved by McpProxy from configuration;
    # options here only set the protocol (http_mcp) and namespace explicitly.
    proxy = trpc_mcp.McpProxy(
        name=service_name,
        options=[Options().set_protocol("http_mcp").set_namespace("Development")],
    )
    try:
        await proxy.initialize(new_ctx())

        resources = await proxy.list_resources(new_ctx())
        print(f"\n[{proxy.name}] resources:")
        for resource in resources:
            print(f"  - {resource.uri}: {resource.description}")

        templates = await proxy.list_resource_templates(new_ctx())
        print(f"\n[{proxy.name}] resource templates:")
        for template in templates:
            print(f"  - {template.uri_template}: {template.description}")

        # Read a resource by URI (template URIs are filled in with concrete values).
        result = await proxy.read_resource(new_ctx(), resource_uri, retries=1)
        print(f"\n[{proxy.name}] {resource_uri} -> {resource_text(result)}")
    finally:
        await proxy.cleanup()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test MCP resources via trpc-mcp McpProxy.")
    parser.add_argument("--conf", default=DEFAULT_CONF, help="Path to the trpc config file.")
    parser.add_argument("--service", default=DEFAULT_SERVICE, help="client.service name to call.")
    parser.add_argument("--uri", default=DEFAULT_RESOURCE_URI, help="Resource URI to read.")
    args = parser.parse_args()

    # trpc_sdk style: load the global config, then initialize plugins.
    TrpcConfig.load(args.conf)
    init_plugins()
    await run(args.service, args.uri)


if __name__ == "__main__":
    asyncio.run(main())
