# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com
"""MCP Resource Callback Implementations.

This module contains resource handler implementations for MCP protocol.
Each function is decorated with @trpc_mcp.resource to register it as a resource handler.
"""
from trpc.context import TrpcContext

import trpc_mcp

# 如果 'echo://static' 绑定到 'trpc.test.mcp.Greeter1' 在 'trpc.test.mcp.Greeter2'
# 也可以匹配


@trpc_mcp.resource(uri="echo://static",
                   name="echo_resource",
                   description="echo resource",
                   mcp_name="trpc.test.mcp.Greeter1")
def echo_resource(ctx: TrpcContext) -> str:
    """Static echo resource handler that returns server info.
    
    Args:
        ctx: TRPC context object containing metadata
        
    Returns:
        Formatted string containing server info and static resource message
    """
    mcp_name = trpc_mcp.get_trpc_mcp_server_name(ctx)
    server_addr = trpc_mcp.get_server_addr(ctx)
    name = "echo_resource"
    info = f"mcp_name: {mcp_name}-server_addr: {server_addr}-resource_name: {name}-args:none"
    print(info)
    return f"this is resource: {info}!"


@trpc_mcp.resource(uri="template://{text}", mcp_name="trpc.test.mcp.Greeter2")
def echo_template(ctx: TrpcContext, text: str) -> str:
    """Template resource handler that echoes dynamic input text.
    
    Args:
        ctx: TRPC context object containing metadata
        text: Input text to process
        
    Returns:
        Formatted string containing server info and processed text
    """
    mcp_name = trpc_mcp.get_trpc_mcp_server_name(ctx)
    server_addr = trpc_mcp.get_server_addr(ctx)
    name = "echo_template"
    info = f"mcp_name: {mcp_name}-server_addr: {server_addr}-resource_name: {name}-args: {text}"
    print(info)
    return f"this is template: {info}"


@trpc_mcp.resource(uri="common://{data}")
def common_template(ctx: TrpcContext, data: str) -> str:
    """Common template resource handler for general use cases.
    
    Args:
        ctx: TRPC context object containing metadata
        data: Input data to process
        
    Returns:
        Formatted string containing server info and processed data
    """
    mcp_name = trpc_mcp.get_trpc_mcp_server_name(ctx)
    server_addr = trpc_mcp.get_server_addr(ctx)
    name = "common_template"
    info = f"mcp_name: {mcp_name}-server_addr: {server_addr}-resource_name: {name}-args: {data}"
    print(info)
    return f"this is template: {info}"
