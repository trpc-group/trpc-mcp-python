# -*- coding: utf-8 -*-
#
# Copyright @ 2025 Tencent.com
"""Smoke tests for the example MCP callbacks using the official MCP SDK client.

This script intentionally uses the official MCP SDK client instead of internal
test helpers, so the assertions below verify the same protocol surface that a
real MCP client or LLM host will see.

Before running this script, start the example server with a matching transport:

    # SSE, multi-service example.
    venv/bin/python examples/trpc_main.py \
        --conf examples/trpc_python.yaml
    venv/bin/python examples/test_official_mcp_client.py \
        --transport sse \
        --service trpc.test.mcp.Greeter1=127.0.0.1:8008 \
        --service trpc.test.mcp.Greeter2=127.0.0.1:8009

    # Streamable HTTP, single-service example.
    venv/bin/python examples/trpc_main.py \
        --conf examples/trpc_python_streamable_http.yaml
    venv/bin/python examples/test_official_mcp_client.py \
        --transport streamable-http \
        --service trpc.test.mcp.Greeter1=127.0.0.1:8008
"""

import argparse
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.context import RequestContext
from mcp.shared.exceptions import McpError
from pydantic import FileUrl

DEFAULT_SERVICES = {
    "trpc.test.mcp.Greeter1": "127.0.0.1:8008",
    "trpc.test.mcp.Greeter2": "127.0.0.1:8009",
}
DEFAULT_STREAMABLE_HTTP_SERVICES = {
    "trpc.test.mcp.Greeter1": "127.0.0.1:8008",
}
COMMON_TOOLS = {"add", "allowed_directories", "common_tool"}
SERVICE_TOOLS = {
    "trpc.test.mcp.Greeter1": {"echo_tool", "get_weather", "show_tool"},
    "trpc.test.mcp.Greeter2": {"shell_tool"},
}
COMMON_RESOURCE_TEMPLATES = {"common://{data}"}
SERVICE_RESOURCES = {
    "trpc.test.mcp.Greeter1": {"echo://static"},
    "trpc.test.mcp.Greeter2": set(),
}
SERVICE_RESOURCE_TEMPLATES = {
    "trpc.test.mcp.Greeter1": set(),
    "trpc.test.mcp.Greeter2": {"template://{text}"},
}
COMMON_PROMPTS = {"common_prompt"}
SERVICE_PROMPTS = {
    "trpc.test.mcp.Greeter1": {"echo_prompt"},
    "trpc.test.mcp.Greeter2": {"show_prompt"},
}
ROOT_URIS = (
    "file:///tmp/trpc-mcp-sdk-root-a",
    "file:///tmp/trpc-mcp-sdk-root-b",
)


async def _list_roots_callback(context: RequestContext) -> types.ListRootsResult | types.ErrorData:
    """Return client-approved roots when the server calls roots/list."""
    # The `allowed_directories` tool calls MCP roots/list from server to client.
    # This callback simulates a real MCP host that grants the server access to
    # a limited set of local directories. The tool test later verifies these
    # URIs are returned, proving server-initiated client requests work.
    return types.ListRootsResult(roots=[
        types.Root(uri=FileUrl(uri), name=f"official-sdk-root-{index}") for index, uri in enumerate(ROOT_URIS, start=1)
    ])


def _is_expected_sse_close_error(exc: BaseException) -> bool:
    if isinstance(exc, BaseExceptionGroup):
        return all(_is_expected_sse_close_error(item) for item in exc.exceptions)
    return "incomplete chunked read" in str(exc)


def _endpoint(host: str, transport: str) -> str:
    path = "sse" if transport == "sse" else "mcp"
    if host.startswith(("http://", "https://")):
        return f"{host.rstrip('/')}/{path}"
    return f"http://{host}/{path}"


@asynccontextmanager
async def _open_session(url: str, transport: str) -> AsyncIterator[ClientSession]:
    if transport == "sse":
        try:
            async with sse_client(url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream,
                                         list_roots_callback=_list_roots_callback) as session:
                    await session.initialize()
                    yield session
        except * Exception as exc_group:
            if not _is_expected_sse_close_error(exc_group):
                raise
        return

    async with streamablehttp_client(url) as (read_stream, write_stream, _get_session_id):
        async with ClientSession(read_stream, write_stream, list_roots_callback=_list_roots_callback) as session:
            await session.initialize()
            yield session


def _text_from_tool_result(result: types.CallToolResult) -> str:
    return "\n".join(content.text for content in result.content if isinstance(content, types.TextContent))


def _text_from_resource_result(result: types.ReadResourceResult) -> str:
    return "\n".join(content.text for content in result.contents if isinstance(content, types.TextResourceContents))


