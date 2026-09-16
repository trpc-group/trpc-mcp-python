# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com
"""Constants for TRPC MCP Plugin.

This module defines all constants used by the TRPC MCP plugin.
It includes protocol definitions, plugin metadata, and other configuration constants required for the plugin operation.
"""
from typing import Final

TRPC_MCP_PROTOCOL = "http_mcp"
CALLBACK_NAME: str = "__trpc_mcp_callback"
HTTP_CODE: str = "status_code"
# Message type constants
MESSAGE_TYPE = "type"  # Key for message type in message dictionary

# HTTP related constants
HTTP_HEADERS = "headers"  # Key for HTTP headers in message dictionary
HTTP_BODY = "body"  # Key for HTTP body content in message dictionary
HTTP_STATUS = "status"  # Key for HTTP status code in message dictionary
HTTP_MORE_BODY = "more_body"  # Flag indicating if there is more body content
HTTP_REQUEST = "http.request"  # Identifier for HTTP request messages
HTTP_RESPONSE_BODY = "http.response.body"  # Identifier for HTTP response body
HTTP_RESPONSE_BODY_EVENT = "HTTPResponseBodyEvent"  # Event type for HTTP response body
HTTP_NAME = "http"

# Context and naming constants
TRPC_CTX = "ctx"  # Key for TRPC context in message dictionary
TRPC_MCP_PROCESS_NAME = "__TRPC_MCP_PROCESS_NAME"  # Process name identifier for MCP
TRPC_MCP_SERVER_NAME = "TrpcFastMCP"  # Server name for MCP

MCP_NAME = "mcp"  # Identifier for MCP plugin in TRPC system
MCP_DEFAULT_SERVICE = "mcp_default"  # Default service name for MCP
MCP_STDIO = "stdio"  # Identifier for stdio communication
MCP_SSE = "sse"  # Identifier for Server-Sent Events communication
MCP_STREAMABLE_HTTP = "streamable-http"  # Identifier for streamable HTTP communication

STATELESS_HTTP = "stateless_http"  # Identifier for stateless HTTP communication
POLARIS = "polaris"  # Identifier for Polaris service discovery
TARGET = "target"  # Key for target service address in Polaris

HOST = "host"  # Key for host address in Polaris
PORT = "port"  # Key for port number in Polaris
OPTIONS = "options"  # Key for additional options in Polaris
GET_METHOD: Final[str] = "GET"
CONTENT_TYPE: str = "Content-Type"
CONTENT_ENCODING: Final[str] = "Content-Encoding"

SSE_PATH_CONF = "sse_path"
SSE_MESSAGE_PATH_CONF = "message_path"
STREAMABLE_HTTP_PATH_CONF = "streamable_http_path"
