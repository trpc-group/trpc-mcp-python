# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Tests for trpc_mcp._trpc_mcp_server."""

import types

import mcp.types as mcp_types
import pytest
from mcp.server.lowlevel.server import request_ctx
from trpc_sdk.abc import TrpcContext
from trpc_sdk.abc import get_message
from trpc_sdk.exceptions import TrpcErrorCode
from trpc_sdk.exceptions import TrpcErrorType
from trpc_sdk.exceptions import TrpcException
from trpc_sdk.http import HTTP_REQ_KEY
from trpc_sdk.http import HTTP_RSP_KEY
from trpc_sdk.http import HTTP_TRPC_HEADER
from trpc_sdk.http import LOCAL_ADDR
from trpc_sdk.http import TRANS_INFO_BASE64_KEY

from trpc_mcp import _trpc_mcp_server as srv
from trpc_mcp._codec import TrpcMcpServerHttpCodec
from trpc_mcp._trpc_mcp_server import (
    SERVER_NAME,
    TrpcMcpServer,
    _TRPC_CONTEXT,
    _forward_supported_kwargs,
    _remove_first_parameter_signature,
    _wrap_trpc_handler,
    get_trpc_context,
)

from conftest import run


class TestForwardSupportedKwargs:

    def test_keeps_supported_only(self):

        def fn(a, b):
            return a + b

        result = _forward_supported_kwargs(fn, a=1, b=2, c=3)
        assert result == {"a": 1, "b": 2}

    def test_var_keyword_keeps_all(self):

        def fn(**kwargs):
            return kwargs

        result = _forward_supported_kwargs(fn, a=1, z=9)
        assert result == {"a": 1, "z": 9}

    def test_unsupported_none_dropped_silently(self):

        def fn(a):
            return a

        result = _forward_supported_kwargs(fn, a=1, b=None)
        assert result == {"a": 1}

    def test_unsupported_nonnull_warns_and_dropped(self):

        def fn(a):
            return a

        result = _forward_supported_kwargs(fn, a=1, b="x")
        assert result == {"a": 1}


class TestSignatureHelpers:

    def test_remove_first_parameter(self):

        def fn(ctx, a, b):
            return None

        sig = _remove_first_parameter_signature(fn)
        assert list(sig.parameters) == ["a", "b"]

    def test_remove_first_parameter_empty(self):

        def fn():
            return None

        sig = _remove_first_parameter_signature(fn)
        assert list(sig.parameters) == []


class TestGetTrpcContext:

    def setup_method(self):
        # Ensure no leaked contextvar between tests.
        _TRPC_CONTEXT.set(None)

    def test_returns_contextvar_value(self):
        ctx = TrpcContext()
        token = _TRPC_CONTEXT.set(ctx)
        try:
            assert get_trpc_context() is ctx
        finally:
            _TRPC_CONTEXT.reset(token)

    def test_no_context_no_request_returns_none(self):
        # request_ctx has no value -> LookupError -> None
        assert get_trpc_context() is None

    def test_request_is_trpc_context(self):
        ctx = TrpcContext()
        token = request_ctx.set(types.SimpleNamespace(request=ctx))
        try:
            assert get_trpc_context() is ctx
        finally:
            request_ctx.reset(token)

    def test_request_scope_has_trpc_context(self):
        ctx = TrpcContext()
        request = types.SimpleNamespace(scope={"trpc_context": ctx})
        token = request_ctx.set(types.SimpleNamespace(request=request))
        try:
            assert get_trpc_context() is ctx
        finally:
            request_ctx.reset(token)

    def test_request_without_scope_returns_none(self):
        request = types.SimpleNamespace(scope=None)
        token = request_ctx.set(types.SimpleNamespace(request=request))
        try:
            assert get_trpc_context() is None
        finally:
            request_ctx.reset(token)


