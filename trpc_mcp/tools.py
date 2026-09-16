# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com
"""
TRPC MCP Tools Module

This module provides tool management functionality for TRPC MCP (Microservice Control Protocol).
It includes tool registration, description and related utilities.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from mcp.types import AnyFunction
from mcp.types import ToolAnnotations
from mcp.types import CallToolResult

from trpc.context import TrpcContext
from trpc.utils.singleton import singleton

from ._compat import Icon
from ._constants import MCP_DEFAULT_SERVICE


@dataclass(frozen=True)
class ToolDescription:
    """Description of a registered tool.

    Attributes:
        fn: The function implementing the tool
        name: Name of the tool
        description: Description of the tool's functionality
    """
    __slots__ = ("fn", "name", "title", "annotations", "structured_output", "description", "icons", "meta")

    description: str
    name: str
    title: str
    annotations: ToolAnnotations
    structured_output: bool
    fn: Callable
    icons: list[Icon] | None
    meta: dict[str, Any] | None


_tools_cache: dict[str, list[ToolDescription]] = {}


def get_tools(mcp_name: str = MCP_DEFAULT_SERVICE) -> list[ToolDescription]:
    """Get all registered tools for a specific MCP service.

    Args:
        mcp_name: Name of the MCP service (defaults to default service)

    Returns:
        List of ToolDescription objects for the specified service
    """
    return _tools_cache.get(mcp_name, [])


def get_all_tools() -> list[ToolDescription]:
    """Get all registered tools across all MCP services.

    Returns:
        Combined list of all ToolDescription objects from all services
    """
    all_tools = []
    for tools in _tools_cache.values():
        all_tools.extend(tools)
    return all_tools


def tool(name: str | None = None,
         description: str | None = None,
         title: str | None = None,
         structured_output: bool | None = None,
         annotations: ToolAnnotations | None = None,
         icons: list[Icon] | None = None,
         meta: dict[str, Any] | None = None,
         mcp_name: str = MCP_DEFAULT_SERVICE) -> Callable[[AnyFunction], AnyFunction]:
    """Decorator to register a tool with the MCP framework.

    Tools can optionally request a Context object by adding a parameter with the
    Context type annotation. The context provides access to MCP capabilities like
    logging, progress reporting, and resource access.

    Args:
        name: Optional name for the tool (defaults to function name)
        description: Optional description of what the tool does
        title: Optional title for the tool (defaults to function name)
        structured_output: Optional structured output for the tool (defaults to False)
        annotations: Optional annotations for the tool (defaults to None)
        icons: Optional list of icons for the tool (SEP-973, defaults to None)
        meta: Optional metadata dict for the tool, e.g. for OpenAI Apps (defaults to None)
        mcp_name: Name of the MCP service to register with (defaults to default service)

    Returns:
        A decorator function that registers the tool

    Example:
        @trpc_mcp.tool()
        def my_tool(trpc_ctx: TrpcContext, x: int) -> str:
            return str(x)

        @trpc_mcp.tool()
        def tool_with_context(trpc_ctx: TrpcContext, x: int, ctx: Context) -> str:
            ctx.info(f"Processing {x}")
            return str(x)

        @trpc_mcp.tool()
        async def async_tool(trpc_ctx: TrpcContext, x: int, context: Context) -> str:
            await context.report_progress(trpc_ctx, 50, 100)
            return str(x)
    """

    def decorator(fn: AnyFunction) -> AnyFunction:
        item = ToolDescription(description=description,
                               name=name,
                               fn=fn,
                               title=title,
                               annotations=annotations,
                               structured_output=structured_output,
                               icons=icons,
                               meta=meta)

        if mcp_name not in _tools_cache:
            _tools_cache[mcp_name] = []
        _tools_cache[mcp_name].append(item)
        return fn

    return decorator


@dataclass
class ToolFilterParams:
    """Parameters for tool filter operations.

    Attributes:
        name: Name of the tool being filtered
        arguments: Dictionary of arguments for the tool
        result: Result of the tool call (set after execution)
    """
    name: str = ""
    arguments: dict = field(default_factory=dict)
    result: CallToolResult = None


CallToolCallback = Callable[[], Any]


class ToolFilterBase(ABC):
    """Abstract base class for tool filters.

    Tool filters allow pre- and post-processing of tool calls.
    Implementations must override pre_call and post_call methods.
    """

    def __init__(self) -> None:
        """Initialize the filter with an empty name."""
        self._name = ""

    @property
    def name(self):
        """Get the name of this filter.

        Returns:
            str: The filter's name
        """
        return self._name

    @abstractmethod
    async def pre_call(self, ctx: TrpcContext, params: ToolFilterParams) -> bool:
        """Pre-call hook executed before tool invocation.

        Args:
            ctx: TRPC context object
            params: Tool filter parameters

        Returns:
            bool: True to continue execution, False to abort
        """
        ...

    @abstractmethod
    async def post_call(self, ctx: TrpcContext, params: ToolFilterParams) -> bool:
        """Post-call hook executed after tool invocation.

        Args:
            ctx: TRPC context object
            params: Tool filter parameters (contains result)

        Returns:
            bool: True to continue, False to indicate error
        """
        ...


@singleton
class _ToolFilterManager:
    """Manager for tool filters with singleton pattern.

    Handles registration and execution of tool filters.
    """

    def __init__(self) -> None:
        """Initialize with empty filter dictionary."""
        self._filters: dict[str, ToolFilterBase] = {}

    def register(self, filter: ToolFilterBase):
        """Register a new tool filter.

        Args:
            filter: Tool filter instance to register
        """
        self._filters[filter.name] = filter

    def get(self, name: str) -> ToolFilterBase:
        """Get a registered filter by name.

        Args:
            name: Name of the filter to retrieve

        Returns:
            ToolFilterBase: The filter instance or None if not found
        """
        return self._filters.get(name, None)

    async def run(self, ctx: TrpcContext, params: ToolFilterParams, cb: CallToolCallback) -> CallToolResult:
        """Execute a tool call with filter processing.

        Args:
            ctx: TRPC context object
            params: Tool filter parameters
            cb: Callback function that executes the actual tool

        Returns:
            CallToolResult: Result of the tool execution

        Raises:
            ValueError: If pre_call or post_call filters fail
        """
        if params.name not in self._filters:
            return await cb()

        filter = self._filters[params.name]
        ret = await filter.pre_call(ctx, params)
        if ret is False:
            raise ValueError(f"Run tool filter error by {params.name} in pre_call")

        params.result = await cb()

        ret = await filter.post_call(ctx, params)
        if ret is False:
            raise ValueError(f"Run tool filter error by {params.name} in post_call")
        return params.result


def register_tool_filter(cls: type[ToolFilterBase] = None, force: bool = False):
    """Decorator to register a tool filter class.

    Can be used as:
        @register_tool_filter
        class MyFilter(ToolFilterBase):
            ...

    or:
        @register_tool_filter(force=True)
        class MyFilter(ToolFilterBase):
            ...

    Args:
        cls: Tool filter class to register
        force: Whether to force registration if name exists (default: False)

    Returns:
        The decorated class or decorator function

    Raises:
        TypeError: If filter name already exists and force=False
    """

    def decorator(cls: type[ToolFilterBase]) -> AnyFunction:
        """Inner decorator function that handles registration."""
        manager = _ToolFilterManager()
        filter_instance = cls()
        if filter_instance.name in manager._filters:
            if force:
                manager.register(filter_instance)
            else:
                raise TypeError(f"Tool filter {filter_instance.name} already exists")
        else:
            manager.register(filter_instance)
        return cls

    if cls is None:
        return decorator
    return decorator(cls)


async def run_filters(ctx: TrpcContext, params: ToolFilterParams, cb: CallToolCallback) -> CallToolResult:
    """Execute tool call with all registered filters.

    This is a convenience wrapper around _ToolFilterManager.run() that creates
    a manager instance and delegates the execution to it.

    Args:
        ctx: TRPC context object
        params: Tool filter parameters including tool name and arguments
        cb: Callback function that executes the actual tool logic

    Returns:
        CallToolResult: Result of the tool execution after filter processing

    Note:
        This function will propagate any exceptions raised by the filters or callback.
    """
    manager = _ToolFilterManager()
    return await manager.run(ctx, params, cb)
