# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com
"""
TRPC FastAPI Server Transport Module.

This module provides FastAPI server transport functionality for TRPC framework integration.
It includes classes for handling FastAPI server processes, HTTP middleware, and route registration
to bridge TRPC services with FastAPI web framework.
"""
import asyncio
import threading
from collections import defaultdict
from typing import Any, Dict

import uvicorn
from mcp.server.fastmcp.server import FastMCP

from trpc.filter import get_server_filter
from trpc.plugin import PluginInitPos
from trpc.plugin import PluginType
from trpc.plugin import register_plugin
from trpc.server.worker import ExecutorProcess
from trpc.trpc_abc.transport import BaseServerTransport
from trpc.trpc_abc.transport import BaseServerTransportOption
from trpc.trpc_abc.transport import BaseTrpcServerEngine

from ._constants import CALLBACK_NAME
from ._constants import TRPC_MCP_PROTOCOL
from ._constants import MCP_STDIO
from ._constants import MCP_STREAMABLE_HTTP
from ._config import get_mcp_server_config
from ._config import get_mcp_server_options
from ._logging import bridge_third_party_loggers
from ._trpc_mcp_server import TrpcMcpServer
from .utils import create_uvicorn_compatible_socket
from .tools import get_all_tools
from .tools import get_tools
from .resources import get_all_resources
from .resources import get_resources
from .prompts import get_all_prompts
from .prompts import get_prompts

_user_mcp_app: Dict[str, FastMCP] = {}

_STDIO_UNSUPPORTED_MESSAGE = ("MCP stdio transport is not supported by the TRPC server transport. "
                              "stdio requires the process stdin/stdout to be dedicated to MCP JSON-RPC, "
                              "but TRPC starts MCP inside its server/worker lifecycle where stdout may be "
                              "used by logs and is not a stable MCP stream. Use sse or streamable-http instead.")


def register_mcp_app(service_name: str, app: FastMCP) -> None:
    """Register a MCP application for a specific service.

    Args:
        service_name: Name of the TRPC service to associate with the MCP app
        app: MCP application instance to register
    """
    _user_mcp_app[service_name] = app


