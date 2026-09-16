# -*- coding: utf-8 -*-
"""Tests for trpc_mcp._trpc_server_transport."""

import types

import pytest

from trpc_mcp import _trpc_server_transport as tst
from trpc_mcp._constants import MCP_STDIO, MCP_STREAMABLE_HTTP, TRPC_MCP_PROTOCOL
from trpc_mcp._trpc_server_transport import (
    McpProcess,
    TrpcMcpServerTransport,
    TrpcMcpServerTransportFactory,
    register_mcp_app,
    _user_mcp_app,
)
from trpc_mcp.tools import tool


def _new_process():
    """Create an McpProcess without invoking the heavy ExecutorProcess init."""
    return McpProcess.__new__(McpProcess)


class TestRegisterMcpApp:

    def test_register(self):
        app = object()
        register_mcp_app("svc-x", app)
        try:
            assert _user_mcp_app["svc-x"] is app
        finally:
            _user_mcp_app.pop("svc-x", None)


class TestAddBindings:

    def test_add_bindings(self):
        from collections import defaultdict

        bindings = defaultdict(set)
        McpProcess._add_bindings(bindings, ["a", "b"], ["svc1", "svc2"])
        assert bindings["a"] == {"svc1", "svc2"}
        assert bindings["b"] == {"svc1", "svc2"}


class TestBuildServiceBindings:

    def test_combines_global_and_per_service(self):

        @tool(name="global_tool")
        def gt(ctx):
            return 1

        @tool(name="svc_tool", mcp_name="svc1")
        def st(ctx):
            return 2

        proc = _new_process()
        tool_services, resource_services, prompt_services = proc._build_service_bindings(["svc1"])
        # global tool visible to the listed service
        assert "svc1" in tool_services["global_tool"]
        assert "svc1" in tool_services["svc_tool"]


class TestMcpIndices:

    def test_filters_mcp_protocol_services(self):
        proc = _new_process()
        svc_mcp = types.SimpleNamespace(opt=types.SimpleNamespace(protocol=TRPC_MCP_PROTOCOL))
        svc_http = types.SimpleNamespace(opt=types.SimpleNamespace(protocol="http"))
        proc.services = [svc_http, svc_mcp, svc_mcp]
        assert proc._mcp_indices() == [1, 2]


class TestHandleExitSignal:

    def test_stops_loop(self):
        proc = _new_process()
        stopped = {}

        class FakeLoop:

            def call_soon_threadsafe(self, fn):
                stopped["fn"] = fn

            def stop(self):
                stopped["stopped"] = True

        proc.loop = FakeLoop()
        proc.handle_exit_signal()
        assert stopped["fn"] == proc.loop.stop

    def test_no_loop_noop(self):
        proc = _new_process()
        proc.loop = None
        proc.handle_exit_signal()  # must not raise


class TestRunMcpApp:

    def test_stdio_raises(self):
        proc = _new_process()
        with pytest.raises(RuntimeError, match="stdio"):
            proc._run_mcp_app([0], object(), MCP_STDIO, None)


class TestHandleMcp:

    def test_starts_thread_once(self, monkeypatch):
        import threading

        proc = _new_process()
        proc._started = False
        proc._start_lock = threading.Lock()
        calls = {"n": 0}

        def fake_start():
            calls["n"] += 1

        # patch the name-mangled executor entrypoint
        monkeypatch.setattr(proc, "_McpProcess__start_mcp_executors", fake_start)
        proc._McpProcess__handle_mcp(0)
        if proc._th:
            proc._th.join(timeout=2)
        assert proc._started is True
        # second call is a no-op
        proc._McpProcess__handle_mcp(0)
        assert calls["n"] == 1


class TestServerTransport:

    def _fake_opts(self):
        service = types.SimpleNamespace(opt=types.SimpleNamespace(protocol=TRPC_MCP_PROTOCOL))
        return types.SimpleNamespace(
            address="127.0.0.1",
            port=8080,
            socket_type="tcp",
            handle=lambda: None,
            checker=lambda: None,
            idle_timeout=10,
            network="tcp",
            service=service,
            target="t",
        )

    def test_init(self):
        transport = TrpcMcpServerTransport()
        assert transport.opts is None
        assert transport.server_engine is None

    def test_listen_and_serve_stdio_raises(self, monkeypatch):
        monkeypatch.setattr(tst, "get_mcp_server_config", lambda: types.SimpleNamespace(transport=MCP_STDIO))
        transport = TrpcMcpServerTransport()
        with pytest.raises(RuntimeError, match="stdio"):
            transport.listen_and_serve(self._fake_opts(), types.SimpleNamespace())

    def test_listen_and_serve_sets_executor(self, monkeypatch):
        monkeypatch.setattr(tst, "get_mcp_server_config", lambda: types.SimpleNamespace(transport=MCP_STREAMABLE_HTTP))

        captured = {}

        class FakeEngine:

            def set_executor_process(self, *args):
                captured["args"] = args

        engine = FakeEngine()
        transport = TrpcMcpServerTransport()
        transport.listen_and_serve(self._fake_opts(), engine)
        assert transport.server_engine is engine
        assert engine.work_handle is McpProcess
        assert "args" in captured

    def test_close(self):
        transport = TrpcMcpServerTransport()
        closed = {}
        transport.server_engine = types.SimpleNamespace(close=lambda: closed.setdefault("c", True))
        transport.close()
        assert closed["c"] is True


class TestTransportFactory:

    def test_create(self):
        factory = TrpcMcpServerTransportFactory()
        assert isinstance(factory.create(), TrpcMcpServerTransport)
