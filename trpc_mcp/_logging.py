# -*- coding: utf-8 -*-
"""Logging bridge for routing MCP stack logs through TRPC logging."""

import logging

from trpc.log import logger as trpc_logger

_LOGGER_NAMES = (
    "",
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
        if logger_name.startswith(("trpc", "trpc_mcp")):
            return True
        for logger_instance in getattr(trpc_logger, "GlobalLogger", {}).values():
            filename = getattr(logger_instance, "filename", None)
            if filename and logger_name == filename:
                return True
        return False

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


def _trpc_python_handlers() -> list[logging.Handler]:
    """Return handlers configured by the TRPC default logger."""
    default_logger = getattr(trpc_logger, "DefaultLogger", None)
    python_logger = getattr(default_logger, "logger", None)
    handlers = list(getattr(python_logger, "handlers", []) or [])
    return handlers


def _install_handlers(target: logging.Logger, handlers: list[logging.Handler], level: int) -> None:
    target.handlers = list(handlers)
    target.setLevel(level)
    target.propagate = False
    if not any(getattr(item, _PREFIX_FILTER_MARKER, False) for item in target.filters):
        prefix_filter = _PackagePrefixFilter()
        setattr(prefix_filter, _PREFIX_FILTER_MARKER, True)
        target.addFilter(prefix_filter)


def _install_handler_filters(handlers: list[logging.Handler]) -> None:
    for handler in handlers:
        if any(getattr(item, _PREFIX_FILTER_MARKER, False) for item in handler.filters):
            continue
        prefix_filter = _PackagePrefixFilter()
        setattr(prefix_filter, _PREFIX_FILTER_MARKER, True)
        handler.addFilter(prefix_filter)


def bridge_third_party_loggers(level: int | None = None) -> None:
    """Route MCP/uvicorn/Redis Python logging into TRPC's logging handlers."""
    handlers = _trpc_python_handlers()
    if not handlers:
        return
    _install_handler_filters(handlers)

    log_level = level
    if log_level is None:
        default_logger = getattr(trpc_logger, "DefaultLogger", None)
        log_level = getattr(default_logger, "min_level", logging.INFO)

    for name in _LOGGER_NAMES:
        _install_handlers(logging.getLogger(name), handlers, log_level)
