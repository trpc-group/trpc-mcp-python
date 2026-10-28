# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""
TRPC MCP Prompts Module

This module provides prompt management functionality for TRPC MCP (Microservice Control Protocol).
It includes prompt registration, description and related utilities.
"""

from collections.abc import Callable
from dataclasses import dataclass

from mcp.types import AnyFunction

from ._compat import Icon
from ._constants import MCP_DEFAULT_SERVICE


@dataclass(frozen=True)
class PromptDescription:
    """Description of a registered prompt.

    Attributes:
        name: Name of the prompt
        description: Description of the prompt's functionality
        fn: The function implementing the prompt
    """
    __slots__ = ("name", "title", "description", "fn", "icons")

    name: str
    title: str
    description: str
    fn: Callable
    icons: list[Icon] | None


_prompts_cache: dict[str, list[PromptDescription]] = {}


def get_prompts(mcp_name: str = MCP_DEFAULT_SERVICE) -> list[PromptDescription]:
    """Get all registered prompts for a specific MCP service.

    Args:
        mcp_name: Name of the MCP service (defaults to default service)

    Returns:
        List of PromptDescription objects for the specified service
    """
    return _prompts_cache.get(mcp_name, [])


def get_all_prompts() -> list[PromptDescription]:
    """Get all registered prompts across all MCP services.

    Returns:
        Combined list of all PromptDescription objects from all services
    """
    all_prompts = []
    for prompts in _prompts_cache.values():
        all_prompts.extend(prompts)
    return all_prompts


def prompt(name: str | None = None,
           title: str | None = None,
           description: str | None = None,
           icons: list[Icon] | None = None,
           mcp_name: str = MCP_DEFAULT_SERVICE):
    """Decorator to register a prompt with the MCP framework.

    Registered prompts can be used to generate structured messages for LLM interactions.
    The decorated function should return a list of Message objects.

    Args:
        name: Optional name for the prompt (defaults to function name)
        title: Optional title for the prompt (defaults to function name)
        description: Optional description of what the prompt does
        icons: Optional list of icons for the prompt (SEP-973, defaults to None)
        mcp_name: Name of the MCP service to register with (defaults to default service)

    Returns:
        A decorator function that registers the prompt

    Example:
        @trpc_mcp.prompt()
        def analyze_table(ctx: TrpcContext, table_name: str) -> list[Message]:
            schema = read_table_schema(table_name)
            return [
                {
                    "role": "user",
                    "content": f"Analyze this schema:\n{schema}"
                }
            ]

        @trpc_mcp.prompt()
        async def analyze_file(ctx: TrpcContext, path: str) -> list[Message]:
            content = await read_file(path)
            return [
                {
                    "role": "user",
                    "content": {
                        "type": "resource",
                        "resource": {
                            "uri": f"file://{path}",
                            "text": content
                        }
                    }
                }
            ]
    """

    def decorator(fn: AnyFunction) -> AnyFunction:
        resource_desc = PromptDescription(fn=fn, name=name, title=title, description=description, icons=icons)

        if mcp_name not in _prompts_cache:
            _prompts_cache[mcp_name] = []
        _prompts_cache[mcp_name].append(resource_desc)
        return fn

    return decorator
