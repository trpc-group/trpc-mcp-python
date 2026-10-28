# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Plain trpc HTTP handlers (protocol: http).

These handlers are registered with ``@route`` and coexist with the in-process
``http_mcp`` service. They show that the ``http_mcp`` codec is isolated and does
not affect a plain ``http`` service.

``service_name`` is bound to ``trpc.test.mcp.Greeter2``. The routes take effect
only when that service listens with ``protocol: http`` (see
``conf/trpc_python_mixed.yaml``). In the default config Greeter2 is ``http_mcp``
rather than an aiohttp listener, so the routes stay unbound and importing this
module has no side effect.
"""
from aiohttp import web

from trpc_sdk.abc import TrpcContext
from trpc_sdk.http import route
from trpc_sdk.log import logger

_HTTP_SERVICE = "trpc.test.mcp.Greeter2"


@route("/ping", service_name=_HTTP_SERVICE)
async def ping(ctx: TrpcContext, request: web.Request) -> web.Response:
    """Plain HTTP GET handler that returns JSON."""
    name = request.query.get("name", "world")
    logger.info(f"[plain-http] GET /ping name={name}")
    return web.json_response({"protocol": "http", "method": "GET", "msg": f"hello {name}"})


@route("/echo", method="POST", service_name=_HTTP_SERVICE)
async def echo(ctx: TrpcContext, request: web.Request) -> web.Response:
    """Plain HTTP POST handler that echoes the request body."""
    body = await request.text()
    logger.info(f"[plain-http] POST /echo body={body}")
    return web.json_response({"protocol": "http", "method": "POST", "echo": body})
