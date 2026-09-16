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

print("=========== register client filter ================== \n")


@register_plugin(PluginType.CLIENT_FILTER_COMPONENT, "default", init_pos=PluginInitPos.MASTER)
class DefaultClientFilter(Filter):
    """Default client-side filter that logs request deadline information"""

    async def run(self, ctx: Context, req, handle) -> FilterReturnType:
        """
        Execute the default client filter logic with deadline logging

        Args:
            ctx: Request context containing deadline information
            req: Incoming request object
            handle: Next handler in the filter chain

        Returns:
            Response from the next handler in the chain
        """
        logger.info(f"default client filter; ctx deadline: {ctx.deadline}")
        return await handle()
