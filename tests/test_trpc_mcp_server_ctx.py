# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Tests for TRPC context-aware FastMCP registration."""

import inspect

from trpc_sdk.abc import TrpcContext

from trpc_mcp._trpc_mcp_server import TrpcMcpServer


def test_tool_resource_prompt_can_use_trpc_context_first_arg():
    server = TrpcMcpServer(name="ctx-test")

    @server.tool()
    def echo(ctx: TrpcContext, text: str) -> str:
        return text

    @server.resource("ctx://{name}")
    def resource(ctx: TrpcContext, name: str) -> str:
        return name

    @server.prompt()
    def prompt(ctx: TrpcContext, name: str) -> str:
        return name

    tool = server._tool_manager.get_tool("echo")
    assert "ctx" not in tool.parameters["properties"]
    assert "text" in tool.parameters["properties"]
    assert list(inspect.signature(tool.fn).parameters) == ["text"]
