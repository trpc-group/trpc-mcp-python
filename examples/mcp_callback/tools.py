# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com
"""MCP Tool Callback Implementations.

This module contains tool handler implementations for MCP protocol.
Each function is decorated with @trpc_mcp.tool to register it as a tool handler.
Includes functionality for:
- Echoing text
- Executing shell commands
- Basic arithmetic operations
"""
import os
import subprocess
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field
import mcp.types as types
from trpc.context import TrpcContext

import trpc_mcp


async def _allowed_directories(ctx: TrpcContext) -> list[types.TextContent]:
    """Get list of allowed directories from MCP server.

    Args:
        mcp_server: MCP server instance

    Returns:
        List of allowed directory paths

    Note:
        Requires client to register list_roots_callback for proper functionality.
    """
    allowed_dirs = []
    session = trpc_mcp.get_session_func(ctx)
    result: types.ListRootsResult = await session.list_roots()
    print(f"\n\n xxx list root result is {result} \n\n")
    for item in result.roots:
        scheme = item.uri.scheme
        if scheme and scheme != "file":
            raise ValueError(f"Scheme {scheme} is not support yet")
        allowed_dirs.append(str(item.uri))
    return [types.TextContent(type="text", text=f"Allowed directories:\n{os.linesep.join(allowed_dirs)}")]


# 不指定 mcp_name 时会注册到所有配置的 MCP service。
# 适用场景：server 端 tool 需要访问本地文件、目录索引或代码仓库等客户端资源前，
# 先通过 MCP Roots 能力询问客户端允许访问哪些根目录，避免服务端自行假设可访问范围。
@trpc_mcp.tool(name="allowed_directories",
               description="List root directories allowed by the MCP client",
               structured_output=False)
async def allowed_directories(ctx: TrpcContext) -> list[types.TextContent]:
    """List client-approved root directories for filesystem-related tools."""
    return await _allowed_directories(ctx)


class WeatherData(BaseModel):
    """Structured weather data response"""

    temperature: float = Field(description="Temperature in Celsius")
    humidity: float = Field(description="Humidity percentage (0-100)")
    condition: str = Field(description="Weather condition (sunny, cloudy, rainy, etc.)")
    wind_speed: float = Field(description="Wind speed in km/h")
    location: str = Field(description="Location name")
    timestamp: datetime = Field(default_factory=datetime.now, description="Observation time")


@trpc_mcp.tool(name="get_weather", description="get_weather", structured_output=True, mcp_name="trpc.test.mcp.Greeter1")
def get_weather(ctx: TrpcContext, city: str) -> WeatherData:
    """Get current weather for a city with full structured data"""
    # In a real implementation, this would fetch from a weather API
    return WeatherData(temperature=22.5, humidity=65.0, condition="partly cloudy", wind_speed=12.3, location=city)


# 绑定到 trpc.test.mcp.Greeter1
@trpc_mcp.tool(name="echo_tool",
               description="echo some text",
               structured_output=True,
               mcp_name="trpc.test.mcp.Greeter1")
async def echo_tool(ctx: TrpcContext, text: str) -> str:
    """Echo tool that returns input text with server metadata.

    Args:
        ctx: TRPC context object containing metadata
        text: Input text to echo

    Returns:
        Formatted string containing server info and input text
    """
    mcp_name = trpc_mcp.get_trpc_mcp_server_name(ctx)
    server_addr = trpc_mcp.get_server_addr(ctx)
    # mcp_server = trpc_mcp.get_mcp_server(ctx)
    # Note stateless streamable not use
    ret = "stateless streamable"
    print(f"\n\n list root ret is {ret} \n\n")
    # ret = await _allowed_directories(ctx)
    print(f"\n\n list root ret is {ret} \n\n")
    name = "echo_tool"
    info = f"mcp_name: {mcp_name}-server_addr: {server_addr}-tool_name: {name}-args: {text}"
    print(info)
    return info


# 绑定到 trpc.test.mcp.Greeter1
@trpc_mcp.tool(name="show_tool", description="show some text", mcp_name="trpc.test.mcp.Greeter1")
def show_tool(ctx: TrpcContext, text: str) -> str:
    """Display tool that shows input text with server metadata.

    Args:
        ctx: TRPC context object containing metadata
        text: Input text to display

    Returns:
        Formatted string containing server info and input text
    """
    mcp_name = trpc_mcp.get_trpc_mcp_server_name(ctx)
    server_addr = trpc_mcp.get_server_addr(ctx)
    name = "show_tool"
    info = f"mcp_name: {mcp_name}-server_addr: {server_addr}-tool_name: {name}-args: {text}"
    print(info)
    return info


