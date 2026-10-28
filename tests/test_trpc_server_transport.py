# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Tests for trpc_mcp._trpc_server_transport."""

import asyncio
import types
from collections import defaultdict

import pytest
import uvicorn
from trpc_sdk.common import get_current_process_var
from trpc_sdk.common import set_current_process_var
from trpc_sdk.runtime._threadmodel._worker_view import WorkerLoopView
from trpc_sdk.transport import UserProtocolTransport
from trpc_sdk.transport import get_protocol_handle

from trpc_mcp import _trpc_server_transport as tst
from trpc_mcp._config import McpServerConfig
from trpc_mcp._constants import MCP_STDIO
from trpc_mcp._constants import MCP_STREAMABLE_HTTP
from trpc_mcp._constants import TRPC_MCP_PROCESS_VAR
from trpc_mcp._constants import TRPC_MCP_PROTOCOL
from trpc_mcp._trpc_server_transport import McpProcess
from trpc_mcp._trpc_server_transport import TrpcMcpServerTransport
from trpc_mcp._trpc_server_transport import _user_mcp_app
from trpc_mcp._trpc_server_transport import get_or_create_mcp_process
from trpc_mcp._trpc_server_transport import register_mcp_app
from trpc_mcp._trpc_server_transport import start_mcp
from trpc_mcp.tools import tool


class _FakeServiceOpt:

    def __init__(self, protocol=TRPC_MCP_PROTOCOL):
        self.protocol = protocol
        self.filters = []

    def add_filter(self, filter_obj):
        self.filters.append(filter_obj)


def _service(protocol=TRPC_MCP_PROTOCOL):
    return types.SimpleNamespace(opt=_FakeServiceOpt(protocol))


def _tran_opts(port, service, name):
    return types.SimpleNamespace(address=("127.0.0.1", port), port=port, service_name=name, service=service,
                                 idle_timeout=0)


def _fake_worker(drain_seconds=1.5):
    """A worker serving one plain address and two MCP addresses on the same service."""
    mcp_service = _service()
    http_service = _service("http")
    return types.SimpleNamespace(
        services=[http_service, mcp_service, mcp_service],
        tran_opts=[
            _tran_opts(9000, http_service, "svc.http"),
            _tran_opts(9001, mcp_service, "svc.mcp"),
            _tran_opts(9002, mcp_service, "svc.mcp"),
        ],
        transports=[object(), UserProtocolTransport(start_mcp), UserProtocolTransport(start_mcp)],
        exit_callbacks=[],
        post_drain_callbacks=[],
        drain_seconds=drain_seconds,
    )


@pytest.fixture(autouse=True)
def _fresh_process_var():
    set_current_process_var(TRPC_MCP_PROCESS_VAR, None)
    yield
    mcp_process = get_current_process_var(TRPC_MCP_PROCESS_VAR)
    if mcp_process is not None and mcp_process.thread is not None:
        mcp_process.thread.join(timeout=2)
    set_current_process_var(TRPC_MCP_PROCESS_VAR, None)


@pytest.fixture
def fake_uvicorn(monkeypatch):
    """Record the sockets ``uvicorn.Server.run`` gets instead of serving."""
    calls = []
    bound = []

    def fake_socket(host, port):
        sock = types.SimpleNamespace(addr=(host, port), closed=False)
        sock.close = lambda: setattr(sock, "closed", True)
        bound.append(sock)
        return sock

    def fake_run(self, sockets=None):
        calls.append(sockets)

    monkeypatch.setattr(tst, "create_uvicorn_compatible_socket", fake_socket)
    monkeypatch.setattr(uvicorn.Server, "run", fake_run)
    return types.SimpleNamespace(calls=calls, bound=bound)


class TestRegistration:

    def test_protocol_handle_registered_at_import(self):
        assert get_protocol_handle(TRPC_MCP_PROTOCOL) is start_mcp

    def test_transport_is_user_protocol_bound_to_starter(self):
        transport = TrpcMcpServerTransport()
        assert isinstance(transport, UserProtocolTransport)
        assert transport.starter is start_mcp

    def test_register_mcp_app(self):
        app = object()
        register_mcp_app("svc-x", app)
        try:
            assert _user_mcp_app["svc-x"] is app
        finally:
            _user_mcp_app.pop("svc-x", None)


class TestBindings:

    def test_add_bindings(self):
        bindings = defaultdict(set)
        tst._add_bindings(bindings, ["a", "b"], ["svc1", "svc2"])
        assert bindings["a"] == {"svc1", "svc2"}
        assert bindings["b"] == {"svc1", "svc2"}

    def test_combines_global_and_per_service(self):

        @tool(name="global_tool")
        def gt(ctx):
            return 1

        @tool(name="svc_tool", mcp_name="svc1")
        def st(ctx):
            return 2

        tool_services, _, _ = tst._build_service_bindings(["svc1"])
        assert "svc1" in tool_services["global_tool"]
        assert "svc1" in tool_services["svc_tool"]