async def _assert_mcp_error(awaitable) -> None:
    """Assert an MCP operation failed through either SDK exception or isError."""
    # Different MCP paths surface failures differently:
    # - protocol/request failures can raise McpError;
    # - tool calls can return CallToolResult(isError=True).
    # Treat both as valid negative-test outcomes.
    try:
        result = await awaitable
    except McpError:
        return
    assert getattr(result, "isError", False), result


def _other_service_tools(service_name: str) -> set[str]:
    tools = set()
    for name, service_tools in SERVICE_TOOLS.items():
        if name != service_name:
            tools.update(service_tools)
    return tools


def _other_service_resources(service_name: str) -> set[str]:
    resources = set()
    for name, service_resources in SERVICE_RESOURCES.items():
        if name != service_name:
            resources.update(service_resources)
    return resources


def _other_service_resource_templates(service_name: str) -> set[str]:
    templates = set()
    for name, service_templates in SERVICE_RESOURCE_TEMPLATES.items():
        if name != service_name:
            templates.update(service_templates)
    return templates


def _other_service_prompts(service_name: str) -> set[str]:
    prompts = set()
    for name, service_prompts in SERVICE_PROMPTS.items():
        if name != service_name:
            prompts.update(service_prompts)
    return prompts


async def _assert_common_tools(session: ClientSession, tools: dict[str, types.Tool]) -> None:
    # Common tools are registered without binding to a specific service, so they
    # should be listed and callable from every service endpoint.
    assert COMMON_TOOLS.issubset(tools)

    # Parameter annotation test:
    # `add(a, b)` uses Annotated/Field descriptions in the callback. The schema
    # returned by tools/list must include those descriptions so an LLM can better
    # understand what each argument means.
    add_schema = tools["add"].inputSchema
    assert add_schema["properties"]["a"]["description"] == "The first integer addend."
    assert add_schema["properties"]["b"]["description"] == "The second integer addend."

    # Meta passthrough test:
    # `common_tool` returns make_call_tool_result(..., meta=...). The official
    # SDK exposes that data as `result.meta`, so this verifies `_meta` is not
    # dropped by TRPC/MCP conversion.
    common_result = await session.call_tool("common_tool", {"text": "official sdk meta"})
    assert common_result.meta == {"common_tool": "official sdk meta"}
    assert "official sdk meta" in _text_from_tool_result(common_result)

    # Structured output test:
    # `add` has normal text content and a structured output schema. Here we only
    # assert the visible text in the common-tool section; service-specific
    # structuredContent is checked below with `get_weather`.
    add_result = await session.call_tool("add", {"a": 1, "b": 2})
    assert "3" in _text_from_tool_result(add_result)

    # roots/list test:
    # The server-side tool asks the client for allowed roots. The client callback
    # above returns ROOT_URIS, and the tool should echo them back.
    allowed_result = await session.call_tool("allowed_directories", {})
    allowed_text = _text_from_tool_result(allowed_result)
    for uri in ROOT_URIS:
        assert uri in allowed_text


async def _assert_service_tool_calls(session: ClientSession, service_name: str) -> None:
    if service_name == "trpc.test.mcp.Greeter1":
        # Greeter1-only tools should be visible and callable from Greeter1.
        echo_result = await session.call_tool("echo_tool", {"text": "official sdk echo"})
        assert not echo_result.isError
        assert "official sdk echo" in _text_from_tool_result(echo_result)

        # `show_tool` is explicitly bound to Greeter1. Calling it from Greeter2
        # is covered by the negative test in `_assert_tools`.
        show_result = await session.call_tool("show_tool", {"text": "official sdk show"})
        assert not show_result.isError
        assert "official sdk show" in _text_from_tool_result(show_result)

        # Structured output test:
        # `get_weather` returns structuredContent. This verifies the SDK sees
        # typed/structured data, not only text content.
        weather_result = await session.call_tool("get_weather", {"city": "ShenZhen"})
        assert not weather_result.isError
        assert weather_result.structuredContent["location"] == "ShenZhen"
    elif service_name == "trpc.test.mcp.Greeter2":
        # Greeter2-only tool. This also confirms that tools can execute commands
        # and return their output as MCP text content in this example.
        shell_result = await session.call_tool("shell_tool", {"cmd": "printf official-sdk"})
        assert not shell_result.isError
        assert "official-sdk" in _text_from_tool_result(shell_result)


async def _assert_tools(session: ClientSession, service_name: str) -> None:
    result = await session.list_tools()
    tools = {tool.name: tool for tool in result.tools}

    # Visibility test:
    # The current service must list its own tools, while tools bound to other
    # services must not appear in tools/list.
    assert SERVICE_TOOLS[service_name].issubset(tools)
    assert _other_service_tools(service_name).isdisjoint(tools)

    await _assert_common_tools(session, tools)
    await _assert_service_tool_calls(session, service_name)

    # Cross-service negative test:
    # A tool bound to another service should fail when called through the wrong
    # service endpoint. This verifies service isolation in both discovery and
    # execution paths.
    for tool_name in _other_service_tools(service_name):
        await _assert_mcp_error(session.call_tool(tool_name, {}))


