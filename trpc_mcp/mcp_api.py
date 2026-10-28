# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""
TRPC MCP API Module

This module provides the core API interfaces for TRPC MCP (Microservice Control Protocol).
It includes server registration, configuration handling, and plugin setup functionality.
"""

from collections.abc import Callable
from typing import Any, Type, Optional

from mcp.server.streamable_http import EventStore
from mcp.server.fastmcp.utilities.func_metadata import _convert_to_content
from mcp.server.session import ServerSession
from mcp.types import CallToolResult
from starlette.requests import Request
from starlette.responses import Response

from trpc_sdk.abc import TrpcContext
from trpc_sdk.http import HTTP_REQ_KEY
from trpc_sdk.http import HTTP_RSP_KEY
from trpc_sdk.http import LOCAL_ADDR

from ._trpc_mcp_server import MCP_APP
from ._trpc_mcp_server import TrpcMcpServer
from ._trpc_server_transport import register_mcp_app
from ._config import get_mcp_server_options
from .utils import get_mcp_app


def get_mcp_server(ctx: Optional[TrpcContext] = None) -> TrpcMcpServer:
    """Retrieve the MCP server instance from TRPC context.

    Args:
        ctx: TRPC context object containing metadata; when it carries no app,
            the app of the current process is returned.

    Returns:
        TrpcMcpServer: The MCP server instance
    """
    if ctx is not None:
        mcp_app = ctx.get_meta_data(MCP_APP)
        if mcp_app is not None:
            return mcp_app
    return get_mcp_app()


def get_trpc_mcp_server_name(ctx: TrpcContext) -> str:
    """Retrieve the name of TRPC MCP server instance.

    Args:
        ctx: TRPC context object containing metadata

    Returns:
        str: Name of the MCP server instance
    """
    return get_mcp_server(ctx).name


def get_http_req(ctx: TrpcContext) -> Request:
    """Retrieve HTTP request object from TRPC context.

    Args:
        ctx: TRPC context object containing metadata

    Returns:
        Request: HTTP request object
    """
    return ctx.get_meta_data(HTTP_REQ_KEY)


def get_http_rsp(ctx: TrpcContext) -> Response:
    """Retrieve HTTP response object from TRPC context.

    Args:
        ctx: TRPC context object containing metadata

    Returns:
        Response: HTTP response object
    """
    return ctx.get_meta_data(HTTP_RSP_KEY)


def get_server_addr(ctx: TrpcContext) -> str:
    """Retrieve server address from TRPC context.

    Args:
        ctx: TRPC context object containing metadata

    Returns:
        str: Server address (hostname or IP)

    Note:
        Falls back to request host if local address is not available.
    """
    local_addr = ctx.get_meta_data(LOCAL_ADDR)
    if not local_addr:
        req = get_http_req(ctx)
        local_addr = req.url.netloc

    return local_addr


def get_remote_addr(ctx: TrpcContext) -> str:
    """Retrieve remote peer address from TRPC context.

    Args:
        ctx: TRPC context object containing metadata

    Returns:
        str: Remote peer IP address
    """
    return ctx.remote_ip


def get_session_func(ctx: TrpcContext) -> ServerSession:
    """Retrieve a session function wrapper from TRPC context.

    Args:
        ctx: TRPC context object containing metadata

    Returns:
        object: A dynamic wrapper for session functions, allowing async execution with TRPC context.
    """
    mcp_server: TrpcMcpServer = get_mcp_server(ctx)
    session = mcp_server.get_server_session()

    return session


def make_call_tool_result(result: Any, meta: dict) -> CallToolResult:
    """Create a CallToolResult object from the given result and metadata.

    Args:
        result: The result data to be converted into CallToolResult content.
        meta: A dictionary containing metadata for the result.

    Returns:
        CallToolResult: An object containing the converted result and metadata.
    """
    return CallToolResult(content=_convert_to_content(result), _meta=meta)


def register_mcp_server_cls(name: str) -> Callable:
    """Decorator factory for registering MCP server classes.

    Args:
        name: Unique name to identify the server class

    Returns:
        Callable: Decorator function that registers the class
    """

    def decorator(mc_cls: Type[TrpcMcpServer]) -> Type[TrpcMcpServer]:
        """Register an MCP server class implementation.

        Args:
            mc_cls: MCP server class to register

        Returns:
            TrpcMcpServer: The registered class
        """
        register_mcp_app(name, mc_cls())  # type: ignore
        return mc_cls  # type: ignore

    return decorator  # type: ignore


def register_streamable_http_event_store(name: str, event_store: EventStore) -> None:
    """Register an event store for streamable HTTP connections.

    Args:
        name: Unique name to identify the event store
        event_store: EventStore instance to be registered

    This function stores the event store in a global map that can be later
    retrieved by service name during MCP server initialization.
    """
    assert isinstance(event_store, EventStore)
    options = get_mcp_server_options()
    options.event_store = event_store
