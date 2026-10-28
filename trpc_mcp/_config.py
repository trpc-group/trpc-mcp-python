# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""
TRPC MCP Configuration Module

This module defines the configuration classes and utilities for TRPC MCP.
It provides configuration structures for both server and client components.
"""

from dataclasses import dataclass
from dataclasses import field
from typing import Callable, Dict, Optional, List

from mcp.server.fastmcp.server import Settings
from mcp.server.fastmcp.server import FastMCP
from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from mcp.server.auth.provider import TokenVerifier
from mcp.server.streamable_http import EventStore
from mcp.server.fastmcp.tools import Tool

from trpc_sdk.config import TrpcConfig
from trpc_sdk.config import TrpcConfigParser

from ._constants import MCP_NAME
from ._constants import STATELESS_HTTP
from ._constants import SSE_PATH_CONF
from ._constants import SSE_MESSAGE_PATH_CONF
from ._constants import STREAMABLE_HTTP_PATH_CONF
from .utils import analyze_init_method
from .utils import make_all_mcp_url


def trpc_dataclass(cls, *args, **kwargs):
    """Decorator that enhances dataclass with TRPC-specific functionality.

    Args:
        cls: The class to be decorated
        *args: Variable length argument list
        **kwargs: Arbitrary keyword arguments

    Returns:
        The decorated class with enhanced __init__ documentation if fields_map exists.
    """
    cls = dataclass(cls, *args, **kwargs)
    fields_map = getattr(cls, "fields_map", None)
    if fields_map:
        init_func = getattr(cls, '__init__')
        init_func.__doc__ = fields_map()
    return cls


@trpc_dataclass
class McpServerConfig:
    """Configuration for MCP server component.

    Attributes:
        name: Server implementation name (default: "TrpcFastMCP")
        instructions: Additional instructions for server
        transport: Communication protocol (default: "sse")
        base_url: Base URL for server
        settings: Additional server settings
        redis: Redis configuration
    """
    name: str = "TrpcFastMCP"
    instructions: str = None
    transport: str = "sse"  # stdio
    base_url: str = ""
    # default: {'stateless_http': True}
    settings: dict = field(default_factory=lambda: {'stateless_http': True})
    redis: dict = field(default_factory=dict)


@trpc_dataclass
class McpClientConfig:
    """Configuration for MCP client component.

    Attributes:
        host: Server host address
        namespace: Namespace for client
        transport: Communication protocol (default: "sse")
        base_url: Base URL prefix configured on the MCP server (must match the
            server-side ``base_url``); used to build the MCP endpoint path.
    """
    host: str = ""
    namespace: str = ""
    transport: str = "sse"  # stdio
    base_url: str = ""


@trpc_dataclass
class McpConfig:
    """Main configuration container for MCP.

    Attributes:
        server: Server configuration
        client: Client configuration
    """
    server: McpServerConfig = None
    client: McpClientConfig = None

    @classmethod
    def fields_map(cls):
        """Generate documentation for configuration fields.

        Returns:
            str: Documentation string describing the configuration parameters.
        """
        return """
        :param server: Server configuration
        :param client: Client configuration
        """


def load_mcp_config() -> McpConfig:
    """Load and initialize MCP configuration from TRPC global plugins config.

    Returns:
        McpConfig: Initialized MCP configuration with default values for missing settings.
    """
    conf_dict: dict = (TrpcConfig.plugins_config() or {}).get(MCP_NAME) or {}
    mcp_config = McpConfig()
    TrpcConfigParser.populate_from_dict(conf_dict, mcp_config)
    mcp_config.server = mcp_config.server or McpServerConfig()
    mcp_config.client = mcp_config.client or McpClientConfig()
    if STATELESS_HTTP not in mcp_config.server.settings:
        mcp_config.server.settings[STATELESS_HTTP] = True
    sse_url, sse_messages_url, streamable_http_url = make_all_mcp_url(mcp_config.server.base_url)
    mcp_config.server.settings[SSE_PATH_CONF] = sse_url
    mcp_config.server.settings[SSE_MESSAGE_PATH_CONF] = sse_messages_url
    mcp_config.server.settings[STREAMABLE_HTTP_PATH_CONF] = streamable_http_url
    return mcp_config


DEFAULT_SETTING = analyze_init_method(FastMCP)


def _default_full_settings(config: Dict) -> Settings:
    """Generate a Settings object with default values for missing required fields.

    Args:
        config: A dictionary containing configuration values. Missing required fields
               will be filled with default values from the FastMCP class.

    Returns:
        Settings: A Settings object initialized with the provided and default values.
                 Any keys not present in Settings.model_fields will be removed.
    """
    global DEFAULT_SETTING
    for key, val in Settings.model_fields.items():
        if key not in config:
            if val.is_required():
                config[key] = DEFAULT_SETTING[key]

    for key in list(config.keys()):
        if key not in Settings.model_fields:
            config.pop(key)

    return Settings(**config)


__SET_SETTINGS_FUNC: Callable[[Dict], Settings] = _default_full_settings


def register_set_settings_func(func: Callable[[Dict], Settings]):
    """Register a function to generate full settings.

    Args:
        func: A callable that takes a dictionary and returns a Settings object.
    """
    global __SET_SETTINGS_FUNC
    __SET_SETTINGS_FUNC = func


def get_set_settings_func() -> Callable[[Dict], Settings]:
    """Get the currently registered function for generating full settings.

    Returns:
        Callable[[Dict], Settings]: The currently registered callable.
    """
    return __SET_SETTINGS_FUNC


def get_mcp_server_config() -> McpServerConfig:
    """Retrieve MCP server configuration from loaded MCP config.

    Returns:
        McpServerConfig: MCP server configuration
    """
    mcp_config = load_mcp_config()
    return mcp_config.server


def get_mcp_client_config() -> McpClientConfig:
    """Retrieve MCP client configuration from loaded MCP config.

    Returns:
        McpClientConfig: MCP client configuration (host/namespace/transport/base_url)
    """
    mcp_config = load_mcp_config()
    return mcp_config.client


@dataclass
class McpServerOptions:
    """Authentication server provider.

    Attributes:
        client_id: The client ID.
        client_secret: The client secret.
    """
    auth_server_provider: Optional[OAuthAuthorizationServerProvider] = None
    token_verifier: Optional[TokenVerifier] = None
    event_store: Optional[EventStore] = None
    tools: Optional[List[Tool]] = None


_mcp_server_options: McpServerOptions = McpServerOptions()


def set_mcp_server_options(options: McpServerOptions):
    """Set the MCP server options.

    Args:
        options: The MCP server options.
    """
    global _mcp_server_options
    _mcp_server_options = options


def get_mcp_server_options() -> McpServerOptions:
    """Get the MCP server options.

    Returns:
        McpServerOptions: The MCP server options.
    """
    return _mcp_server_options
