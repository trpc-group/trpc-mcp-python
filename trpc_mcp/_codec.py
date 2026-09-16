# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com

import http

from aiohttp import hdrs
from trpc.plugin import PluginInitPos
from trpc.plugin import PluginType
from trpc.plugin import register_plugin
from trpc.plugin import DefaultPluginManager
from trpc.codec.message import Message
from trpc.exceptions import ClientInvokeError
from trpc.exceptions import ErrorCode
from trpc.exceptions import ErrorType
from trpc.exceptions import TRPCBaseError
from trpc.http import defines as http_defines

from trpc.http.codec import ServerHttpChecker
from trpc.http.codec import ServerHttpCodec
from trpc.http.codec import ClientHttpChecker
from trpc.http.codec import ClientHttpCodec

from ._constants import TRPC_MCP_PROTOCOL
from .version import __version__ as trpc_mcp_version


class TrpcMcpServerHttpCodec(ServerHttpCodec):
    """HTTP codec that works with the Starlette response used by MCP transport."""

    @classmethod
    def encode(cls, message: Message, body: bytes) -> bytes:
        request = message.context.get_meta_data(http_defines.HTTP_REQ_KEY)
        response = message.context.get_meta_data(http_defines.HTTP_RSP_KEY)

        content_type = response.headers.get(hdrs.CONTENT_TYPE, "")
        if content_type == "":
            req_content_type = request.headers.get(hdrs.CONTENT_TYPE, "")
            if req_content_type == "" or request.method == hdrs.METH_GET:
                response.headers[hdrs.CONTENT_TYPE] = "application/json"
            else:
                response.headers[hdrs.CONTENT_TYPE] = req_content_type

        err: TRPCBaseError = message.server_rsp_err
        if err.code != ErrorCode.TRPC_INVOKE_SUCCESS:
            response.headers[http_defines.HTTP_TRPC_HEADER.trpc_error_message] = err.msg
            trpc_error_code = http_defines.get_trpc_error_code(err.type,
                                                               http_defines.HTTP_TRPC_HEADER.trpc_user_func_error_code)
            response.headers[trpc_error_code] = str(err.code)
            http_code = http_defines.find_http_status(err.code, None)
            response_status = getattr(response, "status", getattr(response, "status_code", http.HTTPStatus.OK.value))
            if http_code is None:
                if response_status in http.HTTPStatus.__members__.values():
                    http_code = http.HTTPStatus(response_status)
                elif err.code in http.HTTPStatus.__members__.values():
                    http_code = http.HTTPStatus(err.code)
                else:
                    http_code = http.HTTPStatus.OK
            cls._set_response_status(response, http_code)

        cls.encode_trpc_rsp_header(message, response.headers)

        return body

    @staticmethod
    def _set_response_status(response, http_code: http.HTTPStatus) -> None:
        if hasattr(response, "set_status"):
            response.set_status(http_code.value, http_code.phrase)
            return
        response.status_code = http_code.value


# Register the MCP-aware client codec ONLY under the dedicated ``http_mcp``
# protocol, NOT under the global ``http`` name. Overriding ``http`` would force
# every plain HTTP business client in the same process to use the MCP codec; by
# isolating it here, plain ``protocol: http`` clients keep the framework default
# codec and MCP clients (which speak ``http_mcp``) coexist cleanly.
@register_plugin(PluginType.CLIENT_CODEC, TRPC_MCP_PROTOCOL, init_pos=PluginInitPos.MASTER)
class TrpcMcpClientHttpCodec(ClientHttpCodec):
    """HTTP client codec that accepts MCP streaming response status codes."""

    @classmethod
    def decode(cls, message: Message, _: bytes) -> bytes:
        rsp_header = message.client_rsp_head
        if not rsp_header:
            raise ClientInvokeError("no rsp header")

        headers: dict = rsp_header.headers
        encode = headers.get(hdrs.CONTENT_ENCODING)
        if encode:
            message.set_compress_type(http_defines.find_compress_type(encode, 0))

        ret = int(headers.get(http_defines.HTTP_TRPC_HEADER.trpc_framework_error_code, "0"))
        if ret != 0:
            message.set_client_rsp_err(
                TRPCBaseError(
                    ErrorType.CalleeFramework,
                    ret,
                    headers.get(http_defines.HTTP_TRPC_HEADER.trpc_error_message, "callee framework error"),
                ))

        func_ret = int(headers.get(http_defines.HTTP_TRPC_HEADER.trpc_user_func_error_code, "0"))
        if func_ret != 0:
            message.set_client_rsp_err(
                TRPCBaseError(
                    ErrorType.Business,
                    func_ret,
                    headers.get(http_defines.HTTP_TRPC_HEADER.trpc_error_message, "business error"),
                ))

        if rsp_header.status_code not in {http.HTTPStatus.OK, http.HTTPStatus.ACCEPTED}:
            message.set_client_rsp_err(ClientInvokeError(f"http client codec StatusCode: {rsp_header.status_code}"))

        if rsp_header.stream:
            return b""
        return rsp_header.body


@register_plugin(PluginType.USER_DEFINED,
                 TRPC_MCP_PROTOCOL,
                 init_pos=PluginInitPos.MASTER,
                 version=trpc_mcp_version,
                 stat_flag=True)
def report_trpc_mcp_codec_plugin():
    """
    Report info of trpc mcp codec plugin

    This function registers the TRPC MCP codec plugin with the TRPC framework.
    It provides metadata about the plugin including version and initialization
    position for proper plugin lifecycle management.
    """
    # Reuse the framework's HTTP client transport so the MCP protocol name can be
    # used on the client side too (``with_protocol`` only overrides the transport
    # when one is registered under that protocol name; without this, configuring
    # ``protocol: http_mcp`` on a client.service would have no transport).
    http_client_transport = DefaultPluginManager.get_instance(PluginType.CLIENT_TRANSPORT, http_defines.HTTP)
    DefaultPluginManager.set_instance(PluginType.SERVER_CHECKER, TRPC_MCP_PROTOCOL, ServerHttpChecker())
    DefaultPluginManager.set_instance(PluginType.SERVER_CODEC, TRPC_MCP_PROTOCOL, TrpcMcpServerHttpCodec())
    DefaultPluginManager.set_instance(PluginType.CLIENT_CHECKER, TRPC_MCP_PROTOCOL, ClientHttpChecker())
    # Use the MCP-aware client codec (handles ACCEPTED/streaming responses),
    # mirroring the codec registered under the plain ``http`` protocol.
    DefaultPluginManager.set_instance(PluginType.CLIENT_CODEC, TRPC_MCP_PROTOCOL, TrpcMcpClientHttpCodec())
    if http_client_transport is not None:
        DefaultPluginManager.set_instance(PluginType.CLIENT_TRANSPORT, TRPC_MCP_PROTOCOL, http_client_transport)
