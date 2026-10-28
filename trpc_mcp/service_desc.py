# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""
TRPC MCP Service Description Module

This module provides service registration and handling for TRPC MCP (Microservice Control Protocol).
It includes the base servicer class and registration utilities.
"""

from typing import List

from trpc_sdk.log import logger
from trpc_sdk.runtime import MODE_PEER
from trpc_sdk.runtime import MODE_SEPARATE
from trpc_sdk.runtime import MODE_SPELLINGS
from trpc_sdk.server import Method
from trpc_sdk.server import Server
from trpc_sdk.server import ServiceDesc
from trpc_sdk.server import TrpcContext

from ._config import McpServerConfig
from ._config import load_mcp_config
from ._constants import MCP_STDIO
from ._constants import STATELESS_HTTP
from ._trpc_server_transport import _STDIO_UNSUPPORTED_MESSAGE

# Process models where several processes serve the same MCP port.
_MULTI_PROCESS_MODES = (MODE_SEPARATE, MODE_PEER)


def _before_fork_in_master(mcp_server: McpServerConfig, svr: Server):
    """Validate the MCP transport and clamp ``worker_num`` before ``serve()`` forks.

    In separate and peer mode every serving process runs its own MCP app, so
    an SSE session or a stateful streamable-http session opened on one
    process is unknown to the others. That only works with Redis and
    ``stateless_http``; otherwise the server is forced down to one process.

    Args:
        mcp_server: ``plugins.mcp.server`` config.
        svr: Server returned by ``create_server``; ``svr.opt`` is the option
            object the worker is built from.

    Raises:
        ValueError: The MCP transport is ``stdio``.
    """
    if mcp_server.transport == MCP_STDIO:
        raise ValueError(_STDIO_UNSUPPORTED_MESSAGE)
    mode = MODE_SPELLINGS.get(svr.opt.mode, svr.opt.mode)
    worker_num = svr.opt.worker_num
    if mode not in _MULTI_PROCESS_MODES or worker_num <= 1:
        return
    stateless_http = mcp_server.settings.get(STATELESS_HTTP, False)
    if not mcp_server.redis or stateless_http is False:
        svr.opt.worker_num = 1
        logger.warning(f"mcp redis is not configured or not stateless_http, mode is {mode}, "
                       f"worker_num is {worker_num}, redis: {mcp_server.redis} stateless_http: {stateless_http}, "
                       f"worker_num is set to 1")


def repair_worker_num(svr: Server):
    """Repair the worker number if it is not set correctly."""
    mcp_config = load_mcp_config()
    server_config = mcp_config.server
    _before_fork_in_master(server_config, svr)


async def mcp_handle(ctx: TrpcContext, message: List):
    """Handle incoming MCP messages.

    Args:
        ctx: TRPC context object
        message: List of messages to process
    """
    pass


class TrpcMcpServicer:
    """Base class for TRPC MCP servicer implementations.

    Subclasses should override the handle method to implement custom message processing.
    """

    async def handle(self, ctx: TrpcContext, msgs):
        raise NotImplementedError('Method not implemented!')


def register_trpc_mcp_server(svr: Server, servicer: TrpcMcpServicer, servicer_name: str = None):
    """Register an MCP service with the TRPC server.

    Must be called before ``svr.serve()``: it may lower ``svr.opt.worker_num``,
    which the worker reads when ``serve()`` builds it.

    Args:
        svr: TRPC server instance
        servicer: Service implementation
        servicer_name: Optional custom service name

    Returns:
        None
    """
    repair_worker_num(svr)
    servicer = servicer or TrpcMcpServicer()
    svc_name = "trpc.llm.mcp.service"
    if servicer_name is not None:
        svc_name = servicer_name

    desc = ServiceDesc(svc_name, [Method(
        f"/{svc_name}/handle",
        None,
        None,
        mcp_handle,
    )])

    svr.register(desc)
