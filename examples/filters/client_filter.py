# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Filter server module"""

from typing import Any

from trpc_sdk.abc import BaseFilter
from trpc_sdk.abc import FilterAsyncGenHandleType
from trpc_sdk.abc import FilterAsyncGenReturnType
from trpc_sdk.abc import FilterHandleType
from trpc_sdk.abc import FilterReturnType
from trpc_sdk.abc import PluginInitPos
from trpc_sdk.abc import PluginType
from trpc_sdk.abc import TrpcContext
from trpc_sdk.log import logger
from trpc_sdk.plugin import register_plugin

print("=========== register client filter ================== \n")


@register_plugin(PluginType.CLIENT_FILTER_COMPONENT, "default", init_pos=PluginInitPos.WORKER)
class DefaultClientFilter(BaseFilter):
    """Default client-side filter that logs request deadline information"""

    async def run(self, ctx: TrpcContext, req: Any, next_handle: FilterHandleType) -> FilterReturnType:
        """Log the request deadline, then run the rest of the chain.

        Args:
            ctx: Request context containing deadline information.
            req: Outgoing request object.
            next_handle: Next handler in the filter chain.

        Returns:
            ``(response, error)`` from the next handler.
        """
        logger.info(f"default client filter; ctx deadline: {ctx.deadline}")
        return await next_handle()

    async def run_stream(self, ctx: TrpcContext, req: Any,
                         next_handle: FilterAsyncGenHandleType) -> FilterAsyncGenReturnType:
        """Pass streaming results through unchanged."""
        async for result in next_handle():
            yield result
