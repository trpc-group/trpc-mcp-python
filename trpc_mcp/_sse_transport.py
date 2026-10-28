# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""SSE transport extensions for TRPC MCP."""

import json
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Any
from urllib.parse import ParseResult
from urllib.parse import quote
from urllib.parse import urlparse
from uuid import UUID
from uuid import uuid4

from pydantic import ValidationError

import anyio
import mcp.types as types
from anyio.streams.memory import MemoryObjectReceiveStream
from anyio.streams.memory import MemoryObjectSendStream
from mcp.server.sse import SseServerTransport
from mcp.shared.message import ServerMessageMetadata
from mcp.shared.message import SessionMessage

from redis import asyncio as aioredis
from sse_starlette import EventSourceResponse
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from trpc_sdk.abc import Node
from trpc_sdk.abc import SelectorOption
from trpc_sdk.abc import TrpcContext
from trpc_sdk.abc import get_message
from trpc_sdk.log import logger
from trpc_sdk.naming import get_selector

from ._constants import HOST
from ._constants import HTTP_HEADERS
from ._constants import OPTIONS
from ._constants import PORT
from ._constants import TARGET

_MCP_APP_META_KEY = "__mcp_app"


class TrpcSseServerTransport(SseServerTransport):
    """SSE transport with Redis pub/sub fallback for multi-worker TRPC servers."""

    _options_map: dict[str, Any] = {
        OPTIONS: {
            "disable_servicerouter": "disable_service_router",
        },
        "timeout": "socket_timeout",
    }

    def __init__(self,
                 endpoint: str,
                 redis_conf: dict | None = None,
                 mcp_app: Any = None,
                 security_settings: Any = None) -> None:
        super().__init__(endpoint, security_settings=security_settings)
        self._redis_conf = (redis_conf or {}).copy()
        self._redis_session: aioredis.Redis | None = None
        self._mcp_app = mcp_app

    @classmethod
    def _convert_key(cls, src: dict, filter_fields: dict) -> None:
        for old_key, new_key in filter_fields.items():
            if old_key not in src:
                continue
            if isinstance(new_key, dict):
                cls._convert_key(src[old_key], new_key)
            else:
                src[new_key] = src.pop(old_key)

    def _parse_dict_to_selector_option(self, ctx: TrpcContext) -> SelectorOption:
        options = SelectorOption()
        options.set_context(ctx)
        options_dict: dict = self._redis_conf.get(OPTIONS, {})
        if not options_dict:
            return options

        self._convert_key(self._redis_conf, self._options_map)
        fields = {"metadata"}
        for key, value in options_dict.items():
            if hasattr(options, key) or key in fields:
                method = getattr(options, f"set_{key}", None)
                if method:
                    method(value)
        self._redis_conf.pop(OPTIONS, None)
        return options

    async def _resolve_redis_target(self, ctx: TrpcContext) -> None:
        if not self._redis_conf or TARGET not in self._redis_conf or HOST in self._redis_conf:
            return
        if self._redis_session is not None:
            return

        target = self._redis_conf.pop(TARGET)
        result: ParseResult = urlparse(target)
        selector = get_selector(result.scheme)
        if selector is None:
            raise ValueError(f"No selector registered for redis target {target}")
        options = self._parse_dict_to_selector_option(ctx)
        node: Node = await selector.select(result.netloc, options)
        if node is None:
            raise ValueError(f"Failed to resolve redis target {target}")
        self._redis_conf[HOST] = node.ip
        self._redis_conf[PORT] = node.port

    async def _get_redis_session(self, ctx: TrpcContext) -> aioredis.Redis | None:
        if not self._redis_conf:
            return None
        if self._redis_session is None:
            await self._resolve_redis_target(ctx)
            self._convert_key(self._redis_conf, self._options_map)
            redis_conf = self._redis_conf.copy()
            redis_conf.pop(OPTIONS, None)
            self._redis_session = aioredis.Redis(**redis_conf)
        return self._redis_session

    @staticmethod
    def _serialize_scope(scope: Scope) -> dict[str, Any]:
        raw_path = scope.get("raw_path", b"")
        query_string = scope.get("query_string", b"")
        headers = scope.get(HTTP_HEADERS, [])
        return {
            "type":
            scope.get("type"),
            "http_version":
            scope.get("http_version"),
            "method":
            scope.get("method"),
            "scheme":
            scope.get("scheme"),
            "path":
            scope.get("path"),
            "raw_path":
            raw_path.decode("latin-1") if isinstance(raw_path, bytes) else raw_path,
            "query_string":
            query_string.decode("latin-1") if isinstance(query_string, bytes) else query_string,
            "root_path":
            scope.get("root_path", ""),
            "client":
            list(scope["client"]) if scope.get("client") else None,
            "server":
            list(scope["server"]) if scope.get("server") else None,
            HTTP_HEADERS: [(
                key.decode("latin-1") if isinstance(key, bytes) else key,
                value.decode("latin-1") if isinstance(value, bytes) else value,
            ) for key, value in headers],
        }

    @staticmethod
    def _deserialize_scope(scope_data: dict[str, Any]) -> Scope:
        raw_path = scope_data.get("raw_path", "")
        query_string = scope_data.get("query_string", "")
        scope_data[HTTP_HEADERS] = [(
            key.encode("latin-1") if isinstance(key, str) else key,
            value.encode("latin-1") if isinstance(value, str) else value,
        ) for key, value in scope_data.get(HTTP_HEADERS, [])]
        if isinstance(raw_path, str):
            scope_data["raw_path"] = raw_path.encode("latin-1")
        if isinstance(query_string, str):
            scope_data["query_string"] = query_string.encode("latin-1")
        if scope_data.get("client") is not None:
            scope_data["client"] = tuple(scope_data["client"])
        if scope_data.get("server") is not None:
            scope_data["server"] = tuple(scope_data["server"])
        return scope_data

    @staticmethod
    def _serialize_context(ctx: TrpcContext) -> dict[str, Any]:
        ctx_data = {
            key: value
            for key, value in (ctx.meta_data or {}).items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
        if ctx.deadline:
            ctx_data["deadline"] = ctx.deadline
        if ctx.timeout:
            ctx_data["timeout"] = ctx.timeout
        if ctx.remote_ip:
            ctx_data["remote_ip"] = ctx.remote_ip
        if ctx.recv_time:
            ctx_data["recv_time"] = ctx.recv_time
        if ctx.msg:
            ctx_data["callee_method"] = ctx.msg.callee_method
        return ctx_data

    def _deserialize_context(self, ctx_data: dict[str, Any]) -> TrpcContext:
        ctx = TrpcContext()
        if "deadline" in ctx_data:
            ctx.deadline = ctx_data.pop("deadline")
        if "timeout" in ctx_data:
            ctx.timeout = ctx_data.pop("timeout")
        if "remote_ip" in ctx_data:
            ctx.remote_ip = ctx_data.pop("remote_ip")
        if "recv_time" in ctx_data:
            ctx.recv_time = ctx_data.pop("recv_time")
        callee_method = ctx_data.pop("callee_method", None)
        ctx.meta_data.update(ctx_data)
        if self._mcp_app is not None:
            ctx.with_meta_data(_MCP_APP_META_KEY, self._mcp_app)
        if callee_method:
            get_message(ctx).set_callee_method(callee_method)
        return ctx

    def _make_data_to_redis(self, ctx: TrpcContext, scope: Scope, body: bytes) -> str:
        return json.dumps({
            "ctx": self._serialize_context(ctx),
            "scope": self._serialize_scope(scope),
            "body": body.decode("utf-8"),
        })

    def _get_data_from_redis(self, message: dict) -> tuple[TrpcContext, Scope, bytes]:
        data = json.loads(message["data"].decode("utf-8"))
        ctx = self._deserialize_context(data.get("ctx", {}))
        scope = self._deserialize_scope(data.get("scope", {}))
        scope["trpc_context"] = ctx
        return ctx, scope, data.get("body", "").encode("utf-8")

    async def try_subscribe(self, session_id: UUID, ctx: TrpcContext) -> None:
        redis_session = await self._get_redis_session(ctx)
        if redis_session is None:
            return

        pubsub = redis_session.pubsub()
        try:
            await pubsub.subscribe(session_id.hex)
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    await self.handle_post_message_by_session(session_id, message)
        except anyio.get_cancelled_exc_class():
            raise
        except Exception as exc:  # pylint: disable=broad-except
            logger.error(f"Redis SSE subscribe failed for session {session_id}: {exc}")
        finally:
            try:
                await pubsub.unsubscribe(session_id.hex)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error(f"Redis SSE unsubscribe failed for session {session_id}: {exc}")
            await pubsub.aclose()

    async def try_publish(self, session_id: UUID, ctx: TrpcContext, body: str) -> bool:
        try:
            redis_session = await self._get_redis_session(ctx)
            if redis_session is None:
                return False
            return bool(await redis_session.publish(session_id.hex, body))
        except Exception as exc:  # pylint: disable=broad-except
            logger.error(f"Redis SSE publish failed for session {session_id}: {exc}")
            return False

    async def handle_post_message_by_session(self, session_id: UUID, message: dict) -> None:
        ctx, scope, body = self._get_data_from_redis(message)
        request = Request(scope)
        session_id_param = request.query_params.get("session_id")
        if session_id_param is None:
            raise ValueError(f"[redis] session_id is missing for {session_id}")

        session_id = UUID(hex=session_id_param)
        writer = self._read_stream_writers.get(session_id)
        if writer is None:
            raise ValueError(f"[redis] Could not find session for ID: {session_id}")

        try:
            json_rpc_msg = types.JSONRPCMessage.model_validate_json(body)
        except ValidationError as err:
            await writer.send(err)
            return

        metadata = ServerMessageMetadata(request_context=request)
        await writer.send(SessionMessage(json_rpc_msg, metadata=metadata))

    @asynccontextmanager
    async def connect_sse(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            raise ValueError("connect_sse can only handle HTTP requests")

        request = Request(scope, receive)
        error_response = await self._security.validate_request(request, is_post=False)
        if error_response:
            await error_response(scope, receive, send)
            raise ValueError("Request validation failed")

        read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
        write_stream: MemoryObjectSendStream[SessionMessage]
        write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

        read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

        session_id = uuid4()
        self._read_stream_writers[session_id] = read_stream_writer
        root_path = scope.get("root_path", "")
        full_message_path_for_client = root_path.rstrip("/") + self._endpoint
        client_post_uri_data = f"{quote(full_message_path_for_client)}?session_id={session_id.hex}"
        sse_stream_writer, sse_stream_reader = anyio.create_memory_object_stream[dict[str, Any]](0)

        async def sse_writer() -> None:
            async with sse_stream_writer, write_stream_reader:
                await sse_stream_writer.send({"event": "endpoint", "data": client_post_uri_data})
                async for session_message in write_stream_reader:
                    await sse_stream_writer.send({
                        "event":
                        "message",
                        "data":
                        session_message.message.model_dump_json(by_alias=True, exclude_none=True),
                    })

        async def response_wrapper() -> None:
            await EventSourceResponse(content=sse_stream_reader, data_sender_callable=sse_writer)(scope, receive, send)
            await read_stream_writer.aclose()
            await write_stream_reader.aclose()
            logger.debug(f"Client session disconnected {session_id}")

        ctx = scope.get("trpc_context") or TrpcContext()
        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(response_wrapper)
                if self._redis_conf:
                    tg.start_soon(self.try_subscribe, session_id, ctx)
                try:
                    yield (read_stream, write_stream)
                finally:
                    tg.cancel_scope.cancel()
        finally:
            self._read_stream_writers.pop(session_id, None)

    async def handle_post_message(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        error_response = await self._security.validate_request(request, is_post=True)
        if error_response:
            return await error_response(scope, receive, send)

        session_id_param = request.query_params.get("session_id")
        if session_id_param is None:
            response = Response("session_id is required", status_code=HTTPStatus.BAD_REQUEST.value)
            return await response(scope, receive, send)

        try:
            session_id = UUID(hex=session_id_param)
        except ValueError:
            response = Response("Invalid session ID", status_code=HTTPStatus.BAD_REQUEST.value)
            return await response(scope, receive, send)

        writer = self._read_stream_writers.get(session_id)
        body = await request.body()
        if writer is None:
            ctx = scope.get("trpc_context") or TrpcContext()
            redis_data = self._make_data_to_redis(ctx, scope, body)
            if await self.try_publish(session_id, ctx, redis_data):
                response = Response(HTTPStatus.ACCEPTED.name, status_code=HTTPStatus.ACCEPTED.value)
                return await response(scope, receive, send)
            response = Response("Could not find session", status_code=HTTPStatus.NOT_FOUND.value)
            return await response(scope, receive, send)

        try:
            message = types.JSONRPCMessage.model_validate_json(body)
        except ValidationError as err:
            response = Response("Could not parse message", status_code=HTTPStatus.BAD_REQUEST.value)
            await response(scope, receive, send)
            await writer.send(err)
            return

        metadata = ServerMessageMetadata(request_context=request)
        response = Response(HTTPStatus.ACCEPTED.name, status_code=HTTPStatus.ACCEPTED.value)
        await response(scope, receive, send)
        await writer.send(SessionMessage(message, metadata=metadata))
