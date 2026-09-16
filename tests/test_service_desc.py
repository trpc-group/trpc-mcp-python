# -*- coding: utf-8 -*-
"""Tests for trpc_mcp.service_desc."""

import types

import pytest
from trpc import config as TrpcYamlConf

from trpc_mcp import service_desc
from trpc_mcp._config import McpServerConfig
from trpc_mcp.service_desc import (
    TrpcMcpServicer,
    _before_fork_in_master,
    mcp_handle,
    register_trpc_mcp_server,
    repair_worker_num,
)

from conftest import run


class _FakeOpt:

    def __init__(self):
        self.worker_num = None


class _FakeServer:

    def __init__(self):
        self.opt = _FakeOpt()
        self.registered = []

    def register(self, desc):
        self.registered.append(desc)


@pytest.fixture
def restore_worker_num():
    saved = TrpcYamlConf.global_config_obj.server.worker_num
    yield
    TrpcYamlConf.global_config_obj.server.worker_num = saved


class TestBeforeForkInMaster:

    def test_forces_single_worker_without_redis(self, restore_worker_num):
        TrpcYamlConf.global_config_obj.server.worker_num = 4
        svr = _FakeServer()
        cfg = McpServerConfig(redis={}, settings={"stateless_http": False})
        _before_fork_in_master(cfg, svr)
        assert TrpcYamlConf.global_config_obj.server.worker_num == 1
        assert svr.opt.worker_num == 1

    def test_keeps_workers_when_redis_and_stateless(self, restore_worker_num):
        TrpcYamlConf.global_config_obj.server.worker_num = 4
        svr = _FakeServer()
        cfg = McpServerConfig(redis={"host": "x"}, settings={"stateless_http": True})
        _before_fork_in_master(cfg, svr)
        assert TrpcYamlConf.global_config_obj.server.worker_num == 4
        assert svr.opt.worker_num == 4

    def test_single_worker_no_change(self, restore_worker_num):
        TrpcYamlConf.global_config_obj.server.worker_num = 1
        svr = _FakeServer()
        cfg = McpServerConfig(redis={}, settings={"stateless_http": False})
        _before_fork_in_master(cfg, svr)
        assert svr.opt.worker_num == 1


class TestRepairWorkerNum:

    def test_invokes_before_fork(self, restore_worker_num, monkeypatch):
        called = {}

        def fake_load():
            return types.SimpleNamespace(server=McpServerConfig())

        monkeypatch.setattr(service_desc, "load_mcp_config", fake_load)
        svr = _FakeServer()
        repair_worker_num(svr)
        assert svr.opt.worker_num is not None


class TestRegisterTrpcMcpServer:

    def test_register_with_default_name(self, restore_worker_num, monkeypatch):
        monkeypatch.setattr(service_desc, "repair_worker_num", lambda svr: None)
        svr = _FakeServer()
        register_trpc_mcp_server(svr, None)
        assert len(svr.registered) == 1
        assert svr.registered[0].service_name == "trpc.llm.mcp.service"

    def test_register_with_custom_name(self, restore_worker_num, monkeypatch):
        monkeypatch.setattr(service_desc, "repair_worker_num", lambda svr: None)
        svr = _FakeServer()
        register_trpc_mcp_server(svr, TrpcMcpServicer(), servicer_name="my.svc")
        assert svr.registered[0].service_name == "my.svc"


class TestServicerAndHandle:

    def test_servicer_handle_raises(self):
        with pytest.raises(NotImplementedError):
            run(TrpcMcpServicer().handle(None, []))

    def test_mcp_handle_is_noop(self):
        assert run(mcp_handle(None, [])) is None
