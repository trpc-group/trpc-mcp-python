# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Standalone example: services of different protocols coexist in one process.

What it checks
--------------
One trpc server process runs two services at once:

- ``trpc.test.mcp.Greeter1``: ``protocol: http_mcp`` -- MCP service, called with ``McpProxy``.
- ``trpc.test.mcp.Greeter2``: ``protocol: http``     -- plain HTTP service, called with the trpc HTTP client.

The ``http_mcp`` codec is isolated and does not affect the plain ``http`` service,
so both protocols work in the same process.

Required server
---------------
- Config: ``examples/conf/trpc_python_mixed.yaml`` (Greeter1=http_mcp, Greeter2=http).
- Plain HTTP routes: ``/ping`` and ``/echo`` in ``examples/http_service/handlers.py``
  (bound to Greeter2), registered by importing them from ``trpc_main.py``.

How to run
----------
    # Terminal 1: start the server (mixed protocols)
    venv/bin/python examples/trpc_main.py \
        --conf examples/conf/trpc_python_mixed.yaml

    # Terminal 2: run this example
    venv/bin/python examples/test_mcp/test_trpc_mcp_mixed_protocol.py \
        --conf examples/conf/trpc_python_mixed.yaml

Expected output (abridged)
--------------------------
    [http_mcp] trpc.test.mcp.Greeter1 add -> structured={'result': 3}
    [http]     trpc.test.mcp.Greeter2 GET  /ping  -> 200 {'protocol': 'http', ...}
    [http]     trpc.test.mcp.Greeter2 POST /echo  -> 200 {'protocol': 'http', 'echo': 'hi'}
    [OK] http_mcp and http both work in the same process
"""
import argparse
import asyncio
import pathlib
import sys

from trpc_sdk.client import Options
from trpc_sdk.config import TrpcConfig
from trpc_sdk.abc import TrpcContext
from trpc_sdk.http import Client as HttpClient
from trpc_sdk.plugin import init_plugins

import trpc_mcp

CURRENT_DIR = pathlib.Path(__file__).parent
sys.path.append(str(CURRENT_DIR.parent))

# Importing the filters package registers the client filter referenced by the
# example configs. Must happen before init_plugins().
import filters as _

DEFAULT_CONF: str = str(CURRENT_DIR.parent / "conf" / "trpc_python_mixed.yaml")
MCP_SERVICE: str = "trpc.test.mcp.Greeter1"  # protocol: http_mcp
HTTP_SERVICE: str = "trpc.test.mcp.Greeter2"  # protocol: http
HTTP_ADDR: str = "127.0.0.1:8009"  # Greeter2 listen address


async def call_mcp() -> bool:
    """Call the http_mcp service."""
    proxy = trpc_mcp.McpProxy(
        name=MCP_SERVICE,
        options=[Options().set_protocol("http_mcp").set_namespace("Development")],
    )
    try:
        await proxy.initialize(TrpcContext())
        result = await proxy.execute_tool(TrpcContext(), "add", {"a": 1, "b": 2}, retries=1)
        print(f"[http_mcp] {MCP_SERVICE} add -> structured={result.structuredContent}")
        return result.structuredContent == {"result": 3}
    finally:
        await proxy.cleanup()


async def call_http() -> bool:
    """Call the plain HTTP service with the trpc HTTP client."""
    cli = HttpClient()

    get_rsp = await cli.get(TrpcContext(), f"http://{HTTP_ADDR}/ping?name=trpc-mcp")
    get_body = await get_rsp.json()
    print(f"[http]     {HTTP_SERVICE} GET  /ping  -> {get_rsp.status} {get_body}")

    post_rsp = await cli.post(TrpcContext(), f"http://{HTTP_ADDR}/echo", data="hi")
    post_body = await post_rsp.json()
    print(f"[http]     {HTTP_SERVICE} POST /echo  -> {post_rsp.status} {post_body}")

    return (get_rsp.status == 200 and get_body.get("protocol") == "http" and post_rsp.status == 200
            and post_body.get("echo") == "hi")


async def run() -> None:
    mcp_ok = await call_mcp()
    http_ok = await call_http()
    if mcp_ok and http_ok:
        print("[OK] http_mcp 与 http 两种协议在同一进程内均正常工作")
    else:
        print(f"[FAIL] mcp_ok={mcp_ok}, http_ok={http_ok}")
        sys.exit(1)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test http_mcp and http services coexisting in one process.")
    parser.add_argument("--conf", default=DEFAULT_CONF, help="Path to the trpc config file.")
    args = parser.parse_args()

    TrpcConfig.load(args.conf)
    init_plugins()
    await run()


if __name__ == "__main__":
    asyncio.run(main())
