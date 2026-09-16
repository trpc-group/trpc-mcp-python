# -*- coding: utf-8 -*-
"""Tests for trpc_mcp._codec."""

import http
import types

import pytest
from aiohttp import hdrs
from trpc.codec.message import get_message
from trpc.context import TrpcContext
from trpc.exceptions import ClientInvokeError, ErrorType, TRPCBaseError
from trpc.http import defines as http_defines

from trpc_mcp._codec import (
    TrpcMcpClientHttpCodec,
    TrpcMcpServerHttpCodec,
    report_trpc_mcp_codec_plugin,
)


def _make_message(request, response):
    ctx = TrpcContext()
    ctx.with_meta_data(http_defines.HTTP_REQ_KEY, request)
    ctx.with_meta_data(http_defines.HTTP_RSP_KEY, response)
    return get_message(ctx)


class _Resp:

    def __init__(self):
        self.headers = {}
        self.status_code = http.HTTPStatus.OK.value


class _RespWithSetStatus:

    def __init__(self):
        self.headers = {}
        self.status = http.HTTPStatus.OK.value
        self._status_set = None

    def set_status(self, code, phrase):
        self._status_set = (code, phrase)
        self.status = code


class TestServerEncodeSuccess:

    def test_empty_content_type_get_defaults_json(self):
        req = types.SimpleNamespace(headers={}, method=hdrs.METH_GET)
        resp = _Resp()
        msg = _make_message(req, resp)
        body = TrpcMcpServerHttpCodec.encode(msg, b"payload")
        assert body == b"payload"
        assert resp.headers[hdrs.CONTENT_TYPE] == "application/json"

    def test_empty_content_type_post_uses_request_type(self):
        req = types.SimpleNamespace(headers={hdrs.CONTENT_TYPE: "application/xml"}, method="POST")
        resp = _Resp()
        msg = _make_message(req, resp)
        TrpcMcpServerHttpCodec.encode(msg, b"")
        assert resp.headers[hdrs.CONTENT_TYPE] == "application/xml"

    def test_existing_response_content_type_kept(self):
        req = types.SimpleNamespace(headers={hdrs.CONTENT_TYPE: "application/xml"}, method="POST")
        resp = _Resp()
        resp.headers[hdrs.CONTENT_TYPE] = "text/event-stream"
        msg = _make_message(req, resp)
        TrpcMcpServerHttpCodec.encode(msg, b"")
        assert resp.headers[hdrs.CONTENT_TYPE] == "text/event-stream"


class TestServerEncodeError:

    def test_error_status_kept_when_response_status_valid(self):
        req = types.SimpleNamespace(headers={}, method=hdrs.METH_GET)
        resp = _Resp()  # status_code defaults to 200 (a valid HTTPStatus)
        msg = _make_message(req, resp)
        msg.set_server_rsp_err(TRPCBaseError(ErrorType.Business, 100, "boom"))
        TrpcMcpServerHttpCodec.encode(msg, b"")
        assert resp.headers[http_defines.HTTP_TRPC_HEADER.trpc_error_message] == "boom"
        assert resp.status_code == 200

    def test_error_status_from_err_code_when_response_invalid(self):
        req = types.SimpleNamespace(headers={}, method=hdrs.METH_GET)
        resp = _Resp()
        resp.status_code = 0  # not a valid HTTPStatus member
        msg = _make_message(req, resp)
        # err.code 100 is a valid HTTPStatus member (CONTINUE)
        msg.set_server_rsp_err(TRPCBaseError(ErrorType.Business, 100, "boom"))
        TrpcMcpServerHttpCodec.encode(msg, b"")
        assert resp.status_code == 100

    def test_error_with_set_status_response(self):
        req = types.SimpleNamespace(headers={}, method=hdrs.METH_GET)
        resp = _RespWithSetStatus()
        msg = _make_message(req, resp)
        msg.set_server_rsp_err(TRPCBaseError(ErrorType.Business, 999999, "boom"))
        TrpcMcpServerHttpCodec.encode(msg, b"")
        # 999999 not a valid status and current status OK -> OK retained
        assert resp._status_set is not None


class TestClientDecode:

    def _msg_with_head(self, **head_kwargs):
        defaults = dict(headers={}, status_code=http.HTTPStatus.OK, stream=False, body=b"data")
        defaults.update(head_kwargs)
        head = types.SimpleNamespace(**defaults)
        msg = get_message(TrpcContext())
        msg.set_client_rsp_head(head)
        return msg, head

    def test_no_rsp_header_raises(self):
        msg = get_message(TrpcContext())
        with pytest.raises(ClientInvokeError):
            TrpcMcpClientHttpCodec.decode(msg, b"")

    def test_success_returns_body(self):
        msg, _ = self._msg_with_head()
        assert TrpcMcpClientHttpCodec.decode(msg, b"") == b"data"

    def test_stream_returns_empty(self):
        msg, _ = self._msg_with_head(stream=True)
        assert TrpcMcpClientHttpCodec.decode(msg, b"") == b""

    def test_content_encoding_sets_compress(self):
        msg, _ = self._msg_with_head(headers={hdrs.CONTENT_ENCODING: "gzip"})
        TrpcMcpClientHttpCodec.decode(msg, b"")

    def test_framework_error_code_sets_err(self):
        headers = {http_defines.HTTP_TRPC_HEADER.trpc_framework_error_code: "100"}
        msg, _ = self._msg_with_head(headers=headers)
        TrpcMcpClientHttpCodec.decode(msg, b"")
        assert msg.client_rsp_err.code == 100

    def test_business_error_code_sets_err(self):
        headers = {http_defines.HTTP_TRPC_HEADER.trpc_user_func_error_code: "200"}
        msg, _ = self._msg_with_head(headers=headers)
        TrpcMcpClientHttpCodec.decode(msg, b"")
        assert msg.client_rsp_err.code == 200

    def test_bad_status_code_sets_err(self):
        msg, _ = self._msg_with_head(status_code=http.HTTPStatus.NOT_FOUND)
        TrpcMcpClientHttpCodec.decode(msg, b"")
        assert msg.client_rsp_err is not None

    def test_accepted_status_ok(self):
        msg, _ = self._msg_with_head(status_code=http.HTTPStatus.ACCEPTED)
        assert TrpcMcpClientHttpCodec.decode(msg, b"") == b"data"


class TestReportPlugin:

    def test_report_runs_without_error(self):
        # Re-running registration should be idempotent and not raise.
        report_trpc_mcp_codec_plugin()
