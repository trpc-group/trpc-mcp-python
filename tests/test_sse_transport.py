# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Tests for trpc_mcp._sse_transport."""

import json
from http import HTTPStatus
from uuid import uuid4

import pytest
from starlette.requests import Request
from trpc_sdk.abc import TrpcContext

from trpc_mcp import _sse_transport
from trpc_mcp._sse_transport import TrpcSseServerTransport

from conftest import run


def _make_transport(redis_conf=None):
    return TrpcSseServerTransport("/messages/", redis_conf=redis_conf, mcp_app=object())


class TestConvertKey:

    def test_flat_rename(self):
        src = {"old": 1}
        TrpcSseServerTransport._convert_key(src, {"old": "new"})
        assert src == {"new": 1}

    def test_nested_rename(self):
        src = {"options": {"disable_servicerouter": True}}
        TrpcSseServerTransport._convert_key(src, {"options": {"disable_servicerouter": "disable_service_router"}})
        assert src == {"options": {"disable_service_router": True}}

    def test_missing_key_noop(self):
        src = {"keep": 1}
        TrpcSseServerTransport._convert_key(src, {"absent": "x"})
        assert src == {"keep": 1}


class TestScopeSerialization:

    def test_round_trip(self):
        transport = _make_transport()
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/messages/",
            "raw_path": b"/messages/",
            "query_string": b"session_id=abc",
            "root_path": "",
            "client": ("1.2.3.4", 5555),
            "server": ("127.0.0.1", 8080),
            "headers": [(b"content-type", b"application/json")],
        }
        data = transport._serialize_scope(scope)
        assert data["query_string"] == "session_id=abc"
        restored = transport._deserialize_scope(dict(data))
        assert restored["raw_path"] == b"/messages/"
        assert restored["query_string"] == b"session_id=abc"
        assert restored["client"] == ("1.2.3.4", 5555)
        assert restored["server"] == ("127.0.0.1", 8080)
        assert restored["headers"][0] == (b"content-type", b"application/json")

    def test_serialize_scope_without_client_server(self):
        transport = _make_transport()
        scope = {"type": "http", "headers": []}
        data = transport._serialize_scope(scope)
        assert data["client"] is None
        assert data["server"] is None
        restored = transport._deserialize_scope(dict(data))
        assert restored["client"] is None


class TestContextSerializationExtra:

    def test_serialize_with_timing_fields(self):
        transport = _make_transport()
        ctx = TrpcContext()
        ctx.deadline = 1234
        ctx.timeout = 30
        ctx.recv_time = 9999
        data = transport._serialize_context(ctx)
        assert data["deadline"] == 1234
        assert data["timeout"] == 30
        assert data["recv_time"] == 9999

    def test_deserialize_with_timing_and_callee(self):
        transport = _make_transport()
        restored = transport._deserialize_context({
            "deadline": 11,
            "timeout": 22,
            "remote_ip": "5.5.5.5",
            "recv_time": 33,
            "callee_method": "/svc/handle",
            "extra": "kept",
        })
        assert restored.deadline == 11
        assert restored.timeout == 22
        assert restored.remote_ip == "5.5.5.5"
        assert restored.recv_time == 33
        assert restored.get_meta_data("extra") == "kept"


class TestContextSerialization:

    def test_serialize_minimal(self):
        transport = _make_transport()
        ctx = TrpcContext()
        ctx.with_meta_data("simple", "value")
        ctx.with_meta_data("complex", object())  # filtered out (non-primitive)
        ctx.remote_ip = "9.9.9.9"
        data = transport._serialize_context(ctx)
        assert data["simple"] == "value"
        assert "complex" not in data
        assert data["remote_ip"] == "9.9.9.9"

    def test_deserialize_round_trip(self):
        transport = _make_transport()
        ctx = TrpcContext()
        ctx.with_meta_data("k", "v")
        ctx.remote_ip = "1.1.1.1"
        data = transport._serialize_context(ctx)
        restored = transport._deserialize_context(dict(data))
        assert restored.remote_ip == "1.1.1.1"
        assert restored.get_meta_data("k") == "v"

    def test_make_and_get_data_from_redis(self):
        transport = _make_transport()
        ctx = TrpcContext()
        ctx.with_meta_data("k", "v")
        scope = {"type": "http", "headers": [], "query_string": b"session_id=x"}
        payload = transport._make_data_to_redis(ctx, scope, b"hello")
        message = {"data": payload.encode("utf-8")}
        out_ctx, out_scope, out_body = transport._get_data_from_redis(message)
        assert out_body == b"hello"
        assert out_scope["trpc_context"] is out_ctx
        assert out_ctx.get_meta_data("k") == "v"


