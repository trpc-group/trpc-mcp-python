# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Logging bridge for routing MCP stack logs through TRPC logging.

trpc_sdk captures stdlib ``logging`` with an ``InterceptHandler`` on the root
logger when a log output sets ``capture_third_party: true`` (or
``TRPC_LOG_INTERCEPT`` is set). This module only makes the MCP stack loggers
reach that root handler, with their package name prefixed to each message.
"""

import logging

_LOGGER_NAMES = (
    "mcp",
    "mcp.server",
    "mcp.server.fastmcp",
    "mcp.server.lowlevel",
    "mcp.server.sse",
    "mcp.server.streamable_http",
    "sse_starlette",
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "redis",
)

_PREFIX_FILTER_MARKER = "_trpc_mcp_package_prefix_filter"
_PREFIXED_RECORD_MARKER = "_trpc_mcp_package_prefixed"


class _PackagePrefixFilter(logging.Filter):
    """Prefix third-party log messages with their logger package name."""

    @staticmethod
    def _is_trpc_record(logger_name: str) -> bool:
        return logger_name.startswith("trpc")

    def filter(self, record: logging.LogRecord) -> bool:
        logger_name = record.name
        if self._is_trpc_record(logger_name):
            return True
        if getattr(record, _PREFIXED_RECORD_MARKER, False):
            return True

        message = record.getMessage()
        # Only keep the top-level package name as the prefix, e.g.
        # "uvicorn.error"/"uvicorn.access" -> "uvicorn", "mcp.server.sse" -> "mcp".
        # This avoids misleading tokens like "error" in the logger name being
        # mistaken for an error level by downstream/LLM log analysis.
        package = logger_name.split(".", 1)[0] or logger_name
        record.msg = f"[{package}] {message}"
        record.args = ()
        setattr(record, _PREFIXED_RECORD_MARKER, True)
        return True


def _install_prefix_filter(target: logging.Filterer) -> None:
    if any(getattr(item, _PREFIX_FILTER_MARKER, False) for item in target.filters):
        return
    prefix_filter = _PackagePrefixFilter()
    setattr(prefix_filter, _PREFIX_FILTER_MARKER, True)
    target.addFilter(prefix_filter)


def _install_handler_filters(handlers: list[logging.Handler]) -> None:
    for handler in handlers:
        _install_prefix_filter(handler)


def bridge_third_party_loggers(level: int | None = None) -> None:
    """Route MCP/uvicorn/Redis Python logging into TRPC's logging.

    Each MCP stack logger propagates to the root logger, where trpc_sdk's
    third-party capture picks it up, and gets the package prefix filter.
    Whether the records end up in a TRPC log output is decided by that
    output's ``capture_third_party`` setting.

    Args:
        level: Level to set on the MCP stack loggers; ``None`` leaves them
            inheriting the root level set by trpc_sdk.
    """
    for name in _LOGGER_NAMES:
        target = logging.getLogger(name)
        target.propagate = True
        if level is not None:
            target.setLevel(level)
        _install_prefix_filter(target)
