# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
from trpc_sdk.abc import TrpcContext
from trpc_mcp.tools import ToolFilterParams
from trpc_mcp.tools import register_tool_filter
from trpc_mcp.tools import ToolFilterBase


@register_tool_filter
class EchoToolFilter(ToolFilterBase):

    def __init__(self) -> None:
        super().__init__()
        self._name = "echo_tool"

    async def pre_call(self, ctx: TrpcContext, params: ToolFilterParams) -> bool:
        print("\n\n EchoToolFilter pre_call \n\n")
        return True

    async def post_call(self, ctx: TrpcContext, params: ToolFilterParams) -> bool:
        print("\n\n EchoToolFilter post_call \n\n")
        return True
