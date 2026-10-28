# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Tests for trpc_mcp._httpx_transport."""

import types

import httpx
import pytest
from trpc_sdk.abc import TrpcContext

from trpc_mcp import _httpx_transport
from trpc_mcp._httpx_transport import (
    TrpcHttpxTransport,
    _TrpcResponseByteStream,
    build_httpx_client_factory,
    open_streamable_http,
)
from trpc_mcp.utils import set_http_header_to_context, set_http_kwargs_to_context

from conftest import run


class _FakeTrpcResponse:

    def __init__(self, chunks=(b"a", b"b"), status=200, header=None):
        self._chunks = list(chunks)
        self.status = status
        self.header = header or {"Content-Type": "text/plain"}
        self.released = False

    async def stream_data(self):
        for chunk in self._chunks:
            yield chunk

    def release(self):
        self.released = True


class TestByteStream:

    def test_iterates_chunks(self):
        rsp = _FakeTrpcResponse(chunks=[b"x", b"y"])
        stream = _TrpcResponseByteStream(rsp)

        async def collect():
            return [chunk async for chunk in stream]

        assert run(collect()) == [b"x", b"y"]

    def test_aclose_releases(self):
        rsp = _FakeTrpcResponse()
        stream = _TrpcResponseByteStream(rsp)
        run(stream.aclose())
        assert rsp.released is True

    def test_aclose_swallows_release_error(self):

        class BadRsp:

            def release(self):
                raise RuntimeError("boom")

        stream = _TrpcResponseByteStream(BadRsp())
        run(stream.aclose())  # must not raise


class TestTransportHelpers:

    def _transport(self, ctx=None):
        return TrpcHttpxTransport("http", "127.0.0.1:8080", ctx or TrpcContext(), [], "client")

    def test_build_trpc_url(self):
        transport = self._transport()
        request = httpx.Request("GET", "http://ignored/path/sub?x=1")
        assert transport._build_trpc_url(request) == "http://127.0.0.1:8080/path/sub?x=1"

    def test_build_headers_drops_hop_by_hop(self):
        transport = self._transport()
        request = httpx.Request("GET", "http://h/p", headers={"Host": "h", "X-Keep": "1"})
        headers = transport._build_headers(request)
        assert "host" not in {k.lower() for k in headers}
        assert headers["x-keep"] == "1"

    def test_build_headers_merges_context_headers(self):
        ctx = TrpcContext()
        set_http_header_to_context(ctx, {"X-Ctx": "v"})
        transport = self._transport(ctx)
        request = httpx.Request("GET", "http://h/p")
        headers = transport._build_headers(request)
        assert headers["X-Ctx"] == "v"


class TestHandleAsyncRequest:

    def test_routes_through_trpc_client(self, monkeypatch):
        ctx = TrpcContext()
        set_http_kwargs_to_context(ctx, {"timeout": 1})
        transport = TrpcHttpxTransport("http", "10.0.0.1:9000", ctx, [], "client")

        captured = {}

        async def fake_request(c, method, url, options, data=None, headers=None, **kwargs):
            captured.update(dict(method=method, url=url, data=data, headers=headers, kwargs=kwargs))
            return _FakeTrpcResponse(status=201, header={"Content-Type": "application/json"})

        monkeypatch.setattr(transport._client, "request", fake_request)

        request = httpx.Request("POST", "http://ignored/mcp", content=b"body")
        response = run(transport.handle_async_request(request))

        assert isinstance(response, httpx.Response)
        assert response.status_code == 201
        assert captured["method"] == "POST"
        assert captured["url"] == "http://10.0.0.1:9000/mcp"
        assert captured["data"] == b"body"

    def test_empty_body_becomes_none(self, monkeypatch):
        ctx = TrpcContext()
        transport = TrpcHttpxTransport("http", "h:1", ctx, [], "client")
        captured = {}

        async def fake_request(c, method, url, options, data=None, headers=None, **kwargs):
            captured["data"] = data
            return _FakeTrpcResponse()

        monkeypatch.setattr(transport._client, "request", fake_request)
        request = httpx.Request("GET", "http://h/p")
        run(transport.handle_async_request(request))
        assert captured["data"] is None


class TestFactory:

    def test_factory_builds_async_client(self):
        factory = build_httpx_client_factory("http", "h:1", TrpcContext(), [], "c")
        client = factory(headers={"A": "B"}, timeout=None, auth=None)
        try:
            assert isinstance(client, httpx.AsyncClient)
            assert isinstance(client._transport, TrpcHttpxTransport)
        finally:
            run(client.aclose())


class TestOpenStreamableHttp:

    def test_uses_new_client_api(self, monkeypatch):
        events = []

        class FakeHttpClient:

            async def __aenter__(self):
                events.append("client_enter")
                return self

            async def __aexit__(self, *a):
                events.append("client_exit")
                return False

        class FakeNewClient:

            def __init__(self, url, http_client=None):
                events.append(("new_client", url))

            async def __aenter__(self):
                return ("read", "write", "session-id")

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr(_httpx_transport._mcp_streamable_http,
                            "streamable_http_client",
                            FakeNewClient,
                            raising=False)

        async def go():
            async with open_streamable_http("http://h/mcp", lambda: FakeHttpClient()) as streams:
                return streams

        assert run(go()) == ("read", "write", "session-id")
        assert "client_enter" in events and "client_exit" in events

    def test_falls_back_to_deprecated_api(self, monkeypatch):

        class FakeOldClient:

            def __init__(self, url, httpx_client_factory=None):
                self.url = url

            async def __aenter__(self):
                return ("r", "w", "id")

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr(_httpx_transport._mcp_streamable_http, "streamable_http_client", None, raising=False)
        monkeypatch.setattr(_httpx_transport._mcp_streamable_http,
                            "streamablehttp_client",
                            FakeOldClient,
                            raising=False)

        async def go():
            async with open_streamable_http("http://h/mcp", lambda: None) as streams:
                return streams

        assert run(go()) == ("r", "w", "id")