class TestWrapTrpcHandler:

    def setup_method(self):
        _TRPC_CONTEXT.set(None)

    def test_sync_with_ctx_injected(self):
        ctx = TrpcContext()
        token = _TRPC_CONTEXT.set(ctx)

        def handler(trpc_ctx, value):
            return (trpc_ctx, value)

        wrapped = _wrap_trpc_handler(handler)
        try:
            got_ctx, val = wrapped(42)
            assert got_ctx is ctx
            assert val == 42
            assert list(__import__("inspect").signature(wrapped).parameters) == ["value"]
        finally:
            _TRPC_CONTEXT.reset(token)

    def test_sync_without_params(self):

        def handler():
            return "done"

        wrapped = _wrap_trpc_handler(handler)
        assert wrapped() == "done"

    def test_async_with_ctx(self):
        ctx = TrpcContext()
        token = _TRPC_CONTEXT.set(ctx)

        async def handler(trpc_ctx, value):
            return (trpc_ctx, value)

        wrapped = _wrap_trpc_handler(handler)
        try:
            got_ctx, val = run(wrapped(7))
            assert got_ctx is ctx and val == 7
        finally:
            _TRPC_CONTEXT.reset(token)

    def test_async_without_params(self):

        async def handler():
            return "ok"

        wrapped = _wrap_trpc_handler(handler)
        assert run(wrapped()) == "ok"


class TestServerBindingsAndVisibility:

    def test_setters(self):
        server = TrpcMcpServer(name="t")
        opts = types.SimpleNamespace(port=8080)
        server.set_trpc_options(opts)
        assert server._trpc_opts_map == {8080: opts}

        opts2 = types.SimpleNamespace(port=9090)
        server.set_trpc_options_map([opts, opts2])
        assert set(server._trpc_opts_map) == {8080, 9090}

        server.set_service_bindings({"t": {"s"}}, {"r": {"s"}}, {"p": {"s"}})
        assert server._tool_services == {"t": {"s"}}

        server.set_sse_redis_config({"host": "h"})
        assert server._sse_redis_conf == {"host": "h"}
        server.set_sse_redis_config({})
        assert server._sse_redis_conf is None

    def test_is_uri_template_match(self):
        server = TrpcMcpServer(name="t")
        assert server._is_uri_template_match("ctx://{name}", "ctx://foo") is True
        assert server._is_uri_template_match("ctx://{name}", "ctx://a/b") is False
        assert server._is_uri_template_match("ctx://static", "ctx://static") is True

    def test_is_allowed_no_service(self, monkeypatch):
        server = TrpcMcpServer(name="t")
        monkeypatch.setattr(server, "_get_current_service_name", lambda: None)
        assert server._is_allowed("anything", {}) is True

    def test_is_allowed_with_bindings(self, monkeypatch):
        server = TrpcMcpServer(name="t")
        monkeypatch.setattr(server, "_get_current_service_name", lambda: "svc1")
        assert server._is_allowed("tool-a", {"tool-a": {"svc1"}}) is True
        assert server._is_allowed("tool-a", {"tool-a": {"svc2"}}) is False
        # name not in bindings -> allowed only if bindings empty
        assert server._is_allowed("missing", {}) is True
        assert server._is_allowed("missing", {"other": {"svc1"}}) is False

    def test_is_resource_allowed(self, monkeypatch):
        server = TrpcMcpServer(name="t")
        monkeypatch.setattr(server, "_get_current_service_name", lambda: None)
        assert server._is_resource_allowed("res://x") is True

        monkeypatch.setattr(server, "_get_current_service_name", lambda: "svc1")
        server._resource_services = {"res://{id}": {"svc1"}}
        assert server._is_resource_allowed("res://42") is True
        assert server._is_resource_allowed("other://y") is False

    def test_get_current_service_name(self, monkeypatch):
        server = TrpcMcpServer(name="t")
        monkeypatch.setattr(srv, "get_trpc_context", lambda: None)
        assert server._get_current_service_name() is None

        ctx = TrpcContext()
        ctx.with_meta_data(SERVER_NAME, "my-svc")
        monkeypatch.setattr(srv, "get_trpc_context", lambda: ctx)
        assert server._get_current_service_name() == "my-svc"


