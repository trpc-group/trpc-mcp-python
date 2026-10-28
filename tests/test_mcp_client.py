# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Tests for trpc_mcp.mcp_client."""

import types

import pytest
from trpc_sdk.abc import TrpcContext

from trpc_mcp import mcp_client
from trpc_mcp._config import McpClientConfig
from trpc_mcp._constants import MCP_SSE, MCP_STREAMABLE_HTTP
from trpc_mcp.mcp_client import McpProxy, _Wrapper

from conftest import run


class TestWrapper:

    def test_direct_attribute(self):
        info = types.SimpleNamespace(name="abc")
        wrapper = _Wrapper(info)
        assert wrapper.name == "abc"

    def test_snake_to_camel_lookup(self):
        info = types.SimpleNamespace(mimeType="text/plain")
        wrapper = _Wrapper(info)
        # ``mime_type`` doesn't exist but ``mimeType`` does.
        assert wrapper.mime_type == "text/plain"

    def test_snake_to_lower_camel_helper(self):
        wrapper = _Wrapper(types.SimpleNamespace())
        assert wrapper._snake_to_lower_camel("a_b_c") == "aBC"
        assert wrapper._snake_to_lower_camel("simple") == "simple"


class TestProxyInit:

    def test_defaults(self):
        proxy = McpProxy("svc")
        assert proxy.name == "svc"
        assert proxy.base_url == ""
        assert proxy.session is None

    def test_base_url_arg(self):
        proxy = McpProxy("svc", base_url="/api")
        assert proxy.base_url == "/api"

    def test_session_raises_when_uninitialized(self):
        proxy = McpProxy("svc")
        with pytest.raises(RuntimeError, match="not initialized"):
            proxy._session()


class TestResolveRuntime:

    def test_explicit_args_take_precedence(self, monkeypatch):
        monkeypatch.setattr(mcp_client, "get_mcp_client_config", lambda: McpClientConfig())
        proxy = McpProxy("svc")
        host, transport, base_url = proxy._resolve_runtime("h.com", MCP_STREAMABLE_HTTP)
        assert host == "h.com"
        assert transport == MCP_STREAMABLE_HTTP

    def test_falls_back_to_config(self, monkeypatch):
        cfg = McpClientConfig(transport="streamable-http", base_url="/cfg")
        monkeypatch.setattr(mcp_client, "get_mcp_client_config", lambda: cfg)
        proxy = McpProxy("svc")
        monkeypatch.setattr(proxy, "_host_from_config", lambda: "")
        host, transport, base_url = proxy._resolve_runtime(None, None)
        assert host == "svc"  # falls back to name
        assert transport == "streamable-http"
        assert base_url == "/cfg"

    def test_defaults_when_no_config(self, monkeypatch):
        monkeypatch.setattr(mcp_client, "get_mcp_client_config", lambda: McpClientConfig())
        proxy = McpProxy("svc")
        monkeypatch.setattr(proxy, "_host_from_config", lambda: "")
        host, transport, base_url = proxy._resolve_runtime(None, None)
        assert transport == MCP_SSE
        assert base_url == ""

    def test_explicit_base_url_empty_string_wins(self, monkeypatch):
        cfg = McpClientConfig(base_url="/cfg")
        monkeypatch.setattr(mcp_client, "get_mcp_client_config", lambda: cfg)
        proxy = McpProxy("svc", base_url="")
        _, _, base_url = proxy._resolve_runtime(None, None)
        assert base_url == ""


class TestHostFromConfig:

    def test_returns_empty_when_no_target(self):
        proxy = McpProxy("nonexistent-service")
        assert proxy._host_from_config() == ""


class TestGetOptions:

    def test_adds_timeout_and_protocol_when_empty(self):
        proxy = McpProxy("svc")
        opts = proxy._McpProxy__get_options()
        assert len(opts) == 2  # timeout + protocol

    def test_keeps_given_options_and_adds_protocol(self):
        proxy = McpProxy("svc", options=["x"])
        opts = proxy._McpProxy__get_options(["y"])
        # given + proxy-level + protocol (no default timeout because non-empty)
        assert opts[:2] == ["y", "x"]
        assert len(opts) == 3


