# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""
TRPC MCP Server Transport Module.

Importing this module registers :func:`start_mcp` as the SDK protocol starter
for ``http_mcp``. ``ServiceAdapter.run`` then serves every ``http_mcp`` address
through a ``UserProtocolTransport``, and the SDK calls the starter in each
process that serves those addresses:

- merge, single loop: the main thread, ``worker`` is the ``MergeWorker``;
- merge, threaded: serving thread 0, ``worker`` is a ``WorkerLoopView``;
- separate: every rpc task (the I/O process never touches MCP ports);
- peer: every peer worker.

Each serving process gets one MCP app and one uvicorn daemon thread, shared by
all ``http_mcp`` addresses of the process. uvicorn runs its own event loop on
that thread and installs no signal handlers there, so SIGTERM stays with the
SDK worker, which stops uvicorn through its exit callbacks.
"""
import inspect
import os
import threading
from collections import defaultdict
from time import sleep
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple

import uvicorn
from mcp.server.fastmcp.server import FastMCP
from starlette.types import ASGIApp

from trpc_sdk.common import get_current_process_var
from trpc_sdk.common import set_current_process_var
from trpc_sdk.filters import get_server_filter
from trpc_sdk.log import logger
from trpc_sdk.transport import UserProtocolTransport
from trpc_sdk.transport import register_protocol_handle

from ._constants import CALLBACK_NAME
from ._constants import MCP_STDIO
from ._constants import MCP_STREAMABLE_HTTP
from ._constants import TRPC_MCP_PROCESS_VAR
from ._constants import TRPC_MCP_PROTOCOL
from ._config import McpServerConfig
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

# Filled at import time and inherited by every forked process; read when a
# process builds its app.
_user_mcp_app: Dict[str, FastMCP] = {}

_STDIO_UNSUPPORTED_MESSAGE = ("MCP stdio transport is not supported by the TRPC server transport. "
                              "stdio requires the process stdin/stdout to be dedicated to MCP JSON-RPC, "
                              "but TRPC starts MCP inside its server/worker lifecycle where stdout may be "
                              "used by logs and is not a stable MCP stream. Use sse or streamable-http instead.")

# Extra seconds the post-drain join waits for uvicorn, on top of the drain the
# SDK already waited, so lifespan shutdown and task cancellation can finish.
_STOP_JOIN_GRACE_SECONDS = 2.0


def register_mcp_app(service_name: str, app: FastMCP) -> None:
    """Register a MCP application for a specific service.

    Must happen before the process builds its app: at import time, or from a
    ``WORKER`` plugin, which the SDK initializes before it starts listeners.

    Args:
        service_name: Name of the TRPC service to associate with the MCP app
        app: MCP application instance to register
    """
    _user_mcp_app[service_name] = app


class McpProcess:
    """Per-process MCP state: the app, its uvicorn server and thread.

    Stored as a process variable, so each rpc task and peer worker owns a
    separate instance after fork.

    Attributes:
        mcp_app: The MCP app served by this process, ``None`` until built.
        server: uvicorn server running ``mcp_app``.
        thread: Daemon thread running ``server``.
        started: True once this process started its uvicorn thread.
        callback_services: ``id()`` of every service that already has the
            callback filter, so it is installed once per service.
    """

    def __init__(self) -> None:
        """Create empty state; filled by :func:`start_mcp`."""
        self.mcp_app: Optional[FastMCP] = None
        self.server: Optional[uvicorn.Server] = None
        self.thread: Optional[threading.Thread] = None
        self.started: bool = False
        self.callback_services: Set[int] = set()

    def request_stop(self) -> None:
        """Ask uvicorn to stop accepting and shut down; returns at once.

        Registered as a worker exit callback, so uvicorn stops accepting at
        the same time as the SDK listeners.
        """
        if self.server is not None:
            self.server.should_exit = True

    def join(self, timeout: float) -> None:
        """Wait for the uvicorn thread to finish its shutdown.

        Args:
            timeout: Seconds to wait at most; the thread is a daemon, so the
                process still exits if uvicorn overruns it.
        """
        thread = self.thread
        if thread is None or not thread.is_alive():
            return
        thread.join(timeout)
        if thread.is_alive():
            logger.warning(f"MCP uvicorn did not stop within {timeout:.1f}s; exiting anyway")


def get_or_create_mcp_process() -> McpProcess:
    """Return this process's :class:`McpProcess`, creating it on first use.

    Returns:
        McpProcess: The instance stored on ``multiprocessing.current_process()``.
    """
    mcp_process = get_current_process_var(TRPC_MCP_PROCESS_VAR)
    if mcp_process is None:
        mcp_process = McpProcess()
        set_current_process_var(TRPC_MCP_PROCESS_VAR, mcp_process)
    return mcp_process


def _mcp_indices(worker: Any) -> List[int]:
    """Return the indices of every address this starter serves.

    Args:
        worker: SDK worker (or loop view) serving the addresses.
    """
    return [
        index for index, transport in enumerate(worker.transports)
        if isinstance(transport, UserProtocolTransport) and transport.starter is start_mcp
    ]


def _add_bindings(bindings: Dict[str, Set[str]], names: List[str], service_names: List[str]) -> None:
    for name in names:
        bindings[name].update(service_names)


def _build_service_bindings(service_names: List[str]) -> Tuple[dict, dict, dict]:
    tool_services = defaultdict(set)
    resource_services = defaultdict(set)
    prompt_services = defaultdict(set)

    _add_bindings(tool_services, [tool.name for tool in get_tools()], service_names)
    _add_bindings(resource_services, [resource.uri for resource in get_resources()], service_names)
    _add_bindings(prompt_services, [prompt.name for prompt in get_prompts()], service_names)

    for service_name in service_names:
        _add_bindings(tool_services, [tool.name for tool in get_tools(service_name)], [service_name])
        _add_bindings(resource_services, [resource.uri for resource in get_resources(service_name)],
                      [service_name])
        _add_bindings(prompt_services, [prompt.name for prompt in get_prompts(service_name)], [service_name])

    return dict(tool_services), dict(resource_services), dict(prompt_services)


def _install_callback_filter(mcp_process: McpProcess, worker: Any, indices: List[int]) -> None:
    filter_obj = get_server_filter(CALLBACK_NAME)
    if not filter_obj:
        return
    for index in indices:
        service = worker.services[index]
        if id(service) in mcp_process.callback_services:
            continue
        service.opt.add_filter(filter_obj)
        mcp_process.callback_services.add(id(service))


def build_app(worker: Any, indices: List[int], mcp_process: McpProcess,
              mcp_config: McpServerConfig) -> Tuple[FastMCP, ASGIApp]:
    """Build this process's MCP app and the ASGI app uvicorn serves.

    Args:
        worker: SDK worker (or loop view) serving the addresses.
        indices: Indices of the ``http_mcp`` addresses in the worker tables.
        mcp_process: State of the serving process.
        mcp_config: ``plugins.mcp.server`` config.

    Returns:
        The MCP app, and its SSE or streamable-http ASGI app.
    """
    _install_callback_filter(mcp_process, worker, indices)
    tran_opts = [worker.tran_opts[index] for index in indices]
    service_names = [opts.service_name for opts in tran_opts]
    mcp_options = get_mcp_server_options()
    settings = mcp_config.settings.copy()
    settings["host"] = tran_opts[0].address[0]
    settings["port"] = tran_opts[0].port
    mcp_app = next((_user_mcp_app[name] for name in service_names if name in _user_mcp_app), None)
    if mcp_app is None:
        mcp_app = TrpcMcpServer(
            name=",".join(service_names),
            instructions=mcp_config.instructions,
            auth_server_provider=mcp_options.auth_server_provider,
            token_verifier=mcp_options.token_verifier,
            event_store=mcp_options.event_store,
            tools=mcp_options.tools,
            **settings,
        )
    if hasattr(mcp_app, "set_trpc_options_map"):
        mcp_app.set_trpc_options_map(tran_opts)
    if hasattr(mcp_app, "set_sse_redis_config"):
        mcp_app.set_sse_redis_config(mcp_config.redis)

    tool_services, resource_services, prompt_services = _build_service_bindings(service_names)
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

    if mcp_config.transport == MCP_STREAMABLE_HTTP:
        app = mcp_app.streamable_http_app()
    else:
        # SSE is the default for backward compatibility.
        # NOTE: base_url is already baked into the SSE/message/streamable paths in
        # settings (see load_mcp_config -> make_all_mcp_url). Do NOT also pass it as
        # mount_path, otherwise FastMCP.sse_app would prepend base_url a second time
        # to the SSE "endpoint" event (e.g. test/test/messages/), and the client
        # would urljoin it into a third copy (/test/test/test/messages/) -> 404.
        app = mcp_app.sse_app(None)
    return mcp_app, app


def _uvicorn_config(app: ASGIApp, mcp_app: FastMCP, drain_seconds: float) -> uvicorn.Config:
    kwargs: Dict[str, Any] = {"log_level": mcp_app.settings.log_level.lower(), "log_config": None}
    if "timeout_graceful_shutdown" in inspect.signature(uvicorn.Config).parameters:
        kwargs["timeout_graceful_shutdown"] = drain_seconds
    return uvicorn.Config(app, **kwargs)


def _serve(server: uvicorn.Server, sockets: list) -> None:
    """uvicorn thread entry; any failure takes the whole process down.

    Args:
        server: uvicorn server wrapping this process's MCP app.
        sockets: Listen sockets already bound by :func:`start_mcp`.
    """
    try:
        server.run(sockets=sockets)
    except BaseException as err:  # pylint: disable=broad-except
        logger.error(f"MCP uvicorn server failed: {err!r}")
        # Give the log a second to flush before the process goes down.
        sleep(1)
        os._exit(1)


def start_mcp(worker: Any, index: int) -> None:
    """SDK protocol starter: serve every ``http_mcp`` address of this process.

    The SDK calls it once per ``http_mcp`` address, after the serving loop
    exists and before it runs. The first call builds the app, binds every MCP
    socket on the caller's thread (so a busy port fails startup with a
    traceback), starts uvicorn on a daemon thread and returns; later calls in
    the same process return at once.

    Args:
        worker: SDK worker serving the address; a ``WorkerLoopView`` on a
            threaded merge worker, whose writes reach the real worker.
        index: Position of the address in the worker's tables.

    Raises:
        ValueError: The MCP transport is ``stdio``.
        OSError: A listen socket cannot be bound.
    """
    del index
    mcp_config = get_mcp_server_config()
    if mcp_config.transport == MCP_STDIO:
        raise ValueError(_STDIO_UNSUPPORTED_MESSAGE)
    mcp_process = get_or_create_mcp_process()
    if mcp_process.started:
        return
    bridge_third_party_loggers()

    indices = _mcp_indices(worker)
    mcp_app, app = build_app(worker, indices, mcp_process, mcp_config)
    sockets = []
    try:
        for i in indices:
            opts = worker.tran_opts[i]
            sockets.append(create_uvicorn_compatible_socket(opts.address[0], opts.port))
    except OSError:
        for sock in sockets:
            sock.close()
        raise

    drain_seconds = float(getattr(worker, "drain_seconds", 0.0) or 0.0)
    server = uvicorn.Server(_uvicorn_config(app, mcp_app, drain_seconds))
    mcp_process.mcp_app = mcp_app
    mcp_process.server = server
    mcp_process.thread = threading.Thread(target=_serve, args=(server, sockets), name="trpc-mcp-uvicorn", daemon=True)
    mcp_process.started = True
    worker.exit_callbacks.append(mcp_process.request_stop)
    worker.post_drain_callbacks.append(lambda: mcp_process.join(drain_seconds + _STOP_JOIN_GRACE_SECONDS))
    addresses = ", ".join(f"{worker.tran_opts[i].address[0]}:{worker.tran_opts[i].port}" for i in indices)
    logger.info(f"Starting MCP {mcp_config.transport} server '{mcp_app.name}' on {addresses}")
    mcp_process.thread.start()


register_protocol_handle(TRPC_MCP_PROTOCOL, start_mcp)


class TrpcMcpServerTransport(UserProtocolTransport):
    """``http_mcp`` server transport: a ``UserProtocolTransport`` bound to :func:`start_mcp`.

    The SDK builds its own ``UserProtocolTransport`` for every ``http_mcp``
    service from the registered starter, so this class is not a plugin; it
    is kept for code that constructs the MCP transport explicitly.
    """

    def __init__(self) -> None:
        """Bind the transport to the MCP starter."""
        super().__init__(start_mcp)
