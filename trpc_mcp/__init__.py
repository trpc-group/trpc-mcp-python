# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""
TRPC MCP Package Initialization Module

This module initializes the TRPC MCP package.
It imports and exposes core functionalities including server, client, tools,
resources and prompts implementations.

Key Components:
- MCP Server: TrpcFastMCPServer implementation
- MCP Client: McpProxy for client-side operations
- Tools: Function decorators and info classes
- Resources: Resource handling utilities
- Prompts: Prompt management system
"""

# Third-party imports
import logging

from mcp.server import sse
from mcp.server import websocket

# Local imports
# Imported for their import-time registrations: the http_mcp codecs/parsers/
# client transport, and the protocol starter.
from . import _codec  # noqa: F401  pylint: disable=unused-import
from . import _trpc_server_transport  # noqa: F401  pylint: disable=unused-import

from .mcp_api import get_http_req
from .mcp_api import get_http_rsp
from .mcp_api import get_mcp_server
from .mcp_api import get_remote_addr
from .mcp_api import get_server_addr
from .mcp_api import get_trpc_mcp_server_name
from .mcp_api import make_call_tool_result
from .mcp_api import get_session_func
from .mcp_api import register_mcp_server_cls
from .mcp_api import register_streamable_http_event_store
from .mcp_client import McpProxy
from .prompts import prompt
from .resources import resource
from .service_desc import register_trpc_mcp_server
from .tools import tool
from .utils import set_http_kwargs_to_context
from .utils import set_http_header_to_context
from .version import __version__

from ._config import get_mcp_client_config
from ._config import register_set_settings_func
from ._constants import MCP_STDIO
from ._constants import MCP_SSE
from ._constants import MCP_STREAMABLE_HTTP
from ._logging import bridge_third_party_loggers
from ._trpc_server_transport import TrpcMcpServerTransport

# Configure loggers
sse.logger = logging.getLogger("mcp.server.sse")
websocket.logger = logging.getLogger("mcp.server.websocket")
bridge_third_party_loggers()

__all__ = [
    "get_mcp_server",
    "get_http_req",
    "get_http_rsp",
    "get_remote_addr",
    "get_server_addr",
    "get_trpc_mcp_server_name",
    "get_trpc_mcp_server_name",
    "register_mcp_server_cls",
    "make_call_tool_result",
    "register_streamable_http_event_store",
    "register_set_settings_func",
    "get_mcp_client_config",
    "McpProxy",
    "TrpcMcpServerTransport",
    "prompt",
    "resource",
    "register_trpc_mcp_server",
    "get_session_func",
    "tool",
    "set_http_kwargs_to_context",
    "set_http_header_to_context",
    "__version__",
    "MCP_STDIO",
    "MCP_SSE",
    "MCP_STREAMABLE_HTTP",
    "bridge_third_party_loggers",
]