class TestDecoratorMisuse:

    def test_tool_decorator_called_with_callable_raises(self):
        server = TrpcMcpServer(name="t")
        with pytest.raises(TypeError):
            server.tool(lambda ctx: None)

    def test_resource_decorator_called_with_callable_raises(self):
        server = TrpcMcpServer(name="t")
        with pytest.raises(TypeError):
            server.resource(lambda ctx: None)

    def test_prompt_decorator_called_with_callable_raises(self):
        server = TrpcMcpServer(name="t")
        with pytest.raises(TypeError):
            server.prompt(lambda ctx: None)


class TestRegistrationAndVisibility:

    def _server_with_items(self):
        server = TrpcMcpServer(name="svc-a,svc-b")

        @server.tool()
        def echo(ctx: TrpcContext, text: str) -> str:
            return text

        @server.resource("res://static")
        def static_res(ctx: TrpcContext) -> str:
            return "data"

        @server.resource("res://{name}/info")
        def templated(ctx: TrpcContext, name: str) -> str:
            return name

        @server.prompt()
        def greet(ctx: TrpcContext, who: str) -> str:
            return who

        return server

    def test_list_tools_visible(self):
        server = self._server_with_items()
        tools = run(server.list_tools())
        assert any(t.name == "echo" for t in tools)

    def test_call_tool(self):
        server = self._server_with_items()
        result = run(server.call_tool("echo", {"text": "hi"}))
        assert result[1] == {"result": "hi"}

    def test_call_tool_not_allowed_raises(self):
        server = self._server_with_items()
        server.set_service_bindings({"echo": {"other-svc"}}, {}, {})
        ctx = TrpcContext()
        ctx.with_meta_data(SERVER_NAME, "svc-a")
        token = _TRPC_CONTEXT.set(ctx)
        try:
            with pytest.raises(ValueError, match="Unknown tool"):
                run(server.call_tool("echo", {"text": "hi"}))
        finally:
            _TRPC_CONTEXT.reset(token)

    def test_list_resources_and_templates(self):
        server = self._server_with_items()
        resources = run(server.list_resources())
        assert any(str(r.uri) == "res://static" for r in resources)
        templates = run(server.list_resource_templates())
        assert any("{name}" in t.uriTemplate for t in templates)

    def test_read_resource_ok(self):
        server = self._server_with_items()
        result = run(server.read_resource("res://static"))
        assert list(result)[0].content == "data"

    def test_read_resource_not_allowed(self, monkeypatch):
        server = self._server_with_items()
        monkeypatch.setattr(server, "_is_resource_allowed", lambda uri: False)
        with pytest.raises(ValueError, match="Unknown resource"):
            run(server.read_resource("res://static"))

    def test_list_prompts(self):
        server = self._server_with_items()
        prompts = run(server.list_prompts())
        assert any(p.name == "greet" for p in prompts)

    def test_get_prompt(self):
        server = self._server_with_items()
        result = run(server.get_prompt("greet", {"who": "world"}))
        assert result is not None

    def test_get_prompt_not_allowed(self):
        server = self._server_with_items()
        server.set_service_bindings({}, {}, {"greet": {"other"}})
        ctx = TrpcContext()
        ctx.with_meta_data(SERVER_NAME, "svc-a")
        token = _TRPC_CONTEXT.set(ctx)
        try:
            with pytest.raises(ValueError, match="Unknown prompt"):
                run(server.get_prompt("greet", {"who": "x"}))
        finally:
            _TRPC_CONTEXT.reset(token)


class TestWrapFilterApp:

    def test_without_opts_returns_app(self):
        server = TrpcMcpServer(name="t")
        sentinel = object()
        assert server._wrap_filter_app(sentinel) is sentinel

    def test_with_opts_wraps(self):
        server = TrpcMcpServer(name="t")
        server.set_trpc_options(types.SimpleNamespace(port=1))
        wrapped = server._wrap_filter_app(lambda *a: None)
        assert isinstance(wrapped, srv._TrpcFilterASGIApp)


class TestGetServerSession:

    def test_get_server_session_uses_context(self, monkeypatch):
        server = TrpcMcpServer(name="t")
        fake_ctx = types.SimpleNamespace(session="the-session")
        monkeypatch.setattr(server, "get_context", lambda: fake_ctx)
        assert server.get_server_session() == "the-session"


