# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com
"""Standalone example: **不同协议的 service 在同一进程内共存**。

测什么
------
同一个 trpc server 进程里同时跑两个 service：

- ``trpc.test.mcp.Greeter1``：``protocol: http_mcp`` —— MCP 服务，用 ``McpProxy`` 调用。
- ``trpc.test.mcp.Greeter2``：``protocol: http``     —— 普通 HTTP 服务，用 trpc HTTP 客户端调用。

目的：验证 ``http_mcp`` 的专用 codec 是隔离的，**不会影响普通 ``http`` 服务**，
两种协议可以在同一进程同时正常工作。

依赖的服务端
------------
- 配置：``examples/conf/trpc_python_mixed.yaml``（Greeter1=http_mcp，Greeter2=http）。
- 普通 HTTP 路由：``examples/http_service/handlers.py`` 的 ``/ping`` 与 ``/echo``
  （绑定到 Greeter2），由 ``trpc_main.py`` 导入注册。

How to run
----------
    # 终端 1：起服务（混合协议）
    venv/bin/python examples/trpc_main.py \
        --conf examples/conf/trpc_python_mixed.yaml

    # 终端 2：跑本测试
    venv/bin/python examples/test_mcp/test_trpc_mcp_mixed_protocol.py \
        --conf examples/conf/trpc_python_mixed.yaml

Expected output (abridged)
--------------------------
    [http_mcp] trpc.test.mcp.Greeter1 add -> structured={'result': 3}
    [http]     trpc.test.mcp.Greeter2 GET  /ping  -> 200 {'protocol': 'http', ...}
    [http]     trpc.test.mcp.Greeter2 POST /echo  -> 200 {'protocol': 'http', 'echo': 'hi'}
    [OK] http_mcp 与 http 两种协议在同一进程内均正常工作
"""
import argparse
import asyncio
import pathlib
import sys

from trpc.client.options import with_namespace
from trpc.client.options import with_protocol
from trpc.config import config as trpc_config
from trpc.context import TrpcContext
from trpc.http.client import Client as HttpClient
from trpc.plugin import plugin as trpc_plugin

import trpc_mcp

CURRENT_DIR = pathlib.Path(__file__).parent
sys.path.append(str(CURRENT_DIR.parent))

# Importing the filters package registers the client filter referenced by the
# example configs. Must happen before trpc_plugin.setup().
import filters as _

DEFAULT_CONF: str = str(CURRENT_DIR.parent / "conf" / "trpc_python_mixed.yaml")
MCP_SERVICE: str = "trpc.test.mcp.Greeter1"  # protocol: http_mcp
HTTP_SERVICE: str = "trpc.test.mcp.Greeter2"  # protocol: http
HTTP_ADDR: str = "127.0.0.1:8009"  # Greeter2 监听地址


async def call_mcp() -> bool:
    """调用 http_mcp 服务（MCP）。"""
    proxy = trpc_mcp.McpProxy(
        name=MCP_SERVICE,
        options=[with_protocol("http_mcp"), with_namespace("Development")],
    )
    try:
        await proxy.initialize(TrpcContext())
        result = await proxy.execute_tool(TrpcContext(), "add", {"a": 1, "b": 2}, retries=1)
        print(f"[http_mcp] {MCP_SERVICE} add -> structured={result.structuredContent}")
        return result.structuredContent == {"result": 3}
    finally:
        await proxy.cleanup()


async def call_http() -> bool:
    """调用普通 http 服务（trpc HTTP 客户端）。"""
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

    trpc_config.load_global_config(args.conf, "utf-8")
    trpc_plugin.setup()
    await run()


if __name__ == "__main__":
    asyncio.run(main())
