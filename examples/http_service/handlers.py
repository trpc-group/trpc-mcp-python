# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com
"""普通 trpc HTTP 服务处理器（protocol: http）。

这些 handler 用 ``@routes.route`` 注册，与同进程内的 ``http_mcp`` MCP 服务共存，
用来证明：``http_mcp`` 的专用 codec 是隔离的，不会影响普通 ``http`` 服务。

``service_name`` 绑定到 ``trpc.test.mcp.Greeter2``：仅当该 service 以
``protocol: http`` 监听时（见 ``conf/trpc_python_mixed.yaml``）这些路由才会生效；
在默认配置里 Greeter2 是 ``http_mcp``，不是 aiohttp 监听，这些路由自然不会绑定，导入无副作用。
"""
from aiohttp import web

from trpc.context import Context
from trpc.http import routes
from trpc.log import logger

_HTTP_SERVICE = "trpc.test.mcp.Greeter2"


@routes.route("/ping", service_name=_HTTP_SERVICE)
async def ping(ctx: Context, request: web.Request) -> web.Response:
    """普通 HTTP GET 接口：返回 JSON。"""
    name = request.query.get("name", "world")
    logger.info(f"[plain-http] GET /ping name={name}")
    return web.json_response({"protocol": "http", "method": "GET", "msg": f"hello {name}"})


@routes.route("/echo", method="POST", service_name=_HTTP_SERVICE)
async def echo(ctx: Context, request: web.Request) -> web.Response:
    """普通 HTTP POST 接口：回显请求体。"""
    body = await request.text()
    logger.info(f"[plain-http] POST /echo body={body}")
    return web.json_response({"protocol": "http", "method": "POST", "echo": body})
