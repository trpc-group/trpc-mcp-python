# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""
TRPC MCP Utilities Module

This module provides utility functions for TRPC MCP (Microservice Control Protocol).
It includes process management, data conversion and context handling utilities.
"""
import inspect
import socket
import warnings
from functools import wraps
from urllib.parse import urlparse
from typing import Callable, Any

from mcp.server.fastmcp.server import FastMCP

from trpc_sdk.abc import TrpcContext
from trpc_sdk.common import get_current_process_var
from trpc_sdk.common import set_current_process_var
from trpc_sdk.http import HTTP_ARGS_META_KEY
from trpc_sdk.log import logger

from ._constants import TRPC_MCP_PROCESS_VAR

set_object_to_process = set_current_process_var
get_object_to_process = get_current_process_var


def get_object_to_process_with_default(name: str, cls_obj):
    """Get an object from current process with default value.

    Args:
        name: Attribute name to get
        cls_obj: Default class to instantiate if not found

    Returns:
        The stored object or a new instance of cls_obj
    """
    val = get_current_process_var(name, None)
    if val is None:
        val = cls_obj()
        set_current_process_var(name, val)
    return val


def normalize_path(mount_path: str, endpoint: str) -> str:
    """
    Combine mount path and endpoint to return a normalized path.
    Args:
        mount_path: The mount path (e.g. "/github" or "/")
        endpoint: The endpoint path (e.g. "/messages/")
    Returns:
        Normalized path (e.g. "/github/messages/")
    """
    # Special case: root path
    if mount_path == "/" or not mount_path:
        # Ensure endpoint starts with slash
        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"
        return endpoint

    if mount_path and not mount_path.startswith("/"):
        mount_path = f"/{mount_path}"

    # Remove trailing slash from mount path
    if mount_path and mount_path.endswith("/"):
        mount_path = mount_path[:-1]

    # Ensure endpoint starts with slash
    if not endpoint.startswith("/"):
        endpoint = f"/{endpoint}"

    # Combine paths
    return f"{mount_path}{endpoint}"


def make_url(host: str, base_url: str = "", endpoint: str = "sse") -> str:
    """Construct SSE endpoint URL based on host and base URL.

    A host without a scheme (IP:port or domain) is addressed over ``http://``.

    Args:
        host: Host address (IP:port or domain)
        base_url: Optional base URL path

    Returns:
        str: Constructed SSE endpoint URL
    """
    result = urlparse(host)
    if result.scheme:
        return host

    if not result.scheme or not result.netloc:
        if host.count("://") == 1:
            return host

    return f"http://{host}{normalize_path(base_url, endpoint)}"


_HTTP_HEADER: str = "_mcp_http_header"


def set_http_header_to_context(ctx: TrpcContext, headers: dict[str, str]) -> None:
    """Set headers to TRPC context.

    Args:
        ctx: TRPC context object
        headers: Dictionary of headers to set
    """
    ctx.with_meta_data(_HTTP_HEADER, headers)


def get_http_header_from_context(ctx: TrpcContext) -> dict[str, Any]:
    """Get headers from TRPC context.

    Args:
        ctx: TRPC context object

    Returns:
        Dictionary of headers
    """
    return ctx.meta_data.get(_HTTP_HEADER, {})


def set_http_kwargs_to_context(ctx: TrpcContext, kwargs: dict[str, str]) -> None:
    """Store HTTP request kwargs in TRPC context metadata.

    Args:
        ctx: TRPC context object
        kwargs: Dictionary containing HTTP request parameters
              (e.g. query params, form data, etc.)
    """
    ctx.with_meta_data(HTTP_ARGS_META_KEY, kwargs)


def get_http_kwargs_from_context(ctx: TrpcContext) -> dict[str, Any]:
    """Retrieve HTTP request kwargs from TRPC context metadata.

    Args:
        ctx: TRPC context object

    Returns:
        Dictionary containing stored HTTP request parameters.
        Returns empty dict if no kwargs found.
    """
    return ctx.meta_data.get(HTTP_ARGS_META_KEY, {})


def deprecated(details: str = ""):
    """Deprecated decorator factory function."""

    def decorator(func: Callable) -> Callable:

        @wraps(func)
        def wrapper(*args, **kwargs):
            message = f"{func.__name__} is deprecated and will be removed in a future version."
            if details:
                message += f" {details}"
            logger.warning(message)
            warnings.warn(message, DeprecationWarning, stacklevel=2)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def analyze_init_method(cls) -> dict:
    """Analyze the __init__ method parameters of a class.

    Args:
        cls: The class to analyze (must have __init__ method)

    Returns:
        dict: A dictionary mapping parameter names to their default values.
        Returns empty dict if class has no __init__ method.

    Example:
        >>> class Test:
        ...     def __init__(self, a=1, b='x'): pass
        >>> analyze_init_method(Test)
        {'a': 1, 'b': 'x'}

    Note:
        The 'self' parameter is automatically skipped in the analysis.
    """
    if not hasattr(cls, '__init__'):
        return {}
    keywords_map = {}
    signature = inspect.signature(cls.__init__)
    for name, param in signature.parameters.items():
        if name == 'self':
            continue
        keywords_map[name] = param.default
    return keywords_map


def create_uvicorn_compatible_socket(host: str, port: int) -> socket.socket:
    """Create a socket suitable for uvicorn in multi-worker TRPC processes.

    ``SO_REUSEPORT`` lets every rpc task (separate mode) or peer worker bind
    the same address.

    Raises:
        OSError: If the socket cannot be bound.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except OSError:
        pass
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    return sock


_SSE_URL: str = "/sse"  # Default SSE endpoint path
_SSE_MESSAGE_URL: str = "/messages/"  # Default message endpoint path
_STREAMABLE_HTTP_URL: str = "/mcp"  # Default message endpoint path


def make_all_mcp_url(base_url: str) -> tuple[str, str, str]:
    """Create all MCP URLs by combining base URL and path.

    Args:
        base_url: Base URL to prepend

    Returns:
        tuple: A tuple containing the SSE endpoint URL, message endpoint URL, and streamable HTTP endpoint URL
    """
    sse_ep = normalize_path(base_url, _SSE_URL)
    sse_msg = normalize_path(base_url, _SSE_MESSAGE_URL)
    streamable_http = normalize_path(base_url, _STREAMABLE_HTTP_URL)
    return sse_ep, sse_msg, streamable_http


def get_mcp_app() -> FastMCP:
    """Retrieve the MCP application from current process.

    Returns:
        FastMCP: The MCP application instance

    Raises:
        ValueError: If MCP app is not found in current process
    """
    mcp_process = get_current_process_var(TRPC_MCP_PROCESS_VAR)
    mcp_app = getattr(mcp_process, "mcp_app", None)
    if mcp_app is None:
        raise ValueError("MCP app not found in current process")
    return mcp_app