class TestSelectorOption:

    def test_no_options_returns_default(self):
        transport = _make_transport(redis_conf={"target": "test://svc"})
        option = transport._parse_dict_to_selector_option(TrpcContext())
        assert option is not None

    def test_with_options(self):
        transport = _make_transport(redis_conf={
            "target": "test://svc",
            "options": {
                "namespace": "Production",
                "metadata": {
                    "k": "v"
                }
            },
        })
        option = transport._parse_dict_to_selector_option(TrpcContext())
        assert option is not None


class _FakeNode:
    ip = "10.0.0.5"
    port = 6380


class _FakeSelector:

    def __init__(self, node=_FakeNode()):
        self._node = node

    async def select(self, netloc, options):
        return self._node


class TestResolveRedisTarget:

    def test_no_target_noop(self):
        transport = _make_transport(redis_conf={"host": "h"})
        run(transport._resolve_redis_target(TrpcContext()))
        assert transport._redis_conf["host"] == "h"

    def test_resolves_target_to_host_port(self, monkeypatch):
        transport = _make_transport(redis_conf={"target": "test://svc"})
        monkeypatch.setattr(_sse_transport, "get_selector", lambda scheme: _FakeSelector())
        run(transport._resolve_redis_target(TrpcContext()))
        assert transport._redis_conf["host"] == "10.0.0.5"
        assert transport._redis_conf["port"] == 6380

    def test_raises_when_node_none(self, monkeypatch):
        transport = _make_transport(redis_conf={"target": "test://svc"})
        monkeypatch.setattr(_sse_transport, "get_selector", lambda scheme: _FakeSelector(node=None))
        with pytest.raises(ValueError):
            run(transport._resolve_redis_target(TrpcContext()))


class _FakeRedis:

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.published = []

    async def publish(self, channel, body):
        self.published.append((channel, body))
        return 1


class TestGetRedisSession:

    def test_none_when_no_conf(self):
        transport = _make_transport()
        assert run(transport._get_redis_session(TrpcContext())) is None

    def test_builds_redis(self, monkeypatch):
        monkeypatch.setattr(_sse_transport.aioredis, "Redis", _FakeRedis)
        transport = _make_transport(redis_conf={"host": "127.0.0.1", "port": 6379})
        session = run(transport._get_redis_session(TrpcContext()))
        assert isinstance(session, _FakeRedis)
        # cached
        assert run(transport._get_redis_session(TrpcContext())) is session


class TestTryPublish:

    def test_no_session_returns_false(self):
        transport = _make_transport()
        assert run(transport.try_publish(uuid4(), TrpcContext(), "body")) is False

    def test_publishes(self, monkeypatch):
        monkeypatch.setattr(_sse_transport.aioredis, "Redis", _FakeRedis)
        transport = _make_transport(redis_conf={"host": "h"})
        result = run(transport.try_publish(uuid4(), TrpcContext(), "body"))
        assert result is True

    def test_publish_error_returns_false(self, monkeypatch):

        class BadRedis(_FakeRedis):

            async def publish(self, channel, body):
                raise RuntimeError("redis down")

        monkeypatch.setattr(_sse_transport.aioredis, "Redis", BadRedis)
        transport = _make_transport(redis_conf={"host": "h"})
        assert run(transport.try_publish(uuid4(), TrpcContext(), "body")) is False


