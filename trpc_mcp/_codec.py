# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""HTTP codecs and plugin registrations for the ``http_mcp`` protocol.

Every plugin is registered at import time: ``create_server`` calls
``ServiceOption.set_protocol`` and clients call ``Options().set_protocol``,
and both look the plugins up right away.
"""

import http

from aiohttp import hdrs
from trpc_sdk.abc import BasePlugin
from trpc_sdk.abc import PluginInitPos
from trpc_sdk.abc import PluginType
from trpc_sdk.abc import TrpcContext
from trpc_sdk.abc import TrpcMessage
from trpc_sdk.abc import get_message
from trpc_sdk.exceptions import ClientInvokeError
from trpc_sdk.exceptions import TrpcErrorCode
from trpc_sdk.exceptions import TrpcErrorType
from trpc_sdk.exceptions import TrpcException
from trpc_sdk.http import ClientHttpCodec
from trpc_sdk.http import ClientHttpParser
from trpc_sdk.http import HTTP_TRPC_HEADER
from trpc_sdk.http import HttpClientTransport
from trpc_sdk.http import ServerHttpCodec
from trpc_sdk.http import ServerHttpParser
from trpc_sdk.http import find_compress_type
from trpc_sdk.http import find_http_status
from trpc_sdk.http import get_trpc_error_code
from trpc_sdk.plugin import register_plugin

from ._constants import TRPC_MCP_PROTOCOL
from .version import __version__ as trpc_mcp_version


class TrpcMcpServerHttpCodec(ServerHttpCodec):
    """HTTP codec that works with the Starlette request/response used by MCP transport."""

    def encode_data(self, context: TrpcContext, body: bytes) -> bytes:
        """Write Content-Type, error status and tRPC headers onto the Starlette response.

        Args:
            context: Server request context whose message holds the Starlette
                request and response as ``server_raw_req`` / ``server_raw_rsp``.
            body: Already-serialized response body.

        Returns:
            ``body`` unchanged.
        """
        message: TrpcMessage = get_message(context)
        request = message.server_raw_req
        response = message.server_raw_rsp

        content_type = response.headers.get(hdrs.CONTENT_TYPE, "")
        if content_type == "":
            req_content_type = request.headers.get(hdrs.CONTENT_TYPE, "")
            if req_content_type == "" or request.method == hdrs.METH_GET:
                response.headers[hdrs.CONTENT_TYPE] = "application/json"
            else:
                response.headers[hdrs.CONTENT_TYPE] = req_content_type

        err: TrpcException = message.server_rsp_err
        if err is not None and err.code != TrpcErrorCode.TRPC_INVOKE_SUCCESS:
            response.headers[HTTP_TRPC_HEADER.trpc_error_message] = err.msg
            trpc_error_code = get_trpc_error_code(err.type, HTTP_TRPC_HEADER.trpc_user_func_error_code)
            response.headers[trpc_error_code] = str(err.code)
            http_code = find_http_status(err.code, None)
            response_status = getattr(response, "status_code", http.HTTPStatus.OK.value)
            if http_code is None:
                if response_status in http.HTTPStatus.__members__.values():
                    http_code = http.HTTPStatus(response_status)
                elif err.code in http.HTTPStatus.__members__.values():
                    http_code = http.HTTPStatus(err.code)
                else:
                    http_code = http.HTTPStatus.OK
            response.status_code = http_code.value

        self.encode_trpc_rsp_header(context, message, response.headers)

        return body


class TrpcMcpClientHttpCodec(ClientHttpCodec):
    """HTTP client codec that accepts MCP streaming response status codes."""

    def decode_data(self, context: TrpcContext, _: bytes) -> bytes:
        """Map tRPC error headers and non-200/202 statuses onto ``client_rsp_err``.

        Args:
            context: Client call context.
            _: Unused; the body lives on ``client_rsp_head``.

        Returns:
            Response body bytes, or ``b''`` for a streamed response.

        Raises:
            ClientInvokeError: ``client_rsp_head`` is missing.
        """
        message: TrpcMessage = get_message(context)
        rsp_header = message.client_rsp_head
        if not rsp_header:
            raise ClientInvokeError("no rsp header")

        headers: dict = rsp_header.headers
        encode = headers.get(hdrs.CONTENT_ENCODING)
        if encode:
            message.set_compress_type(find_compress_type(encode, 0))

        ret = int(headers.get(HTTP_TRPC_HEADER.trpc_framework_error_code, "0"))
        if ret != 0:
            message.set_client_rsp_err(
                TrpcException(
                    TrpcErrorType.CALLEE_FRAMEWORK,
                    ret,
                    headers.get(HTTP_TRPC_HEADER.trpc_error_message, "callee framework error"),
                ))

        func_ret = int(headers.get(HTTP_TRPC_HEADER.trpc_user_func_error_code, "0"))
        if func_ret != 0:
            message.set_client_rsp_err(
                TrpcException(
                    TrpcErrorType.BUSINESS,
                    func_ret,
                    headers.get(HTTP_TRPC_HEADER.trpc_error_message, "business error"),
                ))

        if rsp_header.status_code not in {http.HTTPStatus.OK, http.HTTPStatus.ACCEPTED}:
            message.set_client_rsp_err(ClientInvokeError(f"http client codec StatusCode: {rsp_header.status_code}"))

        if rsp_header.stream:
            return b""
        return rsp_header.body


# Registered ONLY under the dedicated ``http_mcp`` protocol, NOT under ``http``:
# plain ``protocol: http`` clients in the same process keep the framework
# default codec, while MCP clients (which speak ``http_mcp``) use these.
register_plugin(PluginType.SERVER_CODEC, TRPC_MCP_PROTOCOL, init_pos=PluginInitPos.WORKER)(TrpcMcpServerHttpCodec)
register_plugin(PluginType.SERVER_PARSER, TRPC_MCP_PROTOCOL, init_pos=PluginInitPos.WORKER)(ServerHttpParser)
register_plugin(PluginType.CLIENT_CODEC, TRPC_MCP_PROTOCOL, init_pos=PluginInitPos.WORKER)(TrpcMcpClientHttpCodec)
register_plugin(PluginType.CLIENT_PARSER, TRPC_MCP_PROTOCOL, init_pos=PluginInitPos.WORKER)(ClientHttpParser)
# ``Options().set_protocol`` only swaps the transport when one is registered
# under that name; without it ``protocol: http_mcp`` clients would have none.
register_plugin(PluginType.CLIENT_TRANSPORT, TRPC_MCP_PROTOCOL, init_pos=PluginInitPos.WORKER)(HttpClientTransport)


@register_plugin(PluginType.USER_DEFINED,
                 TRPC_MCP_PROTOCOL,
                 init_pos=PluginInitPos.WORKER,
                 version=trpc_mcp_version,
                 report=True)
class TrpcMcpPlugin(BasePlugin):
    """Marks trpc-mcp for plugin version reporting; does nothing else."""
