# -*- coding: utf-8 -*-
"""Tests for trpc_mcp.tools."""

import pytest
from mcp.types import CallToolResult, TextContent

from trpc_mcp import tools as tools_mod
from trpc_mcp.tools import (
    ToolDescription,
    ToolFilterBase,
    ToolFilterParams,
    _ToolFilterManager,
    get_all_tools,
    get_tools,
    register_tool_filter,
    run_filters,
    tool,
)

from conftest import run


def _ok_result():
    return CallToolResult(content=[TextContent(type="text", text="ok")])


class TestToolDecorator:

    def test_register_default_service(self):

        @tool()
        def my_tool(ctx, x: int) -> int:
            return x

        items = get_tools()
        assert len(items) == 1
        assert isinstance(items[0], ToolDescription)
        assert items[0].fn is my_tool

    def test_register_custom_service_and_metadata(self):

        @tool(name="named", description="d", title="t", mcp_name="svc1")
        def my_tool(ctx):
            return 1

        assert get_tools("svc1")[0].name == "named"
        assert get_tools("svc1")[0].description == "d"
        # default service unaffected
        assert get_tools() == []

    def test_get_all_tools_combines_services(self):

        @tool(mcp_name="a")
        def t1(ctx):
            return 1

        @tool(mcp_name="b")
        def t2(ctx):
            return 2

        names = {t.fn.__name__ for t in get_all_tools()}
        assert names == {"t1", "t2"}

    def test_get_tools_unknown_service_empty(self):
        assert get_tools("does-not-exist") == []


class TestToolFilterParams:

    def test_defaults(self):
        params = ToolFilterParams()
        assert params.name == ""
        assert params.arguments == {}
        assert params.result is None


class _RecordingFilter(ToolFilterBase):

    def __init__(self, name, pre=True, post=True):
        super().__init__()
        self._name = name
        self._pre = pre
        self._post = post
        self.pre_called = False
        self.post_called = False

    async def pre_call(self, ctx, params):
        self.pre_called = True
        return self._pre

    async def post_call(self, ctx, params):
        self.post_called = True
        return self._post


class TestToolFilterManager:

    def setup_method(self):
        # Reset the singleton's registry between tests.
        _ToolFilterManager()._filters.clear()

    def test_run_without_registered_filter_calls_cb(self):
        mgr = _ToolFilterManager()
        params = ToolFilterParams(name="no-filter")
        result = run(mgr.run(None, params, _ok_result_cb()))
        assert isinstance(result, CallToolResult)

    def test_run_with_filter_pre_post_ok(self):
        mgr = _ToolFilterManager()
        flt = _RecordingFilter("tool-x")
        mgr.register(flt)
        params = ToolFilterParams(name="tool-x")
        result = run(mgr.run(None, params, _ok_result_cb()))
        assert flt.pre_called and flt.post_called
        assert params.result is result

    def test_run_pre_call_failure_raises(self):
        mgr = _ToolFilterManager()
        mgr.register(_RecordingFilter("tool-x", pre=False))
        with pytest.raises(ValueError, match="pre_call"):
            run(mgr.run(None, ToolFilterParams(name="tool-x"), _ok_result_cb()))

    def test_run_post_call_failure_raises(self):
        mgr = _ToolFilterManager()
        mgr.register(_RecordingFilter("tool-x", post=False))
        with pytest.raises(ValueError, match="post_call"):
            run(mgr.run(None, ToolFilterParams(name="tool-x"), _ok_result_cb()))

    def test_get_returns_none_for_missing(self):
        assert _ToolFilterManager().get("missing") is None

    def test_run_filters_convenience(self):
        _ToolFilterManager()._filters.clear()
        result = run(run_filters(None, ToolFilterParams(name="nope"), _ok_result_cb()))
        assert isinstance(result, CallToolResult)


class TestRegisterToolFilter:

    def setup_method(self):
        _ToolFilterManager()._filters.clear()

    def test_register_bare_decorator(self):

        @register_tool_filter
        class F(ToolFilterBase):

            def __init__(self):
                super().__init__()
                self._name = "bare"

            async def pre_call(self, ctx, params):
                return True

            async def post_call(self, ctx, params):
                return True

        assert _ToolFilterManager().get("bare") is not None

    def test_register_duplicate_raises_without_force(self):

        def make():

            @register_tool_filter
            class F(ToolFilterBase):

                def __init__(self):
                    super().__init__()
                    self._name = "dup"

                async def pre_call(self, ctx, params):
                    return True

                async def post_call(self, ctx, params):
                    return True

            return F

        make()
        with pytest.raises(TypeError, match="already exists"):
            make()

    def test_register_duplicate_with_force(self):

        @register_tool_filter
        class F1(ToolFilterBase):

            def __init__(self):
                super().__init__()
                self._name = "force"

            async def pre_call(self, ctx, params):
                return True

            async def post_call(self, ctx, params):
                return True

        @register_tool_filter(force=True)
        class F2(ToolFilterBase):

            def __init__(self):
                super().__init__()
                self._name = "force"

            async def pre_call(self, ctx, params):
                return True

            async def post_call(self, ctx, params):
                return True

        assert isinstance(_ToolFilterManager().get("force"), F2)


def _ok_result_cb():

    async def cb():
        return _ok_result()

    return cb
