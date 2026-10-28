# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Tests for trpc_mcp.service_desc."""

import types

import pytest

from trpc_mcp import service_desc
from trpc_mcp._config import McpServerConfig
from trpc_mcp._constants import MCP_STDIO
from trpc_mcp.service_desc import (
    TrpcMcpServicer,
    _before_fork_in_master,
    mcp_handle,
    register_trpc_mcp_server,
    repair_worker_num,
)

from conftest import run


class _FakeOpt:

    def __init__(self, mode="merge", worker_num=0):
        self.mode = mode
        self.worker_num = worker_num


class _FakeServer:

    def __init__(self, mode="merge", worker_num=0):
        self.opt = _FakeOpt(mode, worker_num)
        self.registered = []

    def register(self, desc):
        self.registered.append(desc)


_NO_REDIS = McpServerConfig(redis={}, settings={"stateless_http": True})
_STATEFUL = McpServerConfig(redis={"host": "x"}, settings={"stateless_http": False})
_SHARED = McpServerConfig(redis={"host": "x"}, settings={"stateless_http": True})


class TestBeforeForkInMaster:

    @pytest.mark.parametrize("mode", ["separate", "seperate", "peer"])
    @pytest.mark.parametrize("cfg", [_NO_REDIS, _STATEFUL], ids=["no_redis", "stateful"])
    def test_multi_process_forced_to_one_without_shared_sessions(self, mode, cfg):
        svr = _FakeServer(mode, 4)
        _before_fork_in_master(cfg, svr)
        assert svr.opt.worker_num == 1

    @pytest.mark.parametrize("mode", ["separate", "peer"])
    def test_multi_process_kept_with_redis_and_stateless(self, mode):
        svr = _FakeServer(mode, 4)
        _before_fork_in_master(_SHARED, svr)
        assert svr.opt.worker_num == 4

    @pytest.mark.parametrize("mode", ["separate", "peer"])
    def test_single_process_unchanged(self, mode):
        svr = _FakeServer(mode, 1)
        _before_fork_in_master(_NO_REDIS, svr)
        assert svr.opt.worker_num == 1

    @pytest.mark.parametrize("cfg", [_NO_REDIS, _STATEFUL, _SHARED], ids=["no_redis", "stateful", "shared"])
    def test_merge_never_touched(self, cfg):
        # merge never reads worker_num: threaded merge still runs one uvicorn.
        svr = _FakeServer("merge", 4)
        _before_fork_in_master(cfg, svr)
        assert svr.opt.worker_num == 4

    def test_stdio_rejected_before_fork(self):
        svr = _FakeServer("merge", 0)
        with pytest.raises(ValueError, match="stdio"):
            _before_fork_in_master(McpServerConfig(transport=MCP_STDIO), svr)


class TestRepairWorkerNum:

    def test_uses_loaded_server_config(self, monkeypatch):
        monkeypatch.setattr(service_desc, "load_mcp_config", lambda: types.SimpleNamespace(server=_NO_REDIS))
        svr = _FakeServer("separate", 8)
        repair_worker_num(svr)
        assert svr.opt.worker_num == 1


class TestRegisterTrpcMcpServer:

    def test_register_with_default_name(self, monkeypatch):
        monkeypatch.setattr(service_desc, "repair_worker_num", lambda svr: None)
        svr = _FakeServer()
        register_trpc_mcp_server(svr, None)
        assert len(svr.registered) == 1
        assert svr.registered[0].service_name == "trpc.llm.mcp.service"
        assert svr.registered[0].methods[0].name == "/trpc.llm.mcp.service/handle"

    def test_register_with_custom_name(self, monkeypatch):
        monkeypatch.setattr(service_desc, "repair_worker_num", lambda svr: None)
        svr = _FakeServer()
        register_trpc_mcp_server(svr, TrpcMcpServicer(), servicer_name="my.svc")
        assert svr.registered[0].service_name == "my.svc"

    def test_register_repairs_worker_num(self, monkeypatch):
        monkeypatch.setattr(service_desc, "load_mcp_config", lambda: types.SimpleNamespace(server=_NO_REDIS))
        svr = _FakeServer("peer", 3)
        register_trpc_mcp_server(svr, None)
        assert svr.opt.worker_num == 1


class TestServicerAndHandle:

    def test_servicer_handle_raises(self):
        with pytest.raises(NotImplementedError):
            run(TrpcMcpServicer().handle(None, []))

    def test_mcp_handle_is_noop(self):
        assert run(mcp_handle(None, [])) is None
