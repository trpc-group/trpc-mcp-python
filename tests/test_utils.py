# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Tests for trpc_mcp.utils."""

import socket
import types
import warnings

import pytest
from trpc_sdk.abc import TrpcContext
from trpc_sdk.common import set_current_process_var
from trpc_sdk.http import HTTP_ARGS_META_KEY

from trpc_mcp import utils
from trpc_mcp._constants import TRPC_MCP_PROCESS_VAR


class TestNormalizePath:

    def test_root_mount_path_adds_leading_slash(self):
        assert utils.normalize_path("/", "messages/") == "/messages/"

    def test_empty_mount_path(self):
        assert utils.normalize_path("", "/sse") == "/sse"

    def test_mount_without_leading_slash(self):
        assert utils.normalize_path("github", "/messages/") == "/github/messages/"

    def test_mount_with_trailing_slash(self):
        assert utils.normalize_path("/github/", "messages/") == "/github/messages/"

    def test_combined(self):
        assert utils.normalize_path("/github", "/messages/") == "/github/messages/"


class TestMakeUrl:

    def test_host_with_scheme_returned_as_is(self):
        assert utils.make_url("http://example.com/sse") == "http://example.com/sse"

    def test_host_with_explicit_scheme(self):
        assert utils.make_url("https://example.com/sse") == "https://example.com/sse"

    def test_ip_host_builds_http(self):
        assert utils.make_url("127.0.0.1:8080", "", "sse") == "http://127.0.0.1:8080/sse"

    def test_domain_builds_http(self):
        assert utils.make_url("my.service", "", "sse") == "http://my.service/sse"


class TestHttpContextHelpers:

    def test_header_round_trip(self):
        ctx = TrpcContext()
        utils.set_http_header_to_context(ctx, {"A": "B"})
        assert utils.get_http_header_from_context(ctx) == {"A": "B"}

    def test_header_default_empty(self):
        assert utils.get_http_header_from_context(TrpcContext()) == {}

    def test_kwargs_round_trip(self):
        ctx = TrpcContext()
        utils.set_http_kwargs_to_context(ctx, {"q": "1"})
        assert utils.get_http_kwargs_from_context(ctx) == {"q": "1"}
        assert ctx.meta_data[HTTP_ARGS_META_KEY] == {"q": "1"}

    def test_kwargs_default_empty(self):
        assert utils.get_http_kwargs_from_context(TrpcContext()) == {}


class TestDeprecated:

    def test_decorator_warns_and_calls(self):

        @utils.deprecated("use other")
        def fn(x):
            return x + 1

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert fn(1) == 2
        assert any(issubclass(w.category, DeprecationWarning) for w in caught)

    def test_decorator_without_details(self):

        @utils.deprecated()
        def fn():
            return "ok"

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            assert fn() == "ok"


class TestAnalyzeInitMethod:

    def test_extracts_defaults_and_skips_self(self):

        class Sample:

            def __init__(self, a=1, b="x"):
                pass

        assert utils.analyze_init_method(Sample) == {"a": 1, "b": "x"}

    def test_init_with_only_self(self):

        class OnlySelf:

            def __init__(self):
                pass

        assert utils.analyze_init_method(OnlySelf) == {}


class TestProcessVarHelpers:

    def test_get_with_default_creates_and_caches(self):
        name = "__test_unique_obj_var__"

        class Holder:
            pass

        first = utils.get_object_to_process_with_default(name, Holder)
        second = utils.get_object_to_process_with_default(name, Holder)
        assert isinstance(first, Holder)
        assert first is second


class TestSocketAndUrls:

    def test_create_uvicorn_compatible_socket(self):
        sock = utils.create_uvicorn_compatible_socket("127.0.0.1", 0)
        try:
            assert isinstance(sock, socket.socket)
            assert sock.getsockname()[0] == "127.0.0.1"
        finally:
            sock.close()

    def test_make_all_mcp_url(self):
        sse, msg, streamable = utils.make_all_mcp_url("/base")
        assert sse == "/base/sse"
        assert msg == "/base/messages/"
        assert streamable == "/base/mcp"


class TestGetMcpApp:

    @pytest.fixture(autouse=True)
    def _reset_process_var(self):
        set_current_process_var(TRPC_MCP_PROCESS_VAR, None)
        yield
        set_current_process_var(TRPC_MCP_PROCESS_VAR, None)

    def test_raises_when_missing(self):
        with pytest.raises(ValueError):
            utils.get_mcp_app()

    def test_raises_before_app_built(self):
        set_current_process_var(TRPC_MCP_PROCESS_VAR, types.SimpleNamespace(mcp_app=None))
        with pytest.raises(ValueError):
            utils.get_mcp_app()

    def test_returns_app_when_present(self):
        sentinel = object()
        set_current_process_var(TRPC_MCP_PROCESS_VAR, types.SimpleNamespace(mcp_app=sentinel))
        assert utils.get_mcp_app() is sentinel
