# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""
TRPC MCP Client Module

This module implements the client-side functionality for TRPC MCP (Microservice Control Protocol).
It provides proxy class for interacting with MCP servers, including tool execution and resource management.
"""

import asyncio
import inspect
from contextlib import AsyncExitStack
from typing import Any, Callable, Generic, TypeVar
from urllib.parse import urlparse
from urllib.parse import urlunparse

import anyio
from pydantic.networks import AnyUrl
from trpc_sdk.abc import TrpcContext
from trpc_sdk.client import Options
from trpc_sdk.config import TrpcConfig
from trpc_sdk.log import logger

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.types import Prompt
from mcp.types import Resource
from mcp.types import ResourceTemplate
from mcp.types import Tool

from ._constants import MCP_SSE
from ._constants import MCP_STREAMABLE_HTTP
from ._constants import TRPC_MCP_PROTOCOL
from ._config import get_mcp_client_config
from ._httpx_transport import build_httpx_client_factory
from ._httpx_transport import open_streamable_http
from .utils import make_url
from .utils import normalize_path

T = TypeVar('T')

# MCP endpoint paths used by the example/default servers.
_SSE_ENDPOINT = "sse"
_STREAMABLE_HTTP_ENDPOINT = "mcp"
_DEFAULT_TIMEOUT_MS = 300 * 1000


class _Wrapper(Generic[T]):

    def __init__(self, info: T) -> None:
        self.info = info

    def __getattr__(self, name: str) -> Any:
        if hasattr(self.info, name):
            return getattr(self.info, name)
        new_name = self._snake_to_lower_camel(name)
        if hasattr(self.info, new_name):
            return getattr(self.info, new_name)
        return getattr(self.info, name)

    def _snake_to_lower_camel(self, name: str) -> str:
        components = name.split('_')
        return components[0] + ''.join(x.title() for x in components[1:])


ToolInfo = _Wrapper[Tool]
ResourceInfo = _Wrapper[Resource]
ResourceTemplateInfo = _Wrapper[ResourceTemplate]
PromptInfo = _Wrapper[Prompt]


class McpProxy:
    """Proxy class for managing MCP server connections and operations.

    Attributes:
        name: Name identifier for the proxy
        base_url: Base URL for server connections
        _cleanup_lock: Async lock for cleanup operations
        stdio_context: Context for stdio communication
        session: Active client session
        exit_stack: Async context manager stack
    """

    def __init__(self,
                 name: str,
                 host: str | None = None,
                 options: list | None = None,
                 base_url: str | None = None,
                 transport: str | None = None) -> None:
        """Initialize the MCP proxy.

        ``host``/``base_url``/``transport`` are optional: when not provided they
        are resolved from configuration at :meth:`initialize` time, so callers can
        rely on config only. Precedence is: explicit argument > config > default.

        - ``host``: explicit ``host`` -> ``client.service[name].target`` -> ``name``
        - ``transport``: explicit -> ``plugins.mcp.client.transport`` -> ``sse``
        - ``base_url``: explicit -> ``plugins.mcp.client.base_url`` -> ``""``

        Args:
            name: Name identifier for the proxy (also the trpc callee service name)
            host: Server host address (optional, falls back to config)
            options: Connection options (optional)
            base_url: Base URL path (optional, falls back to config)
            transport: Transport name (optional, falls back to config)
        """
        self.name: str = name
        self.__host = host
        self.__options = options
        self.__transport = transport
        self.__base_url = base_url
        # Finalized during initialize() with config fallback applied.
        self.base_url: str = base_url or ""
        self._cleanup_lock: asyncio.Lock = asyncio.Lock()
        self.session: ClientSession | None = None
        self.exit_stack: AsyncExitStack = AsyncExitStack()

    def _session(self) -> ClientSession:
        if not self.session:
            raise RuntimeError(f"Server {self.name} not initialized")
        return self.session

    def _host_from_config(self) -> str:
        """Return the configured trpc ``client.service`` target (scheme kept).

        The scheme selects the trpc selector, so it must be preserved:
        ``ip://127.0.0.1:8008`` (direct) or a custom selector such as
        ``test://service``. :meth:`_resolve_urls` keeps
        this scheme instead of re-guessing it.
        """
        return getattr(TrpcConfig.client_service_config(self.name), "target", "") or ""

    def _resolve_runtime(self, host: str | None, transport: str | None) -> tuple[str, str, str]:
        """Resolve host/transport/base_url with precedence: arg > config > default."""
        client_conf = get_mcp_client_config()

        host = host or self.__host or self._host_from_config() or self.name
        transport = transport or self.__transport or client_conf.transport or MCP_SSE

        if self.__base_url is not None:
            base_url = self.__base_url
        elif client_conf.base_url:
            base_url = client_conf.base_url
        else:
            base_url = ""

        return host, transport, base_url

    def __get_options(self, options: list | None = None) -> list:
        """Merge proxy-level and per-call options, adding a default timeout.

        Note: routing/options are connection-scoped because the official MCP SDK
        transports do not carry per-message routing. Options resolved here at
        ``initialize`` drive the whole MCP session.
        """
        merged = list(options or [])
        merged.extend(self.__options or [])
        if not merged:
            merged.append(Options().set_timeout(_DEFAULT_TIMEOUT_MS))
        # McpProxy is always an MCP client, so force the dedicated ``http_mcp``
        # protocol regardless of what the client.service declares (legacy entries
        # use ``protocol: http``). The trpc HTTP client puts
        # ``Options().set_protocol('http')`` at the front of its option list;
        # appending here makes the MCP protocol win (options apply in order, last
        # write wins) and selects the MCP-aware codec/transport without affecting
        # plain HTTP business clients that keep using the framework ``http`` codec.
        merged.append(Options().set_protocol(TRPC_MCP_PROTOCOL))
        return merged

    async def _call_with_context(
        self,
        ctx: TrpcContext,
        options: list | None,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Invoke an official MCP SDK session method.

        ``ctx``/``options`` are accepted for API compatibility; transport routing
        is connection-scoped (resolved at :meth:`initialize`).
        """
        return await func(*args, **kwargs)

    async def initialize(self,
                         ctx: TrpcContext,
                         transport: str | None = None,
                         options: list | None = None,
                         host: str | None = None,
                         session_args: dict | None = None) -> None:
        """Initialize the server connection.
        :param session_args:
            {
                'read_timeout_seconds': timedelta(seconds=390),
                'sampling_callback':  SamplingFnT,
                'list_roots_callback': ListRootsFnT,
                'logging_callback': LoggingFnT,
                'message_handler': TrpcMessageHandlerFnT,
            }
        """
        try:
            host, transport, self.base_url = self._resolve_runtime(host, transport)
            options = self.__get_options(options)

            endpoint = _STREAMABLE_HTTP_ENDPOINT if transport == MCP_STREAMABLE_HTTP else _SSE_ENDPOINT
            display_url, routing_scheme, routing_netloc = self._resolve_urls(host, endpoint)
            factory = build_httpx_client_factory(routing_scheme, routing_netloc, ctx, options, self.name)

            if transport == MCP_STREAMABLE_HTTP:
                read_stream, write_stream, _ = await self.exit_stack.enter_async_context(
                    open_streamable_http(display_url, factory))
            else:
                # default transport is MCP_SSE because it's compatible
                read_stream, write_stream = await self.exit_stack.enter_async_context(
                    sse_client(display_url, httpx_client_factory=factory))

            session_args = session_args or {}
            session_args["read_stream"] = read_stream
            session_args["write_stream"] = write_stream
            session = await self.exit_stack.enter_async_context(ClientSession(**session_args))
            await session.initialize()
            self.session = session
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Error initializing server {self.name}: {e}")
            await self.cleanup()
            raise

    def _resolve_urls(self, host: str, endpoint: str) -> tuple[str, str, str]:
        """Resolve the MCP SDK display URL and the trpc routing scheme/netloc.

        ``make_url`` yields ``http://host/<ep>`` for hosts without a scheme. The
        MCP SDK requires an http(s) URL (used only for its API surface and origin
        checks since our custom httpx transport intercepts the request), while the
        trpc routing scheme is carried separately so selector addressing still works.
        """
        parsed_host = urlparse(host)
        if parsed_host.scheme and parsed_host.netloc:
            # Host already carries an explicit routing scheme (from the configured
            # client.service target). Preserve it so ip:// (direct) and custom
            # selectors like test:// keep working; make_url would otherwise
            # fall back to http and silently drop a custom selector scheme.
            trpc_url = f"{parsed_host.scheme}://{parsed_host.netloc}{normalize_path(self.base_url, endpoint)}"
        else:
            trpc_url = make_url(host, self.base_url, endpoint)
        parsed = urlparse(trpc_url)
        display_url = urlunparse(("http", parsed.netloc, parsed.path, "", "", ""))
        return display_url, parsed.scheme, parsed.netloc

    async def list_tools(self, ctx: TrpcContext, options: list | None = None) -> list[ToolInfo]:
        """List available tools from the server.

        Returns:
            A list of available tools.

        Raises:
            RuntimeError: If the server is not initialized.
        """
        tools_response = await self._call_with_context(ctx, options, self._session().list_tools)
        return [ToolInfo(tool) for tool in tools_response.tools]

    async def list_resources(self, ctx: TrpcContext, options: list | None = None) -> list[ResourceInfo]:
        """List available resources from the server.

        Returns:
            A list of available resources.

        Raises:
            RuntimeError: If the server is not initialized.
        """
        resources_response = await self._call_with_context(ctx, options, self._session().list_resources)
        return [ResourceInfo(resources) for resources in resources_response.resources]

    async def list_resource_templates(self,
                                      ctx: TrpcContext,
                                      options: list | None = None) -> list[ResourceTemplateInfo]:
        """List available resources from the server.

        Returns:
            A list of available resources.

        Raises:
            RuntimeError: If the server is not initialized.
        """
        resources_response = await self._call_with_context(ctx, options, self._session().list_resource_templates)
        return [ResourceTemplateInfo(resources) for resources in resources_response.resourceTemplates]

    async def list_prompts(self, ctx: TrpcContext, options: list | None = None) -> list[PromptInfo]:
        """List available prompts from the server.

        Returns:
            A list of available prompts.

        Raises:
            RuntimeError: If the server is not initialized.
        """
        prompts_response = await self._call_with_context(ctx, options, self._session().list_prompts)
        return [PromptInfo(prompts) for prompts in prompts_response.prompts]

    async def execute_tool(
        self,
        ctx: TrpcContext,
        tool_name: str,
        arguments: dict[str, Any],
        retries: int = 2,
        delay: float = 1.0,
        options: list | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a tool with retry mechanism.

        Args:
            tool_name: Name of the tool to execute.
            arguments: Tool arguments.
            retries: Number of retry attempts.
            delay: Delay between retries in seconds.
            meta: Optional request ``_meta`` forwarded to the server (MCP 1.16+,
                e.g. for OpenAI Apps style metadata passthrough).

        Returns:
            Tool execution result.

        Raises:
            RuntimeError: If server is not initialized.
            Exception: If tool execution fails after all retries.
        """
        attempt = 0
        while attempt < retries:
            try:
                logger.info(f"Executing {tool_name}...")
                call_tool = self._session().call_tool
                # ``meta`` was added to ClientSession.call_tool in mcp 1.16; only
                # forward it when the installed SDK supports it so we stay
                # compatible across the whole supported mcp range.
                call_kwargs: dict[str, Any] = {}
                if "meta" in inspect.signature(call_tool).parameters:
                    call_kwargs["meta"] = meta
                elif meta is not None:
                    logger.warning("installed mcp does not support call_tool(meta=...); "
                                   "ignoring meta - upgrade mcp to use this feature")
                result = await self._call_with_context(
                    ctx,
                    options,
                    call_tool,
                    tool_name,
                    arguments,
                    **call_kwargs,
                )

                return result

            except Exception as e:  # pylint: disable=broad-except
                attempt += 1
                logger.warning(f"Error executing tool: {e}. Attempt {attempt} of {retries}.")
                if attempt < retries:
                    logger.info(f"Retrying in {delay} seconds...")
                    await anyio.sleep(delay)
                else:
                    logger.error("Max retries reached. Failing.")
                    raise

    async def get_prompts(
        self,
        ctx: TrpcContext,
        name: str,
        arguments: dict[str, Any],
        retries: int = 2,
        delay: float = 1.0,
        options: list | None = None,
    ) -> Any:
        """Execute a tool with retry mechanism.

        Args:
            tool_name: Name of the tool to execute.
            arguments: Tool arguments.
            retries: Number of retry attempts.
            delay: Delay between retries in seconds.

        Returns:
            Tool execution result.

        Raises:
            RuntimeError: If server is not initialized.
            Exception: If tool execution fails after all retries.
        """
        attempt = 0
        while attempt < retries:
            try:
                logger.info(f"Getting prompt {name}...")
                result = await self._call_with_context(ctx, options, self._session().get_prompt, name, arguments)

                return result

            except Exception as e:  # pylint: disable=broad-except
                attempt += 1
                logger.warning(f"Error executing tool: {e}. Attempt {attempt} of {retries}.")
                if attempt < retries:
                    logger.info(f"Retrying in {delay} seconds...")
                    await anyio.sleep(delay)
                else:
                    logger.error("Max retries reached. Failing.")
                    raise

    async def read_resource(
        self,
        ctx: TrpcContext,
        uri: str,
        retries: int = 2,
        delay: float = 1.0,
        options: list | None = None,
    ) -> Any:
        """Execute a tool with retry mechanism.

        Args:
            tool_name: Name of the tool to execute.
            arguments: Tool arguments.
            retries: Number of retry attempts.
            delay: Delay between retries in seconds.

        Returns:
            Tool execution result.

        Raises:
            RuntimeError: If server is not initialized.
            Exception: If tool execution fails after all retries.
        """
        attempt = 0
        while attempt < retries:
            try:
                logger.info(f"Reading resource {uri}...")
                result = await self._call_with_context(ctx, options, self._session().read_resource, AnyUrl(uri))

                return result

            except Exception as e:  # pylint: disable=broad-except
                attempt += 1
                logger.warning(f"Error executing tool: {e}. Attempt {attempt} of {retries}.")
                if attempt < retries:
                    logger.info(f"Retrying in {delay} seconds...")
                    await anyio.sleep(delay)
                else:
                    logger.error("Max retries reached. Failing.")
                    raise

    async def cleanup(self) -> None:
        """Clean up server resources."""
        async with self._cleanup_lock:
            try:
                await self.exit_stack.aclose()
                self.session = None
            except Exception as e:  # pylint: disable=broad-except
                logger.error(f"Error during cleanup of server {self.name}: {e}")