async def _assert_resources(session: ClientSession, service_name: str) -> None:
    resources_result = await session.list_resources()
    resource_uris = {str(resource.uri) for resource in resources_result.resources}

    # Resource template discovery test:
    # Common resources registered as URI templates should show up in
    # list_resource_templates, not list_resources.
    assert "common://{data}" not in resource_uris

    templates_result = await session.list_resource_templates()
    template_uris = {template.uriTemplate for template in templates_result.resourceTemplates}

    # Visibility test for static resources and templates. Each service should
    # only see resources/templates bound to itself plus common templates.
    assert COMMON_RESOURCE_TEMPLATES.issubset(template_uris)
    assert SERVICE_RESOURCES[service_name].issubset(resource_uris)
    assert SERVICE_RESOURCE_TEMPLATES[service_name].issubset(template_uris)
    assert _other_service_resources(service_name).isdisjoint(resource_uris)
    assert _other_service_resource_templates(service_name).isdisjoint(template_uris)

    # Common resource template should be readable from every service.
    common_result = await session.read_resource("common://official-sdk")
    assert "official-sdk" in _text_from_resource_result(common_result)

    if service_name == "trpc.test.mcp.Greeter1":
        # Greeter1 can read its static resource, but not Greeter2's template.
        static_result = await session.read_resource("echo://static")
        assert "echo_resource" in _text_from_resource_result(static_result)
        await _assert_mcp_error(session.read_resource("template://official-sdk"))
    elif service_name == "trpc.test.mcp.Greeter2":
        # Greeter2 can read its template resource, but not Greeter1's static one.
        template_result = await session.read_resource("template://official-sdk")
        assert "official-sdk" in _text_from_resource_result(template_result)
        await _assert_mcp_error(session.read_resource("echo://static"))


async def _assert_prompts(session: ClientSession, service_name: str) -> None:
    prompts_result = await session.list_prompts()
    prompt_names = {prompt.name for prompt in prompts_result.prompts}

    # Prompt visibility test:
    # Common prompts are available everywhere; service-bound prompts are only
    # available from their own service endpoint.
    assert COMMON_PROMPTS.issubset(prompt_names)
    assert SERVICE_PROMPTS[service_name].issubset(prompt_names)
    assert _other_service_prompts(service_name).isdisjoint(prompt_names)

    # Common prompt rendering should work from every service.
    common_result = await session.get_prompt("common_prompt", {"prompt": "official sdk prompt"})
    assert "official sdk prompt" in str(common_result.messages)

    if service_name == "trpc.test.mcp.Greeter1":
        # Greeter1 prompt succeeds; Greeter2 prompt is an expected error here.
        echo_result = await session.get_prompt("echo_prompt", {"prompt": "official sdk echo"})
        assert "official sdk echo" in str(echo_result.messages)
        await _assert_mcp_error(session.get_prompt("show_prompt", {"prompt": "wrong service"}))
    elif service_name == "trpc.test.mcp.Greeter2":
        # Greeter2 prompt succeeds; Greeter1 prompt is an expected error here.
        show_result = await session.get_prompt("show_prompt", {"prompt": "official sdk show"})
        assert "official sdk show" in str(show_result.messages)
        await _assert_mcp_error(session.get_prompt("echo_prompt", {"prompt": "wrong service"}))


async def _test_service(service_name: str, host: str, transport: str) -> None:
    url = _endpoint(host, transport)
    # Each service/transport pair gets a fresh MCP session, so initialization,
    # capability discovery and callback behavior are all tested per endpoint.
    async with _open_session(url, transport) as session:
        await _assert_tools(session, service_name)
        await _assert_resources(session, service_name)
        await _assert_prompts(session, service_name)
    print(f"OK {transport} {service_name} {url}")


async def _run(transport: str, services: dict[str, str]) -> None:
    transports = ("sse", "streamable-http") if transport == "both" else (transport, )
    for item in transports:
        for service_name, host in services.items():
            await _test_service(service_name, host, item)


def _parse_services(transport: str, values: list[str] | None) -> dict[str, str]:
    if not values:
        if transport == "streamable-http":
            return DEFAULT_STREAMABLE_HTTP_SERVICES
        return DEFAULT_SERVICES
    services = {}
    for value in values:
        name, host = value.split("=", maxsplit=1)
        services[name] = host
    return services


def main() -> None:
    parser = argparse.ArgumentParser(description="Test MCP callbacks with the official MCP SDK client.")
    parser.add_argument("--transport", choices=("sse", "streamable-http", "both"), default="sse")
    parser.add_argument(
        "--service",
        action="append",
        help="Service mapping in the form service.name=host:port. Can be repeated.",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.transport, _parse_services(args.transport, args.service)))


if __name__ == "__main__":
    main()
