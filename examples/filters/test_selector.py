# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Test selector filter"""

from trpc_sdk.abc import BaseSelector
from trpc_sdk.abc import Node
from trpc_sdk.abc import PluginInitPos
from trpc_sdk.abc import PluginType
from trpc_sdk.abc import SelectorOption
from trpc_sdk.log import logger
from trpc_sdk.plugin import register_plugin


@register_plugin(PluginType.NAMING_SELECTOR, "test", init_pos=PluginInitPos.WORKER)
class TestSelectorFilter(BaseSelector):
    """Test selector filter"""

    def __init__(self):
        super().__init__()
        print("=========== TestSelectorFilter init ================== \n")

    async def select(self, service_name: str, opt: SelectorOption) -> Node:
        """Select a node"""
        namespace = opt.namespace
        logger.info(f"find_one_node: service_name: {service_name}, namespace: {namespace}")
        # NOTE: the node protocol is applied last (load_node_config -> set_protocol)
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

    async def report(self, node: Node, cost: int, code: int) -> bool:
        """Log the call outcome.

        Args:
            node: The node that handled the call.
            cost: Call duration in milliseconds.
            code: Result code of the call.

        Returns:
            Always ``True``.
        """
        logger.info(f"report: node: {node.address}, cost: {cost}, code: {code}")
        return True