class TestCallToolUnknown:

    def test_call_unknown_tool_delegates_to_super(self):
        server = TrpcMcpServer(name="t")
        # No tool registered: _is_allowed True, get_tool None -> super().call_tool
        with pytest.raises(Exception):
            run(server.call_tool("nope", {}))


def _make_opts(port=8080, address="127.0.0.1"):
    service_opt = types.SimpleNamespace(protocol="http_mcp")

    async def handle_http(ctx, cb):
        await cb(ctx, get_message(ctx).server_raw_req)
        return None

    service = types.SimpleNamespace(opt=service_opt, handle_http=handle_http)
    return types.SimpleNamespace(
        idle_timeout=10,
        address=(address, port),
        port=port,
        service_name="svc-a",
        service=service,
    )


def _http_scope(port=8080, method="GET", headers=None):
    return {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/svc-a/handle",
        "raw_path": b"/svc-a/handle",
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
        "server": ("127.0.0.1", port),
        "client": ("9.9.9.9", 5555),
    }


class TestFilterASGIApp:

    def test_make_trpc_context_and_decode(self):
        from starlette.requests import Request

        opts = _make_opts()
        app = srv._TrpcFilterASGIApp(lambda *a: None, {opts.port: opts}, TrpcMcpServer(name="t"))
        headers = [
            (b"trpc-caller", b"caller.svc"),
            (b"trpc-caller-func", b"/caller/method"),
            (b"content-type", b"application/json"),
        ]
        request = Request(_http_scope(method="POST", headers=headers))
        ctx = app._make_trpc_context(request)
        message = get_message(ctx)
        assert ctx.get_meta_data(SERVER_NAME) == "svc-a"
        assert ctx.get_meta_data(LOCAL_ADDR) == "127.0.0.1:8080"
        assert ctx.get_meta_data(HTTP_REQ_KEY) is request
        assert message.server_raw_req is request
        assert message.server_raw_rsp is ctx.get_meta_data(HTTP_RSP_KEY)
        assert message.caller_service_name == "caller.svc"
        assert message.server_rpc_name == "/svc-a/handle"
        assert ctx.recv_time > 0
        assert ctx.remote_ip == "9.9.9.9"
        assert request.scope["trpc_context"] is ctx

    def test_decode_base64_trans_info(self):
        import base64
        import json

        from starlette.requests import Request

        trans_info = json.dumps({"k": base64.b64encode(b"v").decode()}).encode()
        request = Request(_http_scope(headers=[(b"trpc-trans-info", trans_info)]))
        ctx = TrpcContext()
        ctx.with_meta_data(TRANS_INFO_BASE64_KEY, True)
        message = get_message(ctx)
        srv._TrpcFilterASGIApp._decode_trpc_req_header(ctx, message, request)
        assert message.server_meta_data["k"] == "v"

    def test_get_opts_default_when_unknown_port(self):
        opts = _make_opts(port=1111)
        app = srv._TrpcFilterASGIApp(lambda *a: None, {1111: opts}, TrpcMcpServer(name="t"))
        from starlette.requests import Request

        # server port 2222 not in map -> default opts
        request = Request(_http_scope(port=2222))
        assert app._get_opts(request) is opts

    def test_merge_trpc_headers_empty(self):
        message = {"headers": [(b"a", b"b")]}
        result = srv._TrpcFilterASGIApp._merge_trpc_headers(TrpcContext(), dict(message))
        assert result == message

    def test_merge_trpc_headers_adds(self):
        from trpc_sdk.http import set_http_rsp_header

        ctx = TrpcContext()
        set_http_rsp_header(ctx, {"X-New": "1", "a": "dup"})
        message = {"headers": [(b"a", b"b")]}
        result = srv._TrpcFilterASGIApp._merge_trpc_headers(ctx, message)
        keys = {k for k, _ in result["headers"]}
        assert b"x-new" in keys
        # existing "a" not overwritten (stays single)
        assert sum(1 for k, _ in result["headers"] if k == b"a") == 1

    def test_call_non_http_passthrough(self):
        called = {}

        async def app(scope, receive, send):
            called["ran"] = True

        wrapper = srv._TrpcFilterASGIApp(app, {8080: _make_opts()}, TrpcMcpServer(name="t"))

        async def receive():
            return {"type": "lifespan.startup"}

        async def send(msg):
            pass

        run(wrapper({"type": "lifespan"}, receive, send))
        assert called["ran"] is True

    def test_call_http_flow(self):
        sent = []

        async def downstream(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        opts = _make_opts()
        wrapper = srv._TrpcFilterASGIApp(downstream, {opts.port: opts}, TrpcMcpServer(name="t"))

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg):
            sent.append(msg)

        run(wrapper(_http_scope(), receive, send))
        assert any(m["type"] == "http.response.start" for m in sent)

    def test_call_http_result_response(self):
        sent = []

        async def downstream(scope, receive, send):
            # never sends response; http_handle returns a body instead
            return None

        opts = _make_opts()

        async def handle_http(ctx, cb):
            return b"result-body"

        opts.service.handle_http = handle_http
        wrapper = srv._TrpcFilterASGIApp(downstream, {opts.port: opts}, TrpcMcpServer(name="t"))

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg):
            sent.append(msg)

        run(wrapper(_http_scope(), receive, send))
        assert any(m["type"] == "http.response.start" for m in sent)

    def test_call_http_filter_error_keeps_codec_status_and_headers(self):
        sent = []
        opts = _make_opts()

        async def handle_http(ctx, cb):
            # What ServiceAdapter.handle_http does when a filter fails: the
            # codec writes the error onto server_raw_rsp and returns b"".
            message = get_message(ctx)
            message.set_server_rsp_err(
                TrpcException(TrpcErrorType.FRAMEWORK, TrpcErrorCode.TRPC_SERVER_OVERLOAD_ERR, "denied"))
            return TrpcMcpServerHttpCodec().encode_data(ctx, b"")

        opts.service.handle_http = handle_http
        wrapper = srv._TrpcFilterASGIApp(lambda *a: None, {opts.port: opts}, TrpcMcpServer(name="t"))

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg):
            sent.append(msg)

        run(wrapper(_http_scope(), receive, send))
        start = next(m for m in sent if m["type"] == "http.response.start")
        headers = dict(start["headers"])
        assert start["status"] == 429
        assert headers[HTTP_TRPC_HEADER.trpc_error_message.encode()] == b"denied"
        assert headers[b"content-length"] == b"0"