class McpProcess(ExecutorProcess):
    """Process for handling MCP server execution in multi-listener mode.

    This class extends ExecutorProcess to manage MCP server lifecycle,
    including middleware setup, route registration, and server startup.
    """

    def __init__(self, worker: Any, engine: Any) -> None:
        """Initialize the MCP process.

        Args:
            worker: Worker instance for process management
            engine: Engine instance for server operations
        """
        super().__init__(worker, engine)
        self._mcp_app: FastMCP = None
        self._th: threading.Thread = None
        self._started = False
        self._start_lock = threading.Lock()
        self.user_protocol_handles = {TRPC_MCP_PROTOCOL: self.__handle_mcp}
        self._rpc_methods = set()

    @property
    def mcp_app(self) -> FastMCP:
        """Get the MCP application instance.

        Returns:
            FastMCP: The current MCP application instance
        """
        return self._mcp_app

    def __handle_mcp(self, index: int) -> None:
        """Start MCP consumer in background thread.

        Args:
            index: Index of the transport option to use
        """
        with self._start_lock:
            if self._started:
                return
            self._started = True
            self._th = threading.Thread(target=self.__start_mcp_executors)
            self._th.daemon = True
            self._th.start()

    def handle_exit_signal(self) -> None:
        """Handle process exit signal and cleanup resources."""
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)

    def _mcp_indices(self) -> list[int]:
        return [index for index, service in enumerate(self.services) if service.opt.protocol == TRPC_MCP_PROTOCOL]

    def _run_mcp_app(self, indices: list[int], mcp_app: FastMCP, transport: str, mount_path: str | None) -> None:
        """Run MCP app with TRPC-managed uvicorn socket."""
        if transport == MCP_STDIO:
            raise RuntimeError(_STDIO_UNSUPPORTED_MESSAGE)
        bridge_third_party_loggers()

        if transport == MCP_STREAMABLE_HTTP:
            app = mcp_app.streamable_http_app()
        else:
            # Keep SSE as the default for backward compatibility.
            app = mcp_app.sse_app(mount_path)

        uvicorn_config = uvicorn.Config(
            app,
            host=self.tran_opts[indices[0]].address,
            port=self.tran_opts[indices[0]].port,
            log_level=mcp_app.settings.log_level.lower(),
            log_config=None,
        )
        server = uvicorn.Server(uvicorn_config)
        sockets = [
            create_uvicorn_compatible_socket(self.tran_opts[index].address, self.tran_opts[index].port)
            for index in indices
        ]
        server.run(sockets=sockets)

    @staticmethod
    def _add_bindings(bindings: dict[str, set[str]], names: list[str], service_names: list[str]) -> None:
        for name in names:
            bindings[name].update(service_names)

    def _build_service_bindings(self, service_names: list[str]):
        tool_services = defaultdict(set)
        resource_services = defaultdict(set)
        prompt_services = defaultdict(set)

        self._add_bindings(tool_services, [tool.name for tool in get_tools()], service_names)
        self._add_bindings(resource_services, [resource.uri for resource in get_resources()], service_names)
        self._add_bindings(prompt_services, [prompt.name for prompt in get_prompts()], service_names)

        for service_name in service_names:
            self._add_bindings(tool_services, [tool.name for tool in get_tools(service_name)], [service_name])
            self._add_bindings(resource_services, [resource.uri for resource in get_resources(service_name)],
                               [service_name])
            self._add_bindings(prompt_services, [prompt.name for prompt in get_prompts(service_name)], [service_name])

        return dict(tool_services), dict(resource_services), dict(prompt_services)

    def __start_mcp_executors(self) -> None:
        """Start MCP server executors in multi-listener mode.

        Args:
            index: Index of the transport option to use
        """
        indices = self._mcp_indices()
        if not indices:
            return
        for index in indices:
            filter_obj = get_server_filter(CALLBACK_NAME)
            if filter_obj:
                self.services[index].opt.add_filter(filter_obj)
        service_names = [self.services[index].opt.service_name for index in indices]
        mcp_config = get_mcp_server_config()
        mcp_options = get_mcp_server_options()
        settings = mcp_config.settings.copy()
        addr = self.tran_opts[indices[0]].address
        port = self.tran_opts[indices[0]].port
        settings["host"] = addr
        settings["port"] = port
        default_mcp = TrpcMcpServer(
            name=",".join(service_names),
            instructions=mcp_config.instructions,
            auth_server_provider=mcp_options.auth_server_provider,
            token_verifier=mcp_options.token_verifier,
            event_store=mcp_options.event_store,
            tools=mcp_options.tools,
            **settings,
        )
        mcp_app = next((_user_mcp_app[name] for name in service_names if name in _user_mcp_app), default_mcp)
        self._mcp_app = mcp_app
        if hasattr(mcp_app, "set_trpc_options_map"):
            mcp_app.set_trpc_options_map([self.tran_opts[index] for index in indices])
        if hasattr(mcp_app, "set_sse_redis_config"):
            mcp_app.set_sse_redis_config(mcp_config.redis)

        tool_services, resource_services, prompt_services = self._build_service_bindings(service_names)
        if hasattr(mcp_app, "set_service_bindings"):
            mcp_app.set_service_bindings(tool_services, resource_services, prompt_services)

        for tool in get_all_tools():
            mcp_app.tool(name=tool.name,
                         title=tool.title,
                         description=tool.description,
                         annotations=tool.annotations,
                         icons=tool.icons,
                         meta=tool.meta,
                         structured_output=tool.structured_output)(tool.fn)
        for resource in get_all_resources():
            mcp_app.resource(resource.uri,
                             name=resource.name,
                             title=resource.title,
                             description=resource.description,
                             mime_type=resource.mime_type,
                             icons=resource.icons,
                             annotations=resource.annotations,
                             meta=resource.meta)(resource.fn)

        for prompt in get_all_prompts():
            mcp_app.prompt(prompt.name, title=prompt.title, description=prompt.description,
                           icons=prompt.icons)(prompt.fn)
        # NOTE: base_url is already baked into the SSE/message/streamable paths in
        # settings (see load_mcp_config -> make_all_mcp_url). Do NOT also pass it as
        # mount_path, otherwise FastMCP.sse_app would prepend base_url a second time
        # to the SSE "endpoint" event (e.g. test/test/messages/), and the client
        # would urljoin it into a third copy (/test/test/test/messages/) -> 404.
        self._run_mcp_app(indices, mcp_app, mcp_config.transport, None)


class TrpcMcpServerTransport(BaseServerTransport):
    """MCP server transport implementation for TRPC framework.

    This class provides the transport layer for integrating TRPC services
    with FastAPI web server, handling server lifecycle and process management.
    """

    def __init__(self) -> None:
        """Initialize the FastAPI server transport."""
        self.opts = None
        self.loop = None
        self.server_engine = None

    def listen_and_serve(self, opts: BaseServerTransportOption, server_engine: BaseTrpcServerEngine) -> None:
        """Start listening and serving FastAPI requests.

        Args:
            opts: Server transport configuration options
            server_engine: TRPC server engine instance
        """
        if get_mcp_server_config().transport == MCP_STDIO:
            raise RuntimeError(_STDIO_UNSUPPORTED_MESSAGE)
        self.opts = opts
        self.server_engine = server_engine
        try:
            self.loop = asyncio.get_event_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
        self.set_executor_process()

    def set_executor_process(self) -> None:
        """Set up executor process for handling FastAPI messages."""
        self.server_engine.set_executor_process(
            (self.opts.address, self.opts.port),
            self.opts.socket_type,
            self.opts.handle,
            self.opts.checker,
            self.opts.idle_timeout,
            self.opts.network,
            self.opts.service,
            self.opts,
            self.opts.target,
        )
        # Specify FastapiProcess
        self.server_engine.work_handle = McpProcess

    def close(self) -> None:
        """Close the server transport and cleanup resources."""
        self.server_engine.close()


@register_plugin(PluginType.SERVER_TRANSPORT, TRPC_MCP_PROTOCOL, init_pos=PluginInitPos.MASTER)
class TrpcMcpServerTransportFactory:
    """Factory class for creating MCP server transport instances.

    This factory is registered as a TRPC plugin to provide MCP transport capability.
    """

    def create(self) -> TrpcMcpServerTransport:
        """Create a new MCP server transport instance.

        Returns:
            TrpcMcpServerTransport: A new instance of MCP server transport
        """
        return TrpcMcpServerTransport()
