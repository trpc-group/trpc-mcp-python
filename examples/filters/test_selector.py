# -*- coding: utf-8 -*-
#
# Copyright @ 2026 Tencent.com
"""Test selector filter"""

from typing import NoReturn

from trpc.trpc_abc.node import Node
from trpc.plugin.plugin import PluginType
from trpc.plugin.plugin import register_plugin
from trpc.plugin.plugin import PluginInitPos
from trpc.log import logger
from trpc.naming.option import SelectorOption
from trpc.trpc_abc.selector import BaseSelector


@register_plugin(PluginType.NAMING_SELECTOR, "test", init_pos=PluginInitPos.MASTER)
class TestSelectorFilter(BaseSelector):
    """Test selector filter"""

    def __init__(self):
        super().__init__()
        print("=========== TestSelectorFilter init ================== \n")

    async def select(self, service_name: str, opt: SelectorOption) -> Node:
        """Select a node"""
        namespace = opt.namespace
        logger.info(f"find_one_node: service_name: {service_name}, namespace: {namespace}")
        # NOTE: the node protocol is applied last (load_node_config -> with_protocol)
        # and overrides the connection options, so it must match the MCP backend
        # protocol (http_mcp). Returning plain "http" here would downgrade the
        # client codec and make the SSE POST's 202 ACCEPTED be treated as an error.
        if service_name == "trpc.test.mcp.Greeter1":
            host = "127.0.0.1"
            port = 8008
            protocol = "http_mcp"
            weight = 100
            metadata = {}
        elif service_name == "trpc.test.mcp.Greeter2":
            host = "127.0.0.1"
            port = 8009
            protocol = "http_mcp"
            weight = 100
            metadata = {}
        else:
            raise ValueError(f"service_name: {service_name} not found")
        node = Node(service_name=service_name,
                    address=f"{host}:{port}",
                    ip=host,
                    port=port,
                    protocol=protocol,
                    weight=weight,
                    metadata=metadata)
        return node

    async def report(self, node: Node, cost: int, success: int) -> NoReturn:
        """Report information

        :param node: The node to report
        :param cost: The cost
        :param success: The success result code
        """
        logger.info(f"report: node: {node.address}, cost: {cost}, success: {success}")
