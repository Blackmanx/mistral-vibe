"""Backends opened by the backend-contract fixtures.

Kept in its own module so the pytest-loaded conftest and the copy tests import
by package path share one list under ``--import-mode=importlib``.
"""

from __future__ import annotations

from typing import Any

opened_backends: list[Any] = []
