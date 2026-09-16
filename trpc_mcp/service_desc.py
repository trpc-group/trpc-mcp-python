# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com
"""
TRPC MCP Service Description Module

This module provides service registration and handling for TRPC MCP (Microservice Control Protocol).
It includes the base servicer class and registration utilities.
"""

from typing import List
from trpc import config as TrpcYamlConf
from trpc import context
from trpc import server
from trpc.log import logger

from ._config import McpServerConfig
from ._config import load_mcp_config
from ._constants import STATELESS_HTTP


def _before_fork_in_master(mcp_server: McpServerConfig, svr: server.Server):
    """Callback executed before fork in master process."""
    worker_num = TrpcYamlConf.global_config_obj.server.worker_num
    stateless_http = mcp_server.settings.get(STATELESS_HTTP, False)
    if (not mcp_server.redis or stateless_http is False) and worker_num > 1:
        TrpcYamlConf.global_config_obj.server.worker_num = 1
        warn_info = f"mcp redis is not configured or not stateless_http, worker_num is {worker_num},"
        warn_info = f"{warn_info} redis: {mcp_server.redis} stateless_http: {stateless_http},"
        logger.warning(f"{warn_info} worker_num is set to 1")
    svr.opt.worker_num = TrpcYamlConf.global_config_obj.server.worker_num


def repair_worker_num(svr: server.Server):
    """Repair the worker number if it is not set correctly."""
    mcp_config = load_mcp_config()
    server_config = mcp_config.server
    _before_fork_in_master(server_config, svr)


async def mcp_handle(ctx: context, message: List):
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

    async def handle(self, ctx: context.Context, msgs):
        raise NotImplementedError('Method not implemented!')


def register_trpc_mcp_server(svr: server.Server, servicer: TrpcMcpServicer, servicer_name: str = None):
    """Register an MCP service with the TRPC server.

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

    desc = server.ServiceDesc(svc_name, [server.Method(
        f"/{svc_name}/handle",
        None,
        None,
        mcp_handle,
    )])

    svr.register(desc)