class _FakePubSub:

    def __init__(self, messages):
        self._messages = messages
        self.subscribed = None
        self.unsubscribed = None
        self.closed = False

    async def subscribe(self, channel):
        self.subscribed = channel

    async def listen(self):
        for msg in self._messages:
            yield msg

    async def unsubscribe(self, channel):
        self.unsubscribed = channel

    async def aclose(self):
        self.closed = True


class _PubSubRedis(_FakeRedis):

    def __init__(self, messages, **kwargs):
        super().__init__(**kwargs)
        self._pubsub = _FakePubSub(messages)

    def pubsub(self):
        return self._pubsub


class TestTrySubscribe:

    def test_no_session_returns(self):
        transport = _make_transport()
        run(transport.try_subscribe(uuid4(), TrpcContext()))

    def test_subscribe_dispatches_messages(self, monkeypatch):
        handled = []
        messages = [{"type": "message", "data": b"{}"}, {"type": "subscribe"}]

        def make_redis(**kwargs):
            return _PubSubRedis(messages, **kwargs)

        monkeypatch.setattr(_sse_transport.aioredis, "Redis", make_redis)
        transport = _make_transport(redis_conf={"host": "h"})

        async def fake_handle(session_id, message):
            handled.append(message)

        monkeypatch.setattr(transport, "handle_post_message_by_session", fake_handle)
        run(transport.try_subscribe(uuid4(), TrpcContext()))
        assert len(handled) == 1

    def test_subscribe_handles_listen_error(self, monkeypatch):
        messages = [{"type": "message", "data": b"{}"}]

        def make_redis(**kwargs):
            return _PubSubRedis(messages, **kwargs)

        monkeypatch.setattr(_sse_transport.aioredis, "Redis", make_redis)
        transport = _make_transport(redis_conf={"host": "h"})

        async def boom(session_id, message):
            raise RuntimeError("handler failed")

        # Error inside the listen loop must be caught (logged), not raised.
        monkeypatch.setattr(transport, "handle_post_message_by_session", boom)
        run(transport.try_subscribe(uuid4(), TrpcContext()))


class TestHandlePostMessage:

    def _scope(self, query=b"session_id=", headers=None):
        return {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/messages/",
            "raw_path": b"/messages/",
            "query_string": query,
            "root_path": "",
            "client": ("1.2.3.4", 5),
            "server": ("127.0.0.1", 80),
            "headers": headers or [(b"content-type", b"application/json"), (b"host", b"127.0.0.1")],
        }

    def _run_post(self, transport, scope, body=b""):
        sent = []

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(msg):
            sent.append(msg)

        run(transport.handle_post_message(scope, receive, send))
        return sent

    def test_missing_session_id(self):
        transport = _make_transport()
        scope = self._scope(query=b"")
        sent = self._run_post(transport, scope)
        start = next(m for m in sent if m["type"] == "http.response.start")
        assert start["status"] == HTTPStatus.BAD_REQUEST.value

    def test_invalid_session_id(self):
        transport = _make_transport()
        scope = self._scope(query=b"session_id=not-a-uuid")
        sent = self._run_post(transport, scope)
        start = next(m for m in sent if m["type"] == "http.response.start")
        assert start["status"] == HTTPStatus.BAD_REQUEST.value

    def test_unknown_session_no_redis_404(self):
        transport = _make_transport()
        sid = uuid4()
        scope = self._scope(query=f"session_id={sid.hex}".encode())
        sent = self._run_post(transport, scope)
        start = next(m for m in sent if m["type"] == "http.response.start")
        assert start["status"] == HTTPStatus.NOT_FOUND.value

    def test_unknown_session_with_redis_accepted(self, monkeypatch):
        monkeypatch.setattr(_sse_transport.aioredis, "Redis", _FakeRedis)
        transport = _make_transport(redis_conf={"host": "h"})
        sid = uuid4()
        scope = self._scope(query=f"session_id={sid.hex}".encode())
        sent = self._run_post(transport, scope, body=b"{}")
        start = next(m for m in sent if m["type"] == "http.response.start")
        assert start["status"] == HTTPStatus.ACCEPTED.value

    def test_known_session_valid_message(self):
        transport = _make_transport()
        sid = uuid4()

        captured = []

        class _Writer:

            async def send(self, item):
                captured.append(item)

        transport._read_stream_writers[sid] = _Writer()
        valid = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()
        scope = self._scope(query=f"session_id={sid.hex}".encode())
        sent = self._run_post(transport, scope, body=valid)
        start = next(m for m in sent if m["type"] == "http.response.start")
        assert start["status"] == HTTPStatus.ACCEPTED.value
        assert len(captured) == 1

    def test_known_session_invalid_message(self):
        transport = _make_transport()
        sid = uuid4()

        captured = []

        class _Writer:

            async def send(self, item):
                captured.append(item)

        transport._read_stream_writers[sid] = _Writer()
        scope = self._scope(query=f"session_id={sid.hex}".encode())
        sent = self._run_post(transport, scope, body=b"{not json")
        start = next(m for m in sent if m["type"] == "http.response.start")
        assert start["status"] == HTTPStatus.BAD_REQUEST.value
        assert len(captured) == 1  # error forwarded to writer


