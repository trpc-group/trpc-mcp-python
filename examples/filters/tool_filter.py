# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com
from trpc.context import TrpcContext
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