# 绑定到 trpc.test.mcp.Greeter2
@trpc_mcp.tool(name="shell_tool", description="exec shell", mcp_name="trpc.test.mcp.Greeter2")
def shell_tool(ctx: TrpcContext, cmd: str) -> str:
    """Execute shell command and return results.

    Args:
        ctx: TRPC context object containing metadata
        cmd: Shell command to execute

    Returns:
        Formatted string containing:
        - Server info
        - Command output (if successful)
        - Error message (if command failed)
    """
    mcp_name = trpc_mcp.get_trpc_mcp_server_name(ctx)
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    server_addr = trpc_mcp.get_server_addr(ctx)
    name = "shell_tool"
    info = f"mcp_name: {mcp_name}-server_addr: {server_addr}-tool_name: {name}-args: {cmd}"
    print(info)
    if result.returncode == 0:
        return f"{info}-exec_ret:{result.stdout}"
    return f"{info}-exec_ret:{result.stderr}"


@trpc_mcp.tool(name="common_tool", description="Bind to all service", structured_output=False)
def common_tool(ctx: TrpcContext, text: str) -> types.CallToolResult:
    """Display tool that shows input text with server metadata.

    Args:
        ctx: TRPC context object containing metadata
        text: Input text to display

    Returns:
        Formatted string containing server info and input text
    """
    mcp_name = trpc_mcp.get_trpc_mcp_server_name(ctx)
    server_addr = trpc_mcp.get_server_addr(ctx)
    name = "common_tool"
    info = f"mcp_name: {mcp_name}-server_addr: {server_addr}-tool_name: {name}-args: {text}"
    print(info)
    res = trpc_mcp.make_call_tool_result(info, meta={"common_tool": text})
    return res


# 不指定 mcp_name -> 注册到所有 service（公共工具）。
# 用途：回显客户端通过 set_http_header_to_context 设置的 HTTP 头部，用来验证
# 客户端自定义头部确实透传到了服务端（SSE 与 streamable-http 均可验证）。
@trpc_mcp.tool(name="echo_header", description="Echo back a client-sent HTTP header for verification")
def echo_header(ctx: TrpcContext, key: str) -> str:
    """Return the value of an incoming HTTP header named ``key``.

    The client sets headers via ``trpc_mcp.set_http_header_to_context`` and the
    httpx transport injects them into every HTTP request, so the server can read
    them back from the raw request object.
    """
    req = trpc_mcp.get_http_req(ctx)
    value = req.headers.get(key)
    info = f"{key}={value}"
    print(f"echo_header -> {info}")
    return info


# 演示 icons / meta（FastMCP 1.13+/1.16+ 才支持，trpc-mcp 已做版本自适应透传）。
# - icons: 给 tool 关联展示用图标（SEP-973），客户端 list_tools 时拿得到。
# - meta:  附带任意机器可读元数据（如 OpenAI Apps 约定），随 tool 定义返回。
# 不指定 mcp_name -> 注册到所有 service。
@trpc_mcp.tool(name="branded_tool",
               title="Branded Echo",
               description="Echo text; also carries icons + meta to demo MCP metadata passthrough",
               icons=[types.Icon(src="https://example.com/icon-48.png", mimeType="image/png", sizes=["48x48"])],
               meta={
                   "category": "demo",
                   "vendor": "trpc-mcp"
               })
def branded_tool(ctx: TrpcContext, text: str) -> str:
    """Plain echo tool used to demonstrate tool-level icons/meta."""
    info = f"branded_tool args: {text}"
    print(info)
    return info


# 不指定 mcp_name, 默认指定到所以配置的mcp中
@trpc_mcp.tool(name="add", description="add tool")
def add(ctx: TrpcContext, a: Annotated[int, Field(description="The first integer addend.")],
        b: Annotated[int, Field(description="The second integer addend.")]) -> int:
    """Basic addition tool that sums two numbers.

    Args:
        ctx: TRPC context object containing metadata
        a: First number to add
        b: Second number to add

    Returns:
        Sum of a and b
    """
    mcp_name = trpc_mcp.get_trpc_mcp_server_name(ctx)
    server_addr = trpc_mcp.get_server_addr(ctx)
    name = "add"
    info = f"mcp_name: {mcp_name}-server_addr: {server_addr}-tool_name: {name}-args: a: {a}, b:{b}"
    print(info)
    return a + b
