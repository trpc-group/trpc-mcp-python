# -*- coding: utf-8 -*-
"""Tests for trpc_mcp.utils."""

import multiprocessing
import socket
import warnings

import pytest
from trpc.context import TrpcContext
from trpc.http import defines as http_defines

from trpc_mcp import utils


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


class TestIsValidPattern:

    def test_valid_ip_port(self):
        assert utils._is_valid_pattern("127.0.0.1:8080") is True

    def test_invalid_ip(self):
        assert utils._is_valid_pattern("999.0.0.1:8080") is False

    def test_not_ip_port(self):
        assert utils._is_valid_pattern("example.com") is False

    def test_port_out_of_range(self):
        assert utils._is_valid_pattern("127.0.0.1:70000") is False


class TestMakeUrl:

    def test_host_with_scheme_returned_as_is(self):
        assert utils.make_url("http://example.com/sse") == "http://example.com/sse"

    def test_host_with_explicit_scheme(self):
        assert utils.make_url("https://example.com/sse") == "https://example.com/sse"

    def test_ip_host_builds_http(self):
        assert utils.make_url("127.0.0.1:8080", "", "sse") == "http://127.0.0.1:8080/sse"

    def test_service_name_builds_polaris(self):
        assert utils.make_url("my.service", "", "sse") == "polaris://my.service/sse"


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
        assert ctx.meta_data[http_defines.HTTP_ARGS_META_KEY] == {"q": "1"}

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

    def test_raises_when_missing(self):
        proc = multiprocessing.current_process()
        had = hasattr(proc, "mcp_app")
        saved = getattr(proc, "mcp_app", None)
        if had:
            delattr(proc, "mcp_app")
        try:
            with pytest.raises(ValueError):
                utils.get_mcp_app()
        finally:
            if had:
                proc.mcp_app = saved

    def test_returns_app_when_present(self):
        proc = multiprocessing.current_process()
        sentinel = object()
        proc.mcp_app = sentinel
        try:
            assert utils.get_mcp_app() is sentinel
        finally:
            delattr(proc, "mcp_app")
