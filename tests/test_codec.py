# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Tests for trpc_mcp._codec."""

import http
import types

import pytest
from aiohttp import hdrs
from starlette.responses import Response
from trpc_sdk._inner import trpc_pb2
from trpc_sdk.abc import PluginType
from trpc_sdk.abc import TrpcContext
from trpc_sdk.abc import get_message
from trpc_sdk.codec import get_client_codec
from trpc_sdk.codec import get_client_parser
from trpc_sdk.codec import get_server_codec
from trpc_sdk.codec import get_server_parser
from trpc_sdk.exceptions import ClientInvokeError
from trpc_sdk.exceptions import TrpcErrorType
from trpc_sdk.exceptions import TrpcException
from trpc_sdk.http import HTTP_TRPC_HEADER
from trpc_sdk.http import HttpClientTransport
from trpc_sdk.plugin import get_plugin
from trpc_sdk.transport import get_client_transport

from trpc_mcp._codec import TrpcMcpClientHttpCodec
from trpc_mcp._codec import TrpcMcpPlugin
from trpc_mcp._codec import TrpcMcpServerHttpCodec
from trpc_mcp._constants import TRPC_MCP_PROTOCOL


def _server_ctx(request, response):
    ctx = TrpcContext()
    message = get_message(ctx)
    message.set_server_raw_req(request)
    message.set_server_raw_rsp(response)
    return ctx, message


class _Resp:

    def __init__(self):
        self.headers = {}
        self.status_code = http.HTTPStatus.OK.value


class TestRegistration:

    def test_server_plugins(self):
        assert isinstance(get_server_codec(TRPC_MCP_PROTOCOL), TrpcMcpServerHttpCodec)
        assert get_server_parser(TRPC_MCP_PROTOCOL) is not None

    def test_client_plugins(self):
        assert isinstance(get_client_codec(TRPC_MCP_PROTOCOL), TrpcMcpClientHttpCodec)
        assert get_client_parser(TRPC_MCP_PROTOCOL) is not None
        assert isinstance(get_client_transport(TRPC_MCP_PROTOCOL), HttpClientTransport)

    def test_plain_http_codec_untouched(self):
        assert not isinstance(get_client_codec("http"), TrpcMcpClientHttpCodec)
        assert not isinstance(get_server_codec("http"), TrpcMcpServerHttpCodec)

    def test_report_plugin(self):
        assert isinstance(get_plugin(PluginType.USER_DEFINED, TRPC_MCP_PROTOCOL), TrpcMcpPlugin)


class TestServerEncodeSuccess:

    def test_empty_content_type_get_defaults_json(self):
        req = types.SimpleNamespace(headers={}, method=hdrs.METH_GET)
        resp = _Resp()
        ctx, _ = _server_ctx(req, resp)
        body = TrpcMcpServerHttpCodec().encode_data(ctx, b"payload")
        assert body == b"payload"
        assert resp.headers[hdrs.CONTENT_TYPE] == "application/json"

    def test_empty_content_type_post_uses_request_type(self):
        req = types.SimpleNamespace(headers={hdrs.CONTENT_TYPE: "application/xml"}, method="POST")
        resp = _Resp()
        ctx, _ = _server_ctx(req, resp)
        TrpcMcpServerHttpCodec().encode_data(ctx, b"")
        assert resp.headers[hdrs.CONTENT_TYPE] == "application/xml"

    def test_existing_response_content_type_kept(self):
        req = types.SimpleNamespace(headers={hdrs.CONTENT_TYPE: "application/xml"}, method="POST")
        resp = _Resp()
        resp.headers[hdrs.CONTENT_TYPE] = "text/event-stream"
        ctx, _ = _server_ctx(req, resp)
        TrpcMcpServerHttpCodec().encode_data(ctx, b"")
        assert resp.headers[hdrs.CONTENT_TYPE] == "text/event-stream"

    def test_trpc_rsp_headers_written(self):
        req = types.SimpleNamespace(headers={}, method=hdrs.METH_GET)
        resp = _Resp()
        ctx, message = _server_ctx(req, resp)
        rsp_head = trpc_pb2.ResponseProtocol()
        rsp_head.request_id = 7
        message.set_server_rsp_head(rsp_head)
        TrpcMcpServerHttpCodec().encode_data(ctx, b"")
        assert resp.headers[HTTP_TRPC_HEADER.trpc_request_id] == "7"


