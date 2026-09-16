# -*- coding: utf-8 -*-
"""Shared pytest fixtures and helpers for the trpc_mcp test suite."""

import asyncio
from typing import Any

import pytest

from trpc_mcp import prompts as prompts_mod
from trpc_mcp import resources as resources_mod
from trpc_mcp import tools as tools_mod


def run(coro: Any) -> Any:
    """Run a coroutine to completion on a fresh event loop.

    Using ``asyncio.run`` keeps async tests self-contained and avoids depending
    on a particular pytest-asyncio mode/configuration.
    """
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clear_registration_caches():
    """Reset the module-level decorator caches around every test.

    The ``tool``/``resource``/``prompt`` decorators append into process-wide
    caches; without this fixture, registrations would leak across tests.
    """
    tools_mod._tools_cache.clear()
    resources_mod._resources_cache.clear()
    prompts_mod._prompts_cache.clear()
    yield
    tools_mod._tools_cache.clear()
    resources_mod._resources_cache.clear()
    prompts_mod._prompts_cache.clear()


class FakeContext:
    """Lightweight stand-in for ``trpc.context.TrpcContext``.

    Implements just the surface (``meta_data`` + ``with_meta_data`` +
    ``get_meta_data``) used by the modules under test.
    """

    def __init__(self) -> None:
        self.meta_data: dict = {}
        self.remote_ip = "1.2.3.4"
        self.deadline = 0
        self.timeout = 0
        self.recv_time = 0.0
        self.msg = None

    def with_meta_data(self, key, value):
        self.meta_data[key] = value
        return self

    def get_meta_data(self, key, default=None):
        return self.meta_data.get(key, default)


@pytest.fixture
def fake_ctx() -> FakeContext:
    return FakeContext()