class TestMcpProcess:

    def test_process_var_is_reused(self):
        first = get_or_create_mcp_process()
        assert get_or_create_mcp_process() is first
        assert get_current_process_var(TRPC_MCP_PROCESS_VAR) is first

    def test_request_stop_without_server_is_noop(self):
        McpProcess().request_stop()

    def test_join_without_thread_is_noop(self):
        McpProcess().join(0.1)


class TestStartMcp:

    def test_mcp_indices_only_matches_this_starter(self):
        worker = _fake_worker()
        worker.transports.append(UserProtocolTransport(lambda w, i: None))
        assert tst._mcp_indices(worker) == [1, 2]

    def test_starts_one_thread_for_every_mcp_address(self, fake_uvicorn):
        worker = _fake_worker()
        start_mcp(worker, 1)
        mcp_process = get_current_process_var(TRPC_MCP_PROCESS_VAR)
        first_thread = mcp_process.thread
        start_mcp(worker, 2)
        first_thread.join(timeout=2)

        assert mcp_process.started is True
        assert mcp_process.thread is first_thread
        assert mcp_process.mcp_app.name == "svc.mcp,svc.mcp"
        assert len(fake_uvicorn.calls) == 1
        assert [sock.addr for sock in fake_uvicorn.calls[0]] == [("127.0.0.1", 9001), ("127.0.0.1", 9002)]
        assert len(worker.exit_callbacks) == 1
        assert len(worker.post_drain_callbacks) == 1

    def test_uvicorn_gets_drain_as_graceful_timeout(self, fake_uvicorn):
        worker = _fake_worker(drain_seconds=2.5)
        start_mcp(worker, 1)
        server = get_current_process_var(TRPC_MCP_PROCESS_VAR).server
        assert server.config.timeout_graceful_shutdown == 2.5

    def test_exit_callback_stops_uvicorn(self, fake_uvicorn):
        worker = _fake_worker()
        start_mcp(worker, 1)
        mcp_process = get_current_process_var(TRPC_MCP_PROCESS_VAR)
        assert mcp_process.server.should_exit is False
        for callback in worker.exit_callbacks:
            callback()
        assert mcp_process.server.should_exit is True
        for callback in worker.post_drain_callbacks:
            callback()
        assert not mcp_process.thread.is_alive()

    def test_worker_loop_view_callbacks_reach_real_worker(self, fake_uvicorn):
        worker = _fake_worker()
        loop = asyncio.new_event_loop()
        try:
            view = WorkerLoopView(worker, loop)
            start_mcp(view, 1)
        finally:
            loop.close()
        assert len(worker.exit_callbacks) == 1
        assert len(worker.post_drain_callbacks) == 1

    def test_streamable_http_transport(self, fake_uvicorn, monkeypatch):
        monkeypatch.setattr(tst, "get_mcp_server_config", lambda: McpServerConfig(transport=MCP_STREAMABLE_HTTP))
        start_mcp(_fake_worker(), 1)
        assert get_current_process_var(TRPC_MCP_PROCESS_VAR).started is True

    def test_stdio_raises_value_error(self, fake_uvicorn, monkeypatch):
        monkeypatch.setattr(tst, "get_mcp_server_config", lambda: McpServerConfig(transport=MCP_STDIO))
        with pytest.raises(ValueError, match="stdio"):
            start_mcp(_fake_worker(), 1)
        assert fake_uvicorn.bound == []

    def test_bind_failure_raises_before_thread(self, fake_uvicorn, monkeypatch):
        opened = []

        def flaky_socket(host, port):
            if port == 9002:
                raise OSError("address in use")
            sock = types.SimpleNamespace(closed=False)
            sock.close = lambda: setattr(sock, "closed", True)
            opened.append(sock)
            return sock

        monkeypatch.setattr(tst, "create_uvicorn_compatible_socket", flaky_socket)
        worker = _fake_worker()
        with pytest.raises(OSError):
            start_mcp(worker, 1)
        mcp_process = get_current_process_var(TRPC_MCP_PROCESS_VAR)
        assert mcp_process.started is False
        assert mcp_process.thread is None
        assert worker.exit_callbacks == []
        assert [sock.closed for sock in opened] == [True]
        assert fake_uvicorn.calls == []

    def test_callback_filter_added_once_per_service(self, fake_uvicorn, monkeypatch):
        callback_filter = object()
        monkeypatch.setattr(tst, "get_server_filter", lambda name: callback_filter)
        worker = _fake_worker()
        mcp_process = get_or_create_mcp_process()
        tst._install_callback_filter(mcp_process, worker, [1, 2])
        tst._install_callback_filter(mcp_process, worker, [1, 2])
        assert worker.services[1].opt.filters == [callback_filter]
        assert worker.services[0].opt.filters == []

    def test_user_registered_app_is_used(self, fake_uvicorn):
        user_app = tst.TrpcMcpServer(name="user-app")
        register_mcp_app("svc.mcp", user_app)
        try:
            start_mcp(_fake_worker(), 1)
            assert get_current_process_var(TRPC_MCP_PROCESS_VAR).mcp_app is user_app
        finally:
            _user_mcp_app.pop("svc.mcp", None)