class TestResolveUrls:

    def test_explicit_scheme_preserved(self):
        proxy = McpProxy("svc")
        display, scheme, netloc = proxy._resolve_urls("ip://127.0.0.1:8080", "sse")
        assert scheme == "ip"
        assert netloc == "127.0.0.1:8080"
        assert display.startswith("http://127.0.0.1:8080")

    def test_ip_host_without_scheme(self):
        proxy = McpProxy("svc")
        display, scheme, netloc = proxy._resolve_urls("127.0.0.1:8080", "sse")
        assert scheme == "http"
        assert display == "http://127.0.0.1:8080/sse"

    def test_domain_without_scheme(self):
        proxy = McpProxy("svc")
        display, scheme, netloc = proxy._resolve_urls("my.service", "mcp")
        assert scheme == "http"
        assert netloc == "my.service"


class _FakeSession:

    def __init__(self):
        self.calls = []

    async def list_tools(self):
        return types.SimpleNamespace(tools=[types.SimpleNamespace(name="t1")])

    async def list_resources(self):
        return types.SimpleNamespace(resources=[types.SimpleNamespace(name="r1")])

    async def list_resource_templates(self):
        return types.SimpleNamespace(resourceTemplates=[types.SimpleNamespace(name="rt1")])

    async def list_prompts(self):
        return types.SimpleNamespace(prompts=[types.SimpleNamespace(name="p1")])

    async def call_tool(self, name, arguments, meta=None):
        self.calls.append(("call_tool", name, arguments, {"meta": meta}))
        return types.SimpleNamespace(result="tool-result")

    async def get_prompt(self, name, arguments):
        return types.SimpleNamespace(result="prompt-result")

    async def read_resource(self, uri):
        return types.SimpleNamespace(result=str(uri))


class TestListMethods:

    def _proxy_with_session(self):
        proxy = McpProxy("svc")
        proxy.session = _FakeSession()
        return proxy

    def test_list_tools(self):
        proxy = self._proxy_with_session()
        tools = run(proxy.list_tools(TrpcContext()))
        assert tools[0].name == "t1"

    def test_list_resources(self):
        proxy = self._proxy_with_session()
        resources = run(proxy.list_resources(TrpcContext()))
        assert resources[0].name == "r1"

    def test_list_resource_templates(self):
        proxy = self._proxy_with_session()
        templates = run(proxy.list_resource_templates(TrpcContext()))
        assert templates[0].name == "rt1"

    def test_list_prompts(self):
        proxy = self._proxy_with_session()
        prompts = run(proxy.list_prompts(TrpcContext()))
        assert prompts[0].name == "p1"


class TestExecuteTool:

    def test_execute_tool_success(self):
        proxy = McpProxy("svc")
        proxy.session = _FakeSession()
        result = run(proxy.execute_tool(TrpcContext(), "t1", {"a": 1}))
        assert result.result == "tool-result"

    def test_execute_tool_forwards_meta_when_supported(self):
        proxy = McpProxy("svc")
        session = _FakeSession()
        proxy.session = session
        run(proxy.execute_tool(TrpcContext(), "t1", {}, meta={"m": 1}))
        assert session.calls[0][3].get("meta") == {"m": 1}

    def test_execute_tool_retries_then_raises(self):
        proxy = McpProxy("svc")

        class Boom:

            async def call_tool(self, *a, **k):
                raise RuntimeError("nope")

        proxy.session = Boom()
        with pytest.raises(RuntimeError, match="nope"):
            run(proxy.execute_tool(TrpcContext(), "t1", {}, retries=2, delay=0))

    def test_execute_tool_meta_unsupported_warns(self, monkeypatch):
        proxy = McpProxy("svc")

        class NoMeta:

            async def call_tool(self, name, arguments):
                return "ok"

        proxy.session = NoMeta()
        result = run(proxy.execute_tool(TrpcContext(), "t1", {}, meta={"m": 1}))
        assert result == "ok"


