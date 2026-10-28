# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Tests for trpc_mcp._logging."""

import logging

from trpc_mcp._logging import (
    _LOGGER_NAMES,
    _PREFIX_FILTER_MARKER,
    _PREFIXED_RECORD_MARKER,
    _PackagePrefixFilter,
    _install_handler_filters,
    bridge_third_party_loggers,
)


def _make_record(name, msg="hello"):
    return logging.LogRecord(name, logging.INFO, __file__, 1, msg, None, None)


class TestIsTrpcRecord:

    def test_trpc_prefix(self):
        assert _PackagePrefixFilter._is_trpc_record("trpc.foo") is True
        assert _PackagePrefixFilter._is_trpc_record("trpc_mcp.bar") is True
        assert _PackagePrefixFilter._is_trpc_record("trpc_sdk.log") is True

    def test_non_trpc(self):
        assert _PackagePrefixFilter._is_trpc_record("uvicorn.error") is False


class TestFilter:

    def test_trpc_record_passes_unchanged(self):
        flt = _PackagePrefixFilter()
        record = _make_record("trpc.core")
        assert flt.filter(record) is True
        assert record.getMessage() == "hello"

    def test_already_prefixed_record_passes(self):
        flt = _PackagePrefixFilter()
        record = _make_record("uvicorn.error")
        setattr(record, _PREFIXED_RECORD_MARKER, True)
        assert flt.filter(record) is True
        # not re-prefixed
        assert record.getMessage() == "hello"

    def test_third_party_record_prefixed(self):
        flt = _PackagePrefixFilter()
        record = _make_record("uvicorn.error", "boom")
        assert flt.filter(record) is True
        assert record.getMessage() == "[uvicorn] boom"
        assert getattr(record, _PREFIXED_RECORD_MARKER) is True


class TestInstallHandlerFilters:

    def test_skips_handler_with_existing_marker(self):
        handler = logging.NullHandler()
        existing = logging.Filter()
        setattr(existing, _PREFIX_FILTER_MARKER, True)
        handler.addFilter(existing)
        _install_handler_filters([handler])
        # No additional marker filter should be added.
        markers = [f for f in handler.filters if getattr(f, _PREFIX_FILTER_MARKER, False)]
        assert len(markers) == 1

    def test_adds_marker_to_bare_handler(self):
        handler = logging.NullHandler()
        _install_handler_filters([handler])
        markers = [f for f in handler.filters if getattr(f, _PREFIX_FILTER_MARKER, False)]
        assert len(markers) == 1


class TestBridge:

    @staticmethod
    def _markers(target):
        return [f for f in target.filters if getattr(f, _PREFIX_FILTER_MARKER, False)]

    def test_loggers_propagate_with_one_prefix_filter(self):
        logging.getLogger("uvicorn.error").propagate = False
        bridge_third_party_loggers()
        bridge_third_party_loggers()
        for name in _LOGGER_NAMES:
            target = logging.getLogger(name)
            assert target.propagate is True
            assert len(self._markers(target)) == 1

    def test_root_logger_untouched(self):
        root = logging.getLogger()
        level = root.level
        bridge_third_party_loggers(level=logging.DEBUG)
        assert root.level == level
        assert self._markers(root) == []

    def test_level_applied(self):
        mcp_logger = logging.getLogger("mcp")
        saved = mcp_logger.level
        try:
            bridge_third_party_loggers(level=logging.DEBUG)
            assert mcp_logger.level == logging.DEBUG
        finally:
            mcp_logger.setLevel(saved)