class TestHandlePostMessageBySession:

    def test_missing_session_id_raises(self):
        transport = _make_transport()
        scope = {
            "type": "http",
            "method": "POST",
            "headers": [],
            "query_string": b"",
            "path": "/messages/",
            "scheme": "http",
            "server": ("127.0.0.1", 80),
            "client": ("1.2.3.4", 5),
            "raw_path": b"/messages/",
        }
        data = json.dumps({
            "ctx": {},
            "scope": transport._serialize_scope(scope),
            "body": "{}",
        })
        message = {"data": data.encode("utf-8")}
        with pytest.raises(ValueError, match="session_id is missing"):
            run(transport.handle_post_message_by_session(uuid4(), message))

    def test_unknown_session_raises(self):
        transport = _make_transport()
        sid = uuid4()
        scope = {
            "type": "http",
            "method": "POST",
            "headers": [],
            "query_string": f"session_id={sid.hex}".encode(),
            "path": "/messages/",
            "scheme": "http",
            "server": ("127.0.0.1", 80),
            "client": ("1.2.3.4", 5),
            "raw_path": b"/messages/",
        }
        data = json.dumps({
            "ctx": {},
            "scope": transport._serialize_scope(scope),
            "body": "{}",
        })
        message = {"data": data.encode("utf-8")}
        with pytest.raises(ValueError, match="Could not find session"):
            run(transport.handle_post_message_by_session(sid, message))

    def test_valid_message_dispatched(self):
        transport = _make_transport()
        sid = uuid4()
        captured = []

        class _Writer:

            async def send(self, item):
                captured.append(item)

        transport._read_stream_writers[sid] = _Writer()
        scope = {
            "type": "http",
            "method": "POST",
            "headers": [],
            "query_string": f"session_id={sid.hex}".encode(),
            "path": "/messages/",
            "scheme": "http",
            "server": ("127.0.0.1", 80),
            "client": ("1.2.3.4", 5),
            "raw_path": b"/messages/",
        }
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        data = json.dumps({
            "ctx": {},
            "scope": transport._serialize_scope(scope),
            "body": body,
        })
        message = {"data": data.encode("utf-8")}
        run(transport.handle_post_message_by_session(sid, message))
        assert len(captured) == 1

    def test_invalid_message_forwarded_as_error(self):
        transport = _make_transport()
        sid = uuid4()
        captured = []

        class _Writer:

            async def send(self, item):
                captured.append(item)

        transport._read_stream_writers[sid] = _Writer()
        scope = {
            "type": "http",
            "method": "POST",
            "headers": [],
            "query_string": f"session_id={sid.hex}".encode(),
            "path": "/messages/",
            "scheme": "http",
            "server": ("127.0.0.1", 80),
            "client": ("1.2.3.4", 5),
            "raw_path": b"/messages/",
        }
        data = json.dumps({
            "ctx": {},
            "scope": transport._serialize_scope(scope),
            "body": "{not valid json",
        })
        message = {"data": data.encode("utf-8")}
        run(transport.handle_post_message_by_session(sid, message))
        assert len(captured) == 1  # validation error forwarded
