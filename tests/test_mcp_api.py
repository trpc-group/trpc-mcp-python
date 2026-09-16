# -*- coding: utf-8 -*-
"""Tests for trpc_mcp.mcp_api."""

import types

import pytest
from mcp.server.streamable_http import EventStore
from mcp.types import CallToolResult
from trpc.context import TrpcContext
from trpc.http import defines as http_defines

from trpc_mcp import mcp_api
from trpc_mcp._config import McpServerOptions, get_mcp_server_options, set_mcp_server_options


class _FakeServer:

    def __init__(self):
        self.name = "fake-mcp"
        self._session = object()

    def get_server_session(self):
        return self._session


@pytest.fixture
def patched_app(monkeypatch):
    server = _FakeServer()
    monkeypatch.setattr(mcp_api, "get_mcp_app", lambda: server)
    return server


class TestServerAccessors:

    def test_get_mcp_server(self, patched_app):
        assert mcp_api.get_mcp_server(TrpcContext()) is patched_app

    def test_get_trpc_mcp_server_name(self, patched_app):
        assert mcp_api.get_trpc_mcp_server_name(TrpcContext()) == "fake-mcp"

    def test_get_session_func(self, patched_app):
        assert mcp_api.get_session_func(TrpcContext()) is patched_app._session


class TestHttpAccessors:

    def test_get_http_req_and_rsp(self):
        ctx = TrpcContext()
        req = object()
        rsp = object()
        ctx.with_meta_data(http_defines.HTTP_REQ_KEY, req)
        ctx.with_meta_data(http_defines.HTTP_RSP_KEY, rsp)
        assert mcp_api.get_http_req(ctx) is req
        assert mcp_api.get_http_rsp(ctx) is rsp

    def test_get_server_addr_from_meta(self):
        ctx = TrpcContext()
        ctx.with_meta_data(http_defines.LOCAL_ADDR, "10.0.0.1:80")
        assert mcp_api.get_server_addr(ctx) == "10.0.0.1:80"

    def test_get_server_addr_fallback_to_request_host(self):
        ctx = TrpcContext()
        ctx.with_meta_data(http_defines.HTTP_REQ_KEY, types.SimpleNamespace(host="host:9000"))
        assert mcp_api.get_server_addr(ctx) == "host:9000"

    def test_get_remote_addr(self):
        ctx = TrpcContext()
        ctx.remote_ip = "8.8.8.8"
        assert mcp_api.get_remote_addr(ctx) == "8.8.8.8"


class TestMakeCallToolResult:

    def test_builds_result(self):
        result = mcp_api.make_call_tool_result("hello", {"k": "v"})
        assert isinstance(result, CallToolResult)
        assert result.content[0].text == "hello"
        assert result.meta == {"k": "v"}


class TestRegisterMcpServerCls:

    def test_decorator_registers_instance(self, monkeypatch):
        captured = {}

        def fake_register(name, app):
            captured["name"] = name
            captured["app"] = app

        monkeypatch.setattr(mcp_api, "register_mcp_app", fake_register)

        @mcp_api.register_mcp_server_cls("svc-name")
        class MyServer:
            pass

        assert MyServer is captured["app"].__class__
        assert captured["name"] == "svc-name"


class _FakeEventStore(EventStore):

    async def store_event(self, stream_id, message):
        return "event-id"

    async def replay_events_after(self, last_event_id, send_callback):
        return None


class TestRegisterEventStore:

    def test_registers_event_store(self):
        original = get_mcp_server_options()
        try:
            set_mcp_server_options(McpServerOptions())
            store = _FakeEventStore()
            mcp_api.register_streamable_http_event_store("svc", store)
            assert get_mcp_server_options().event_store is store
        finally:
            set_mcp_server_options(original)

    def test_rejects_non_event_store(self):
        with pytest.raises(AssertionError):
            mcp_api.register_streamable_http_event_store("svc", object())