class TestGetPromptsAndReadResource:

    def test_get_prompts_success(self):
        proxy = McpProxy("svc")
        proxy.session = _FakeSession()
        result = run(proxy.get_prompts(TrpcContext(), "p1", {}))
        assert result.result == "prompt-result"

    def test_get_prompts_retry_raises(self):
        proxy = McpProxy("svc")

        class Boom:

            async def get_prompt(self, *a, **k):
                raise RuntimeError("fail")

        proxy.session = Boom()
        with pytest.raises(RuntimeError):
            run(proxy.get_prompts(TrpcContext(), "p1", {}, retries=2, delay=0))

    def test_read_resource_success(self):
        proxy = McpProxy("svc")
        proxy.session = _FakeSession()
        result = run(proxy.read_resource(TrpcContext(), "res://x"))
        assert "res://x" in result.result

    def test_read_resource_retry_raises(self):
        proxy = McpProxy("svc")

        class Boom:

            async def read_resource(self, *a, **k):
                raise RuntimeError("fail")

        proxy.session = Boom()
        with pytest.raises(RuntimeError):
            run(proxy.read_resource(TrpcContext(), "res://x", retries=2, delay=0))


class _CtxMgr:

    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *a):
        return False


class _FakeClientSession:

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.initialized = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def initialize(self):
        self.initialized = True


class TestInitialize:

    def test_initialize_sse(self, monkeypatch):
        monkeypatch.setattr(mcp_client, "get_mcp_client_config", lambda: McpClientConfig())
        monkeypatch.setattr(mcp_client, "build_httpx_client_factory", lambda *a, **k: (lambda **kw: None))
        monkeypatch.setattr(mcp_client, "sse_client", lambda url, httpx_client_factory=None: _CtxMgr(("read", "write")))
        monkeypatch.setattr(mcp_client, "ClientSession", _FakeClientSession)

        proxy = McpProxy("svc", host="127.0.0.1:8080")
        run(proxy.initialize(TrpcContext()))
        assert isinstance(proxy.session, _FakeClientSession)
        assert proxy.session.initialized is True

    def test_initialize_streamable_http(self, monkeypatch):
        monkeypatch.setattr(mcp_client, "get_mcp_client_config", lambda: McpClientConfig())
        monkeypatch.setattr(mcp_client, "build_httpx_client_factory", lambda *a, **k: (lambda **kw: None))
        monkeypatch.setattr(mcp_client, "open_streamable_http", lambda url, factory: _CtxMgr(("read", "write", "sid")))
        monkeypatch.setattr(mcp_client, "ClientSession", _FakeClientSession)

        proxy = McpProxy("svc", host="127.0.0.1:8080", transport=MCP_STREAMABLE_HTTP)
        run(proxy.initialize(TrpcContext()))
        assert proxy.session.initialized is True

    def test_initialize_failure_cleans_up_and_raises(self, monkeypatch):
        monkeypatch.setattr(mcp_client, "get_mcp_client_config", lambda: McpClientConfig())
        monkeypatch.setattr(mcp_client, "build_httpx_client_factory", lambda *a, **k: (lambda **kw: None))

        def boom(*a, **k):
            raise RuntimeError("connect failed")

        monkeypatch.setattr(mcp_client, "sse_client", boom)
        proxy = McpProxy("svc", host="127.0.0.1:8080")
        with pytest.raises(RuntimeError, match="connect failed"):
            run(proxy.initialize(TrpcContext()))
        assert proxy.session is None


class TestCleanup:

    def test_cleanup_resets_session(self):
        proxy = McpProxy("svc")
        proxy.session = _FakeSession()
        run(proxy.cleanup())
        assert proxy.session is None

    def test_cleanup_handles_error(self, monkeypatch):
        proxy = McpProxy("svc")

        class BadStack:

            async def aclose(self):
                raise RuntimeError("close fail")

        proxy.exit_stack = BadStack()
        # Should swallow the error and not raise.
        run(proxy.cleanup())
