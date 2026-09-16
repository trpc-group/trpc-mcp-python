# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com
"""TRPC MCP Server Adapter Module."""

import base64
import inspect
import json
import re
import time
from contextvars import ContextVar
from functools import wraps
from typing import Any
from typing import Callable

import jsonschema
import mcp.types as types
from mcp.types import AnyFunction
from mcp.types import ToolAnnotations
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
from mcp.server.auth.middleware.bearer_auth import RequireAuthMiddleware
from mcp.server.fastmcp.server import FastMCP
from mcp.server.session import ServerSession
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount
from starlette.routing import Route
from starlette.types import ASGIApp
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from trpc.codec.message import get_message
from trpc.codec.serialization import SerializationType
from trpc.config import config
from trpc.context import TrpcContext
from trpc.http import defines as http_defines
from trpc.http import pop_http_rsp_header
from trpc.log import logger
from mcp.server.lowlevel.server import request_ctx
from trpc.trpc_abc.transport import BaseServerTransportOption
from trpc.trpcpb import RequestProtocol
from trpc.trpcpb import TRPC_DYEING_MESSAGE

from ._compat import Annotations
from ._compat import Icon
from ._sse_transport import TrpcSseServerTransport
from .tools import ToolFilterParams
from .tools import run_filters

SERVER_NAME: str = "__server_name"
PROTOCOL_NAME: str = "__protocol_name"
MCP_APP: str = "__mcp_app"
_TRPC_CONTEXT: ContextVar[TrpcContext | None] = ContextVar("trpc_mcp_context", default=None)


def _forward_supported_kwargs(func, **kwargs) -> dict[str, Any]:
    """Keep only kwargs the installed callable actually accepts.

    Newer MCP features (e.g. ``icons`` since 1.13, ``meta`` since 1.16, resource
    ``annotations`` since 1.15) add keyword arguments to FastMCP/ClientSession.
    Passing such a keyword to an older SDK raises ``TypeError`` even when the
    value is ``None``. To stay compatible across the whole supported mcp range we
    drop unsupported keywords; if a keyword is unsupported but was *explicitly
    set* (non-None) we warn so the feature loss is visible rather than silent.
    """
    params = inspect.signature(func).parameters
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return dict(kwargs)
    supported: dict[str, Any] = {}
    for key, value in kwargs.items():
        if key in params:
            supported[key] = value
        elif value is not None:
            logger.warning(f"installed mcp does not support '{key}' on {getattr(func, '__qualname__', func)}; "
                           f"ignoring it - upgrade mcp to use this feature")
    return supported


def get_trpc_context() -> TrpcContext | None:
    """Get current TRPC context for MCP handlers."""
    trpc_context = _TRPC_CONTEXT.get()
    if trpc_context is not None:
        return trpc_context

    try:
        request = request_ctx.get().request
    except LookupError:
        return None

    if isinstance(request, TrpcContext):
        return request

    scope = getattr(request, "scope", None)
    if isinstance(scope, dict):
        return scope.get("trpc_context")
    return None


def _remove_first_parameter_signature(fn: Callable[..., Any]) -> inspect.Signature:
    signature = inspect.signature(fn)
    parameters = list(signature.parameters.values())
    if parameters:
        parameters = parameters[1:]
    return signature.replace(parameters=parameters)