class TestCallToolHandler:

    def _server(self):
        server = TrpcMcpServer(name="svc")

        @server.tool()
        def echo(ctx: TrpcContext, text: str) -> str:
            return text

        @server.tool()
        def make_dict(ctx: TrpcContext) -> dict:
            return {"k": "v"}

        return server

    def _handler(self, server):
        return server._mcp_server.request_handlers[mcp_types.CallToolRequest]

    def _request(self, name, arguments):
        return mcp_types.CallToolRequest(
            method="tools/call",
            params=mcp_types.CallToolRequestParams(name=name, arguments=arguments),
        )

    def test_handler_text_result(self):
        server = self._server()
        handler = self._handler(server)
        result = run(handler(self._request("echo", {"text": "hi"})))
        assert isinstance(result, mcp_types.ServerResult)

    def test_handler_dict_result(self):
        server = self._server()
        handler = self._handler(server)
        result = run(handler(self._request("make_dict", {})))
        assert isinstance(result, mcp_types.ServerResult)

    def test_handler_error_on_unknown_tool(self):
        server = self._server()
        handler = self._handler(server)
        result = run(handler(self._request("missing", {})))
        # error result is still a ServerResult with isError True
        assert isinstance(result, mcp_types.ServerResult)


class TestSseAndStreamableApps:

    def test_sse_app_without_redis(self):
        server = TrpcMcpServer(name="t")
        server.set_trpc_options(_make_opts())
        app = server.sse_app()
        assert app is not None

    def test_sse_app_with_redis(self):
        server = TrpcMcpServer(name="t")
        server.set_trpc_options(_make_opts())
        server.set_sse_redis_config({"host": "127.0.0.1", "port": 6379})
        app = server.sse_app()
        assert app is not None

    def test_streamable_http_app(self):
        server = TrpcMcpServer(name="t")
        server.set_trpc_options(_make_opts())
        app = server.streamable_http_app()
        assert app is not None
