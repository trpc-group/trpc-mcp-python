# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Tests for trpc_mcp.resources, trpc_mcp.prompts, _compat, defines, version."""

from trpc_mcp import prompts as prompts_mod
from trpc_mcp import resources as resources_mod
from trpc_mcp.prompts import PromptDescription, get_all_prompts, get_prompts, prompt
from trpc_mcp.resources import (
    ResourceDescription,
    get_all_resources,
    get_resources,
    resource,
)


class TestResourceDecorator:

    def test_register_default(self):

        @resource("res://a", name="a", mime_type="text/plain")
        def get_a(ctx):
            return "a"

        items = get_resources()
        assert len(items) == 1
        assert isinstance(items[0], ResourceDescription)
        assert items[0].uri == "res://a"
        assert items[0].name == "a"
        assert items[0].mime_type == "text/plain"

    def test_register_custom_service(self):

        @resource("res://b", mcp_name="svc")
        def get_b(ctx):
            return "b"

        assert get_resources("svc")[0].uri == "res://b"
        assert get_resources() == []

    def test_get_all_resources(self):

        @resource("res://x", mcp_name="a")
        def gx(ctx):
            return "x"

        @resource("res://y", mcp_name="b")
        def gy(ctx):
            return "y"

        uris = {r.uri for r in get_all_resources()}
        assert uris == {"res://x", "res://y"}

    def test_unknown_service_empty(self):
        assert get_resources("missing") == []


class TestPromptDecorator:

    def test_register_default(self):

        @prompt(name="p", description="d")
        def my_prompt(ctx):
            return []

        items = get_prompts()
        assert len(items) == 1
        assert isinstance(items[0], PromptDescription)
        assert items[0].name == "p"
        assert items[0].description == "d"

    def test_register_custom_service(self):

        @prompt(mcp_name="svc")
        def my_prompt(ctx):
            return []

        assert len(get_prompts("svc")) == 1
        assert get_prompts() == []

    def test_get_all_prompts(self):

        @prompt(mcp_name="a")
        def pa(ctx):
            return []

        @prompt(mcp_name="b")
        def pb(ctx):
            return []

        names = {p.fn.__name__ for p in get_all_prompts()}
        assert names == {"pa", "pb"}

    def test_unknown_service_empty(self):
        assert get_prompts("missing") == []


class TestCompat:

    def test_icon_and_annotations_exported(self):
        from trpc_mcp import _compat

        # Either the real mcp types or the ``Any`` fallback are valid.
        assert _compat.Icon is not None
        assert _compat.Annotations is not None


class TestDefinesAndVersion:

    def test_defines_reexports_constants(self):
        from trpc_mcp import defines

        assert defines.MCP_SSE == "sse"
        assert defines.TRPC_MCP_PROTOCOL == "http_mcp"

    def test_version(self):
        from trpc_mcp.version import __version__

        assert isinstance(__version__, str)
        assert __version__.count(".") >= 2