def _wrap_trpc_handler(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Hide the first TRPC ctx parameter from FastMCP and inject it at runtime."""
    original_signature = inspect.signature(fn)
    has_trpc_ctx = bool(original_signature.parameters)
    public_signature = _remove_first_parameter_signature(fn)

    if inspect.iscoroutinefunction(fn):

        @wraps(fn)
        async def async_wrapper(*args, **kwargs):
            if has_trpc_ctx:
                return await fn(get_trpc_context(), *args, **kwargs)
            return await fn(*args, **kwargs)

        async_wrapper.__signature__ = public_signature  # type: ignore[attr-defined]
        return async_wrapper

    @wraps(fn)
    def sync_wrapper(*args, **kwargs):
        if has_trpc_ctx:
            return fn(get_trpc_context(), *args, **kwargs)
        return fn(*args, **kwargs)

    sync_wrapper.__signature__ = public_signature  # type: ignore[attr-defined]
    return sync_wrapper


class _TrpcFilterASGIApp:
    """ASGI wrapper that runs TRPC server filters before MCP handles requests."""

    def __init__(self, app: ASGIApp, opts_map: dict[int, BaseServerTransportOption], mcp_app: "TrpcMcpServer") -> None:
        self._app = app
        self._opts_map = opts_map
        self._default_opts = next(iter(opts_map.values()))
        self._mcp_app = mcp_app

    def _get_opts(self, request: Request) -> BaseServerTransportOption:
        server = request.scope.get("server") or ()
        if len(server) >= 2:
            opts = self._opts_map.get(server[1])
            if opts is not None:
                return opts
        return self._default_opts

    def _make_trpc_context(self, request: Request) -> TrpcContext:
        opts = self._get_opts(request)
        trpc_context = TrpcContext()
        trpc_context.timeout = opts.idle_timeout
        trpc_context.recv_time = int(time.time() * 1000)
        trpc_context.with_meta_data(http_defines.HTTP_REQ_KEY, request)
        trpc_context.with_meta_data(http_defines.HTTP_RSP_KEY, Response())
        trpc_context.with_meta_data(http_defines.LOCAL_ADDR, f"{opts.address}:{opts.port}")
        trpc_context.with_meta_data(http_defines.TRANS_INFO_BASE64_KEY, config.global_config_obj.server.encode_base64)
        trpc_context.with_meta_data(SERVER_NAME, opts.service_name)
        trpc_context.with_meta_data(PROTOCOL_NAME, opts.service.opt.protocol)
        trpc_context.with_meta_data(MCP_APP, self._mcp_app)
        if request.client:
            trpc_context.remote_ip = request.client.host

        message = get_message(trpc_context)
        self._decode_trpc_req_header(message, request)
        request.scope["trpc_context"] = trpc_context
        return trpc_context

    @staticmethod
    def _decode_trpc_req_header(message, request: Request) -> None:
        """Decode TRPC headers from a Starlette request without consuming the body."""
        trpc_req = RequestProtocol()
        headers = request.headers

        trpc_req.version = int(headers.get(http_defines.HTTP_TRPC_HEADER.trpc_version, trpc_req.version))
        trpc_req.call_type = int(headers.get(http_defines.HTTP_TRPC_HEADER.trpc_call_type, trpc_req.call_type))
        trpc_req.message_type = int(headers.get(http_defines.HTTP_TRPC_HEADER.trpc_message_type, trpc_req.message_type))
        trpc_req.request_id = int(headers.get(http_defines.HTTP_TRPC_HEADER.trpc_request_id, trpc_req.request_id))
        message.set_request_id(trpc_req.request_id)

        trpc_req.timeout = int(headers.get(http_defines.HTTP_TRPC_HEADER.trpc_timeout, trpc_req.timeout))
        message.set_timeout(trpc_req.timeout)

        caller_method = headers.get(http_defines.HTTP_TRPC_HEADER.trpc_caller_method)
        if caller_method:
            message.set_caller_method(caller_method)

        caller = headers.get(http_defines.HTTP_TRPC_HEADER.trpc_caller, None)
        if caller:
            trpc_req.caller = caller.encode("utf-8")
            message.set_caller_service_name(caller)

        url_path = request.url.path
        trpc_req.func = url_path.encode("utf-8")
        message.set_server_rpc_name(url_path)
        path = url_path.split("/")
        callee = path[1] if len(path) > 1 else None

        trpc_callee = headers.get(http_defines.HTTP_TRPC_HEADER.trpc_callee, callee)
        if trpc_callee:
            trpc_req.callee = trpc_callee.encode("utf-8")
            message.set_callee_service_name(trpc_callee)

        message.set_dyeing((trpc_req.message_type & TRPC_DYEING_MESSAGE) != 0)

        trans_info = headers.get(http_defines.HTTP_TRPC_HEADER.trpc_trans_info, None)
        is_base64 = message.context.get_meta_data(http_defines.TRANS_INFO_BASE64_KEY, False)
        if trans_info:
            trans_info = json.loads(trans_info)
            if is_base64:
                for key, value in trans_info.items():
                    value = base64.b64decode(value)
                    try:
                        trans_info[key] = value.decode()
                    except Exception:  # pylint: disable=broad-except
                        trans_info[key] = value
            message.server_meta_data.update(trans_info)
            for key, value in trans_info.items():
                if not isinstance(value, bytes):
                    value = str(value).encode()
                trpc_req.trans_info[key] = value

        if request.method == "GET":
            message.set_serialization_type(SerializationType.Form)
            trpc_req.content_type = SerializationType.Form
        else:
            message.set_serialization_type(SerializationType.JSON)
            content_type = request.headers.get("Content-Type", "")
            serialization_type = http_defines.find_serialization_type(content_type, SerializationType.JSON)
            message.set_serialization_type(serialization_type)
            trpc_req.content_type = serialization_type

        message.set_server_req_head(trpc_req)

    @staticmethod
    def _merge_trpc_headers(ctx: TrpcContext, message: dict[str, Any]) -> dict[str, Any]:
        trpc_headers = pop_http_rsp_header(ctx)
        if not trpc_headers:
            return message

        raw_headers = list(message.get("headers") or [])
        existing = {key.lower() for key, _ in raw_headers}
        for key, value in trpc_headers.items():
            key_bytes = str(key).lower().encode("latin-1")
            if key_bytes in existing:
                continue
            raw_headers.append((key_bytes, str(value).encode("latin-1")))
        message["headers"] = raw_headers
        return message

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request = Request(scope, receive)
        trpc_context = self._make_trpc_context(request)
        response_started = False

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                message = self._merge_trpc_headers(trpc_context, message)
            await send(message)

        async def mcp_handle(ctx: TrpcContext, _: Request) -> None:
            token = _TRPC_CONTEXT.set(ctx)
            try:
                await self._app(scope, receive, send_wrapper)
            finally:
                _TRPC_CONTEXT.reset(token)

        opts = self._get_opts(request)
        result = await opts.service.http_handle(trpc_context, mcp_handle)
        if result is not None and not response_started:
            headers = pop_http_rsp_header(trpc_context)
            response = Response(content=result, headers=headers)
            await response(scope, receive, send)


class TrpcMcpServer(FastMCP):
    """TrpcMcpServer subclass that routes HTTP requests through TRPC filters."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._trpc_opts_map: dict[int, BaseServerTransportOption] = {}
        self._tool_services: dict[str, set[str]] = {}
        self._resource_services: dict[str, set[str]] = {}
        self._prompt_services: dict[str, set[str]] = {}
        self._sse_redis_conf: dict | None = None

    def set_trpc_options(self, opts: BaseServerTransportOption) -> None:
        """Attach TRPC transport options used by the filter wrapper."""
        self._trpc_opts_map = {opts.port: opts}

    def set_trpc_options_map(self, opts_list: list[BaseServerTransportOption]) -> None:
        """Attach all TRPC transport options served by this MCP app."""
        self._trpc_opts_map = {opts.port: opts for opts in opts_list}

    def set_service_bindings(self, tool_services: dict[str, set[str]], resource_services: dict[str, set[str]],
                             prompt_services: dict[str, set[str]]) -> None:
        """Attach service visibility maps for MCP capabilities."""
        self._tool_services = tool_services
        self._resource_services = resource_services
        self._prompt_services = prompt_services

    def set_sse_redis_config(self, redis_conf: dict | None) -> None:
        """Attach Redis configuration used by distributed SSE sessions."""
        self._sse_redis_conf = redis_conf or None

    @staticmethod
    def _get_current_service_name() -> str | None:
        ctx = get_trpc_context()
        if ctx is None:
            return None
        return ctx.get_meta_data(SERVER_NAME)

    @staticmethod
    def _is_uri_template_match(template: str, uri: str) -> bool:
        pattern = re.escape(template)
        pattern = re.sub(r"\\\{[^/]+\\\}", r"[^/]+", pattern)
        return re.fullmatch(pattern, uri) is not None

    def _is_allowed(self, name: str, bindings: dict[str, set[str]]) -> bool:
        service_name = self._get_current_service_name()
        if service_name is None:
            return True
        services = bindings.get(name)
        if services is None:
            return not bindings
        return service_name in services

    def _is_resource_allowed(self, uri: str) -> bool:
        service_name = self._get_current_service_name()
        if service_name is None:
            return True
        for template, services in self._resource_services.items():
            if (template == uri or self._is_uri_template_match(template, uri)) and service_name in services:
                return True
        return False

    def _wrap_filter_app(self, app):
        if not self._trpc_opts_map:
            logger.warning("TRPC MCP server runs without TRPC filter options")
            return app
        return _TrpcFilterASGIApp(app, self._trpc_opts_map, self)

    def _setup_handlers(self) -> None:
        super()._setup_handlers()

        async def call_tool_handler(req: types.CallToolRequest):
            try:
                tool_name = req.params.name
                arguments = req.params.arguments or {}
                tool = await self._mcp_server._get_cached_tool_definition(tool_name)  # pylint: disable=protected-access
                results = await self.call_tool(tool_name, arguments)

                if isinstance(results, types.CallToolResult):
                    return types.ServerResult(results)

                maybe_structured_content = None
                if isinstance(results, tuple) and len(results) == 2:
                    unstructured_content, maybe_structured_content = results
                elif isinstance(results, dict):
                    maybe_structured_content = results
                    unstructured_content = [types.TextContent(type="text", text=json.dumps(results, indent=2))]
                elif hasattr(results, "__iter__"):
                    unstructured_content = results
                else:
                    return self._mcp_server._make_error_result(  # pylint: disable=protected-access
                        f"Unexpected return type from tool: {type(results).__name__}")

                if tool and tool.outputSchema is not None:
                    if maybe_structured_content is None:
                        return self._mcp_server._make_error_result(  # pylint: disable=protected-access
                            "Output validation error: outputSchema defined but no structured output returned")
                    try:
                        jsonschema.validate(instance=maybe_structured_content, schema=tool.outputSchema)
                    except jsonschema.ValidationError as err:
                        return self._mcp_server._make_error_result(  # pylint: disable=protected-access
                            f"Output validation error: {err.message}")

                return types.ServerResult(
                    types.CallToolResult(
                        content=list(unstructured_content),
                        structuredContent=maybe_structured_content,
                        isError=False,
                    ))
            except Exception as err:  # pylint: disable=broad-except
                return self._mcp_server._make_error_result(str(err))  # pylint: disable=protected-access

        self._mcp_server.request_handlers[types.CallToolRequest] = call_tool_handler

    def sse_app(self, mount_path: str | None = None):
        """Return SSE app wrapped by TRPC server filters."""
        if not self._sse_redis_conf:
            return self._wrap_filter_app(super().sse_app(mount_path))

        if mount_path is not None:
            self.settings.mount_path = mount_path
        normalized_message_endpoint = self._normalize_path(self.settings.mount_path, self.settings.message_path)
        sse = TrpcSseServerTransport(
            normalized_message_endpoint,
            redis_conf=self._sse_redis_conf,
            mcp_app=self,
            security_settings=self.settings.transport_security,
        )

        async def handle_sse(scope: Scope, receive: Receive, send: Send):
            async with sse.connect_sse(scope, receive, send) as streams:
                await self._mcp_server.run(
                    streams[0],
                    streams[1],
                    self._mcp_server.create_initialization_options(),
                )
            return Response()

        routes: list[Route | Mount] = []
        middleware: list[Middleware] = []
        required_scopes = []

        if self.settings.auth:
            required_scopes = self.settings.auth.required_scopes or []
            if self._token_verifier:
                middleware = [
                    Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(self._token_verifier)),
                    Middleware(AuthContextMiddleware),
                ]
            if self._auth_server_provider:
                from mcp.server.auth.routes import create_auth_routes

                routes.extend(
                    create_auth_routes(
                        provider=self._auth_server_provider,
                        issuer_url=self.settings.auth.issuer_url,
                        service_documentation_url=self.settings.auth.service_documentation_url,
                        client_registration_options=self.settings.auth.client_registration_options,
                        revocation_options=self.settings.auth.revocation_options,
                    ))

        if self._token_verifier:
            resource_metadata_url = None
            if self.settings.auth and self.settings.auth.resource_server_url:
                from pydantic import AnyHttpUrl

                resource_metadata_url = AnyHttpUrl(
                    str(self.settings.auth.resource_server_url).rstrip("/") + "/.well-known/oauth-protected-resource")
            routes.append(
                Route(
                    self.settings.sse_path,
                    endpoint=RequireAuthMiddleware(handle_sse, required_scopes, resource_metadata_url),
                    methods=["GET"],
                ))
            routes.append(
                Mount(
                    self.settings.message_path,
                    app=RequireAuthMiddleware(sse.handle_post_message, required_scopes, resource_metadata_url),
                ))
        else:

            async def sse_endpoint(request: Request) -> Response:
                return await handle_sse(request.scope, request.receive, request._send)  # type: ignore[attr-defined]

            routes.append(Route(self.settings.sse_path, endpoint=sse_endpoint, methods=["GET"]))
            routes.append(Mount(self.settings.message_path, app=sse.handle_post_message))

        if self.settings.auth and self.settings.auth.resource_server_url:
            from mcp.server.auth.routes import create_protected_resource_routes

            routes.extend(
                create_protected_resource_routes(
                    resource_url=self.settings.auth.resource_server_url,
                    authorization_servers=[self.settings.auth.issuer_url],
                    scopes_supported=self.settings.auth.required_scopes,
                ))

        routes.extend(self._custom_starlette_routes)
        return self._wrap_filter_app(Starlette(debug=self.settings.debug, routes=routes, middleware=middleware))

    def streamable_http_app(self):
        """Return Streamable HTTP app wrapped by TRPC server filters.

        We reuse FastMCP's default ``StreamableHTTPSessionManager`` as-is and only
        wrap the resulting ASGI app with the TRPC server filters. Per-session
        crash isolation (one disconnected/crashed session must not tear down the
        shared task group) is handled by the official manager since mcp>=1.11.0
        (PR #841); see ``docs/troubleshooting.md`` for the full history.
        """
        return self._wrap_filter_app(super().streamable_http_app())

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        """Call a tool while preserving explicit CallToolResult metadata."""
        if not self._is_allowed(name, self._tool_services):
            raise ValueError(f"Unknown tool: {name}")
        context = self.get_context()
        tool = self._tool_manager.get_tool(name)
        if not tool:
            return await super().call_tool(name, arguments)

        trpc_ctx = get_trpc_context()
        tool_params = ToolFilterParams(name=name, arguments=arguments)

        async def call_tool():
            return await tool.run(tool_params.arguments, context=context, convert_result=False)

        result = await run_filters(trpc_ctx, tool_params, call_tool)
        if isinstance(result, types.CallToolResult):
            return result
        return tool.fn_metadata.convert_result(result)

    async def list_tools(self) -> list[types.Tool]:
        """List tools visible to the current TRPC service."""
        tools = await super().list_tools()
        return [tool for tool in tools if self._is_allowed(tool.name, self._tool_services)]

    async def list_resources(self):
        """List resources visible to the current TRPC service."""
        resources = await super().list_resources()
        return [resource for resource in resources if self._is_resource_allowed(str(resource.uri))]

    async def list_resource_templates(self):
        """List resource templates visible to the current TRPC service."""
        templates = await super().list_resource_templates()
        return [template for template in templates if self._is_allowed(template.uriTemplate, self._resource_services)]

    async def read_resource(self, uri):
        """Read a resource only when it is visible to the current TRPC service."""
        if not self._is_resource_allowed(str(uri)):
            raise ValueError(f"Unknown resource: {uri}")
        return await super().read_resource(uri)

    async def list_prompts(self):
        """List prompts visible to the current TRPC service."""
        prompts = await super().list_prompts()
        return [prompt for prompt in prompts if self._is_allowed(prompt.name, self._prompt_services)]

    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None):
        """Get a prompt only when it is visible to the current TRPC service."""
        if not self._is_allowed(name, self._prompt_services):
            raise ValueError(f"Unknown prompt: {name}")
        return await super().get_prompt(name, arguments)

    def add_tool(
        self,
        fn: AnyFunction,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: dict[str, Any] | None = None,
        structured_output: bool | None = None,
    ) -> None:
        """Add a tool whose first user parameter is TRPC context."""
        base = super().add_tool
        return base(
            _wrap_trpc_handler(fn),
            **_forward_supported_kwargs(
                base,
                name=name,
                title=title,
                description=description,
                annotations=annotations,
                icons=icons,
                meta=meta,
                structured_output=structured_output,
            ),
        )

    def tool(
        self,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: dict[str, Any] | None = None,
        structured_output: bool | None = None,
    ):
        """Register a tool while keeping the public TRPC ctx-first convention."""
        if callable(name):
            raise TypeError("The @tool decorator was used incorrectly. Did you forget to call it?")

        def decorator(fn: AnyFunction) -> AnyFunction:
            self.add_tool(
                fn,
                name=name,
                title=title,
                description=description,
                annotations=annotations,
                icons=icons,
                meta=meta,
                structured_output=structured_output,
            )
            return fn

        return decorator

    def resource(
        self,
        uri: str,
        *,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
        icons: list[Icon] | None = None,
        annotations: Annotations | None = None,
        meta: dict[str, Any] | None = None,
    ):
        """Register a resource while keeping the public TRPC ctx-first convention."""
        if callable(uri):
            raise TypeError("The @resource decorator was used incorrectly. Did you forget to call it?")

        def decorator(fn: AnyFunction) -> AnyFunction:
            base = super(TrpcMcpServer, self).resource
            base(
                uri,
                **_forward_supported_kwargs(
                    base,
                    name=name,
                    title=title,
                    description=description,
                    mime_type=mime_type,
                    icons=icons,
                    annotations=annotations,
                    meta=meta,
                ),
            )(_wrap_trpc_handler(fn))
            return fn

        return decorator

    def prompt(
        self,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        icons: list[Icon] | None = None,
    ):
        """Register a prompt while keeping the public TRPC ctx-first convention."""
        if callable(name):
            raise TypeError("The @prompt decorator was used incorrectly. Did you forget to call it?")

        def decorator(fn: AnyFunction) -> AnyFunction:
            base = super(TrpcMcpServer, self).prompt
            base(**_forward_supported_kwargs(
                base,
                name=name,
                title=title,
                description=description,
                icons=icons,
            ), )(_wrap_trpc_handler(fn))
            return fn

        return decorator

    def get_server_session(self) -> ServerSession:
        """Get the current server session.

        Returns:
            TrpcMcpServerSession: The active server session

        Raises:
            LookupError: If called outside of a request context
        """
        return self.get_context().session
