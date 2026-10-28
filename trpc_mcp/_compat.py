# Tencent is pleased to support the open source community by making tRPC-MCP-Python available.
#
# Copyright (C) 2026 Tencent. All rights reserved.
#
# tRPC-MCP-Python is licensed under Apache-2.0.
"""Compatibility shims for optional ``mcp.types`` symbols.

Some types were added to the official SDK after our minimum supported version
(``mcp>=1.11.0``):

- ``Icon``        - added in mcp 1.13.0 (SEP-973).
- ``Annotations`` - present since early mcp, shimmed defensively for safety.

Importing them at module top level would raise ``ImportError`` on older-but-still
-supported versions and break the whole package on import. We therefore import
them lazily here with a fallback to ``Any`` so type hints stay valid and the
features simply degrade (registration already filters unsupported kwargs via
``_forward_supported_kwargs``).
"""

from typing import Any

try:
    from mcp.types import Icon  # noqa: F401  (re-exported)
except ImportError:  # pragma: no cover - older mcp without SEP-973
    Icon = Any  # type: ignore[assignment,misc]

try:
    from mcp.types import Annotations  # noqa: F401  (re-exported)
except ImportError:  # pragma: no cover - extremely old mcp
    Annotations = Any  # type: ignore[assignment,misc]
