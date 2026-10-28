# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""MCP Prompt Callback Implementations.

This module contains prompt handler implementations for MCP protocol.
Each function is decorated with @trpc_mcp.prompt to register it as a prompt handler.
"""
from trpc_sdk.abc import TrpcContext

import trpc_mcp


@trpc_mcp.prompt(name="echo_prompt", description="echo prompt", mcp_name="trpc.test.mcp.Greeter1")
def echo_prompt(ctx: TrpcContext, prompt: str) -> str:
    """Echo prompt handler that returns the input prompt with server info.
    
    Args:
        ctx: TRPC context object containing metadata
        prompt: Input prompt text to echo
        
    Returns:
        Formatted string containing server info and prompt text
    """
    mcp_name = trpc_mcp.get_trpc_mcp_server_name(ctx)
    server_addr = trpc_mcp.get_server_addr(ctx)
    name = "echo_prompt"
    info = f"mcp_name: {mcp_name}-server_addr: {server_addr}-prompt_name: {name}-args: {prompt}"
    print(info)
    return info


@trpc_mcp.prompt(name="show_prompt", description="show prompt", mcp_name="trpc.test.mcp.Greeter2")
def show_prompt(ctx: TrpcContext, prompt: str) -> str:
    """Display prompt handler that shows the input prompt with server info.
    
    Args:
        ctx: TRPC context object containing metadata
        prompt: Input prompt text to display
        
    Returns:
        Formatted string containing server info and prompt text
    """
    mcp_name = trpc_mcp.get_trpc_mcp_server_name(ctx)
    server_addr = trpc_mcp.get_server_addr(ctx)
    name = "echo_prompt"
    info = f"mcp_name: {mcp_name}-server_addr: {server_addr}-prompt_name: {name}-args: {prompt}"
    print(info)
    return info


@trpc_mcp.prompt(name="common_prompt", description="common prompt")
def common_prompt(ctx: TrpcContext, prompt: str) -> str:
    """Generic prompt handler for common use cases.
    
    Args:
        ctx: TRPC context object containing metadata
        prompt: Input prompt text to process
        
    Returns:
        Formatted string containing server info and prompt text
    """
    mcp_name = trpc_mcp.get_trpc_mcp_server_name(ctx)
    server_addr = trpc_mcp.get_server_addr(ctx)
    name = "common_prompt"
    info = f"mcp_name: {mcp_name}-server_addr: {server_addr}-prompt_name: {name}-args: {prompt}"
    print(info)
    return info
