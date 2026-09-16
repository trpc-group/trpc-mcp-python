# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com
"""Filter server module"""

from trpc.trpc_abc.filter import Filter
from trpc.trpc_abc.filter import FilterReturnType
from trpc.plugin.plugin import PluginInitPos
from trpc.plugin.plugin import PluginType
from trpc.plugin.plugin import register_plugin
from trpc.log import logger
from trpc.context import Context

print("=========== register server filter ================== \n")


@register_plugin(PluginType.SERVER_FILTER_COMPONENT, "one", init_pos=PluginInitPos.MASTER)
class OneFilter(Filter):
    """First server-side filter in the filter chain"""

    async def run(self, ctx: Context, req, handle) -> FilterReturnType:
        """
        Execute the filter logic

        Args:
            ctx: Request context
            req: Request object
            handle: Next handler in the chain

        Returns:
            Response from the next handler
        """
        logger.info("one server filter")
        return await handle()


@register_plugin(PluginType.SERVER_FILTER_COMPONENT, "two", init_pos=PluginInitPos.MASTER)
class TwoFilter(Filter):
    """Second server-side filter in the filter chain"""

    async def run(self, ctx: Context, req, handle) -> FilterReturnType:
        """
        Execute the filter logic

        Args:
            ctx: Request context
            req: Request object
            handle: Next handler in the chain

        Returns:
            Response from the next handler
        """
        logger.info("two server filter")
        return await handle()


@register_plugin(PluginType.SERVER_FILTER_COMPONENT, "default", init_pos=PluginInitPos.MASTER)
class DefaultServerFilter(Filter):
    """Default server-side filter that logs request deadline information"""

    async def run(self, ctx: Context, req, handle) -> FilterReturnType:
        """
        Execute the default server filter logic with deadline logging

        Args:
            ctx: Request context containing deadline information
            req: Incoming request object
            handle: Next handler in the filter chain

        Returns:
            Response from the next handler in the chain
        """
        logger.info(f"default server filter; ctx deadline: {ctx.deadline}")
        return await handle()
