# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com
"""MCP tools module"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp.types import AnyFunction

from ._compat import Annotations
from ._compat import Icon
from ._constants import MCP_DEFAULT_SERVICE


@dataclass(frozen=True)
class ResourceDescription:
    """Description of a registered resource.

    Attributes:
        name: Name of the resource
        description: Description of the resource
        mime_type: MIME type of the resource content
        uri: URI identifier for the resource
        fn: The function implementing the resource
    """
    __slots__ = ("name", "title", "description", "mime_type", "uri", "fn", "icons", "annotations", "meta")

    name: str
    title: str
    description: str
    mime_type: str
    uri: str
    fn: Callable
    icons: list[Icon] | None
    annotations: Annotations | None
    meta: dict[str, Any] | None


_resources_cache: dict[str, list[ResourceDescription]] = {}


def get_resources(mcp_name: str = MCP_DEFAULT_SERVICE) -> list[ResourceDescription]:
    """Get all registered resources for a specific MCP service.

    Args:
        mcp_name: Name of the MCP service (defaults to default service)

    Returns:
        List of ResourceDescription objects for the specified service
    """
    return _resources_cache.get(mcp_name, [])


def get_all_resources() -> list[ResourceDescription]:
    """Get all registered resources across all MCP services.

    Returns:
        Combined list of all ResourceDescription objects from all services
    """
    all_resources = []
    for resources in _resources_cache.values():
        all_resources.extend(resources)
    return all_resources


def resource(uri: str,
             *,
             name: str | None = None,
             title: str | None = None,
             description: str | None = None,
             mime_type: str | None = None,
             icons: list[Icon] | None = None,
             annotations: Annotations | None = None,
             meta: dict[str, Any] | None = None,
             mcp_name: str = MCP_DEFAULT_SERVICE):
    """Decorator to register a function as a resource with the MCP framework.

    The function will be called when the resource is read to generate its content.
    The function can return:
    - str for text content
    - bytes for binary content
    - other types will be converted to JSON

    If the URI contains parameters (e.g. "resource://{param}") or the function
    has parameters, it will be registered as a template resource.

    Args:
        uri: URI for the resource (e.g. "resource://my-resource" or "resource://{param}")
        name: Optional name for the resource
        title: Optional title for the resource
        description: Optional description of the resource
        mime_type: Optional MIME type for the resource
        icons: Optional list of icons for the resource (SEP-973, defaults to None)
        annotations: Optional annotations for the resource (defaults to None)
        meta: Optional metadata dict for the resource (defaults to None)
        mcp_name: Name of the MCP service to register with (defaults to default service)

    Returns:
        A decorator function that registers the resource

    Example:
        @trpc_mcp.resource("resource://my-resource")
        def get_data(ctx: TrpcContext) -> str:
            return "Hello, world!"

        @trpc_mcp.resource("resource://my-resource")
        async get_data(ctx: TrpcContext) -> str:
            data = await fetch_data()
            return f"Hello, world! {data}"

        @trpc_mcp.resource("resource://{city}/weather")
        def get_weather(ctx: TrpcContext, city: str) -> str:
            return f"Weather for {city}"

        @trpc_mcp.resource("resource://{city}/weather")
        async def get_weather(ctx: TrpcContext, city: str) -> str:
            data = await fetch_weather(city)
            return f"Weather for {city}: {data}"
    """

    def decorator(fn: AnyFunction) -> AnyFunction:
        resource_desc = ResourceDescription(uri=uri,
                                            fn=fn,
                                            name=name,
                                            title=title,
                                            description=description,
                                            mime_type=mime_type,
                                            icons=icons,
                                            annotations=annotations,
                                            meta=meta)
        if mcp_name not in _resources_cache:
            _resources_cache[mcp_name] = []
        _resources_cache[mcp_name].append(resource_desc)
        return fn

    return decorator
