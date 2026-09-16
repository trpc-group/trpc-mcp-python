# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com
"""httpx transport that routes MCP SDK requests through the trpc client flow.

The official MCP SDK client transports (``sse_client`` / ``streamablehttp_client``)
program against ``httpx`` and expose an ``httpx_client_factory`` injection point.
This module provides a custom ``httpx.AsyncBaseTransport`` so that the MCP SDK
transports and session stay completely unmodified, while every HTTP round trip is
executed by trpc-python's client (selector / Polaris addressing, filters, options,
codec). This keeps the trpc client flow intact and uses the MCP SDK at the
transport layer.
"""

import contextlib
from typing import Any

import httpx
from trpc.context import TrpcContext
from trpc.http import defines as http_defines
from trpc.http.client import Client as TrpcHttpClient
from trpc.log import logger

from mcp.client import streamable_http as _mcp_streamable_http

from .utils import get_http_header_from_context
from .utils import get_http_kwargs_from_context

# Headers that aiohttp recomputes; forwarding them from httpx would conflict.
_DROP_REQUEST_HEADERS = {"host", "content-length", "connection", "transfer-encoding"}


class _TrpcResponseByteStream(httpx.AsyncByteStream):
    """Adapt a trpc streaming response into an httpx async byte stream."""

    def __init__(self, rsp: Any) -> None:
        self._rsp = rsp

    async def __aiter__(self):
        async for chunk in self._rsp.stream_data():
            yield chunk

    async def aclose(self) -> None:
        try:
            self._rsp.release()
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug(f"release trpc mcp response failed: {exc}")


class TrpcHttpxTransport(httpx.AsyncBaseTransport):
    """Bridge httpx requests issued by the MCP SDK to the trpc HTTP client.

    Routing target/scheme are fixed for the lifetime of one MCP connection
    (resolved from the proxy host), while the request path/query/method/body come
    from the MCP SDK. trpc re-runs node selection on every request, so Polaris
    dynamic addressing still works per call.
    """

    def __init__(self,
                 routing_scheme: str,
                 routing_netloc: str,
                 ctx: TrpcContext,
                 options: list,
                 client_name: str = "") -> None:
        self._scheme = routing_scheme
        self._netloc = routing_netloc
        self._ctx = ctx
        self._options = options or []
        self._client = TrpcHttpClient(client_name)

    def _build_trpc_url(self, request: httpx.Request) -> str:
        # raw_path carries both path and query as bytes.
        path = request.url.raw_path.decode("ascii")
        return f"{self._scheme}://{self._netloc}{path}"

    def _build_headers(self, request: httpx.Request) -> dict:
        headers = {key: value for key, value in request.headers.items() if key.lower() not in _DROP_REQUEST_HEADERS}
        for key, value in get_http_header_from_context(self._ctx).items():
            headers.setdefault(key, value)
        return headers

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        trpc_url = self._build_trpc_url(request)
        headers = self._build_headers(request)
        kwargs = dict(get_http_kwargs_from_context(self._ctx))
        kwargs[http_defines.HTTP_ARG_STREAM_KEY] = True
        body = request.content or None

        rsp = await self._client.request(
            self._ctx,
            request.method,
            trpc_url,
            self._options,
            data=body,
            headers=headers,
            **kwargs,
        )
        resp_headers = [(key, value) for key, value in rsp.header.items()]
        return httpx.Response(
            status_code=rsp.status,
            headers=resp_headers,
            stream=_TrpcResponseByteStream(rsp),
            request=request,
        )


def build_httpx_client_factory(routing_scheme: str,
                               routing_netloc: str,
                               ctx: TrpcContext,
                               options: list,
                               client_name: str = ""):
    """Build an ``McpHttpClientFactory`` backed by :class:`TrpcHttpxTransport`."""

    def factory(headers: dict | None = None, timeout: Any = None, auth: Any = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=TrpcHttpxTransport(routing_scheme, routing_netloc, ctx, options, client_name),
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=True,
        )

    return factory


@contextlib.asynccontextmanager
async def open_streamable_http(url: str, factory):
    """Open a streamable-http client transport, adapting to the installed mcp.

    The official SDK renamed ``streamablehttp_client`` (factory-based, now
    ``@deprecated``) to ``streamable_http_client`` (which takes a pre-built
    ``httpx.AsyncClient`` instead of a factory). We prefer the new API when it is
    available and fall back to the deprecated one on older mcp, so this works
    across the whole supported mcp range without emitting deprecation warnings on
    new versions.

    Yields the same ``(read_stream, write_stream, get_session_id)`` tuple in both
    cases.
    """
    new_client = getattr(_mcp_streamable_http, "streamable_http_client", None)
    if new_client is not None:
        # New API: pass an httpx.AsyncClient instance. It does NOT close a
        # caller-provided client, so we manage its lifecycle here. Keep the client
        # open as the OUTER context so the transport can still send the session
        # DELETE on exit (terminate_on_close) before the client is closed.
        http_client = factory()
        async with http_client:
            async with new_client(url, http_client=http_client) as streams:
                yield streams
    else:
        async with _mcp_streamable_http.streamablehttp_client(url, httpx_client_factory=factory) as streams:
            yield streams