class TestServerEncodeError:

    def test_error_headers_on_starlette_response(self):
        req = types.SimpleNamespace(headers={}, method=hdrs.METH_GET)
        resp = Response()
        ctx, message = _server_ctx(req, resp)
        message.set_server_rsp_err(TrpcException(TrpcErrorType.BUSINESS, 999999, "boom"))
        TrpcMcpServerHttpCodec().encode_data(ctx, b"")
        assert resp.headers[HTTP_TRPC_HEADER.trpc_error_message] == "boom"
        assert resp.headers[HTTP_TRPC_HEADER.trpc_user_func_error_code] == "999999"
        # 999999 is not an HTTP status and the response is 200, so 200 is kept.
        assert resp.status_code == 200

    def test_error_status_kept_when_response_status_valid(self):
        req = types.SimpleNamespace(headers={}, method=hdrs.METH_GET)
        resp = _Resp()
        ctx, message = _server_ctx(req, resp)
        message.set_server_rsp_err(TrpcException(TrpcErrorType.BUSINESS, 100, "boom"))
        TrpcMcpServerHttpCodec().encode_data(ctx, b"")
        assert resp.headers[HTTP_TRPC_HEADER.trpc_error_message] == "boom"
        assert resp.status_code == 200

    def test_error_status_from_err_code_when_response_invalid(self):
        req = types.SimpleNamespace(headers={}, method=hdrs.METH_GET)
        resp = _Resp()
        resp.status_code = 0  # not a valid HTTPStatus member
        ctx, message = _server_ctx(req, resp)
        # err.code 100 is a valid HTTPStatus member (CONTINUE)
        message.set_server_rsp_err(TrpcException(TrpcErrorType.BUSINESS, 100, "boom"))
        TrpcMcpServerHttpCodec().encode_data(ctx, b"")
        assert resp.status_code == 100


class TestClientDecode:

    def _ctx_with_head(self, **head_kwargs):
        defaults = dict(headers={}, status_code=http.HTTPStatus.OK, stream=False, body=b"data")
        defaults.update(head_kwargs)
        head = types.SimpleNamespace(**defaults)
        ctx = TrpcContext()
        message = get_message(ctx)
        message.set_client_rsp_head(head)
        return ctx, message

    def test_no_rsp_header_raises(self):
        with pytest.raises(ClientInvokeError):
            TrpcMcpClientHttpCodec().decode_data(TrpcContext(), b"")

    def test_success_returns_body(self):
        ctx, _ = self._ctx_with_head()
        assert TrpcMcpClientHttpCodec().decode_data(ctx, b"") == b"data"

    def test_stream_returns_empty(self):
        ctx, _ = self._ctx_with_head(stream=True)
        assert TrpcMcpClientHttpCodec().decode_data(ctx, b"") == b""

    def test_content_encoding_sets_compress(self):
        ctx, _ = self._ctx_with_head(headers={hdrs.CONTENT_ENCODING: "gzip"})
        TrpcMcpClientHttpCodec().decode_data(ctx, b"")

    def test_framework_error_code_sets_err(self):
        headers = {HTTP_TRPC_HEADER.trpc_framework_error_code: "100"}
        ctx, message = self._ctx_with_head(headers=headers)
        TrpcMcpClientHttpCodec().decode_data(ctx, b"")
        assert message.client_rsp_err.code == 100
        assert message.client_rsp_err.type == TrpcErrorType.CALLEE_FRAMEWORK

    def test_business_error_code_sets_err(self):
        headers = {HTTP_TRPC_HEADER.trpc_user_func_error_code: "200"}
        ctx, message = self._ctx_with_head(headers=headers)
        TrpcMcpClientHttpCodec().decode_data(ctx, b"")
        assert message.client_rsp_err.code == 200
        assert message.client_rsp_err.type == TrpcErrorType.BUSINESS

    def test_bad_status_code_sets_err(self):
        ctx, message = self._ctx_with_head(status_code=http.HTTPStatus.NOT_FOUND)
        TrpcMcpClientHttpCodec().decode_data(ctx, b"")
        assert isinstance(message.client_rsp_err, ClientInvokeError)

    def test_accepted_status_ok(self):
        ctx, message = self._ctx_with_head(status_code=http.HTTPStatus.ACCEPTED)
        assert TrpcMcpClientHttpCodec().decode_data(ctx, b"") == b"data"
        assert message.client_rsp_err is None or message.client_rsp_err.code == 0
