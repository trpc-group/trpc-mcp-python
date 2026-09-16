# -*- coding: utf-8 -*-
"""Tests for trpc_mcp._config."""

import pytest
from mcp.server.fastmcp.server import Settings
from trpc.config import config as trpc_config

from trpc_mcp import _config
from trpc_mcp._config import (
    McpClientConfig,
    McpConfig,
    McpServerConfig,
    McpServerOptions,
    _default_full_settings,
    get_mcp_client_config,
    get_mcp_server_config,
    get_mcp_server_options,
    get_set_settings_func,
    load_mcp_config,
    register_set_settings_func,
    set_mcp_server_options,
)
from trpc_mcp._constants import (
    SSE_MESSAGE_PATH_CONF,
    SSE_PATH_CONF,
    STATELESS_HTTP,
    STREAMABLE_HTTP_PATH_CONF,
)


@pytest.fixture
def clean_plugins_config():
    saved = trpc_config.global_plugins_config
    trpc_config.global_plugins_config = {}
    yield trpc_config.global_plugins_config
    trpc_config.global_plugins_config = saved


class TestDataclasses:

    def test_server_config_defaults(self):
        cfg = McpServerConfig()
        assert cfg.name == "TrpcFastMCP"
        assert cfg.transport == "sse"
        assert cfg.settings == {"stateless_http": True}
        assert cfg.redis == {}

    def test_client_config_defaults(self):
        cfg = McpClientConfig()
        assert cfg.transport == "sse"
        assert cfg.host == ""

    def test_mcp_config_fields_map_doc(self):
        # ``trpc_dataclass`` sets ``__init__.__doc__`` from ``fields_map``.
        assert "Server configuration" in McpConfig.__init__.__doc__


class TestLoadMcpConfig:

    def test_defaults_when_empty(self, clean_plugins_config):
        cfg = load_mcp_config()
        assert isinstance(cfg.server, McpServerConfig)
        assert isinstance(cfg.client, McpClientConfig)
        assert cfg.server.settings[STATELESS_HTTP] is True
        assert cfg.server.settings[SSE_PATH_CONF] == "/sse"
        assert cfg.server.settings[SSE_MESSAGE_PATH_CONF] == "/messages/"
        assert cfg.server.settings[STREAMABLE_HTTP_PATH_CONF] == "/mcp"

    def test_with_base_url_and_existing_stateless(self, clean_plugins_config):
        clean_plugins_config["mcp"] = {
            "server": {
                "base_url": "/api",
                "settings": {
                    "stateless_http": False
                }
            },
            "client": {
                "host": "h"
            },
        }
        cfg = load_mcp_config()
        assert cfg.server.base_url == "/api"
        assert cfg.server.settings[STATELESS_HTTP] is False
        assert cfg.server.settings[SSE_PATH_CONF] == "/api/sse"
        assert cfg.client.host == "h"

    def test_get_server_and_client_config(self, clean_plugins_config):
        assert isinstance(get_mcp_server_config(), McpServerConfig)
        assert isinstance(get_mcp_client_config(), McpClientConfig)


class TestDefaultFullSettings:

    def test_fills_required_and_drops_unknown(self):
        result = _default_full_settings({"unknown_key": 1, "port": 9999})
        assert isinstance(result, Settings)
        assert "unknown_key" not in result.model_dump()
        assert result.port == 9999

    def test_empty_config(self):
        result = _default_full_settings({})
        assert isinstance(result, Settings)


class TestSettingsFuncRegistry:

    def test_default_func(self):
        assert get_set_settings_func() is _default_full_settings

    def test_register_and_restore(self):
        original = get_set_settings_func()

        def custom(config):
            return Settings()

        register_set_settings_func(custom)
        try:
            assert get_set_settings_func() is custom
        finally:
            register_set_settings_func(original)


class TestServerOptions:

    def test_set_and_get(self):
        original = get_mcp_server_options()
        try:
            opts = McpServerOptions()
            set_mcp_server_options(opts)
            assert get_mcp_server_options() is opts
        finally:
            set_mcp_server_options(original)

    def test_options_defaults(self):
        opts = McpServerOptions()
        assert opts.auth_server_provider is None
        assert opts.token_verifier is None
        assert opts.event_store is None
        assert opts.tools is None
