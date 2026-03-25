#!/usr/bin/env python3
"""
plist_utils.py
Common plist parsing helpers for Dr. iPhone.
"""

from __future__ import annotations

import plistlib
from typing import Any


def loads_plist_text(text: str) -> Any:
    if not text:
        return None
    try:
        return plistlib.loads(text.encode("utf-8"))
    except Exception:
        return None


def get_dict(data: Any, key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if default is None:
        default = {}
    if isinstance(data, dict):
        value = data.get(key, default)
        if isinstance(value, dict):
            return value
    return default


def get_value(data: Any, key: str, default: Any = None) -> Any:
    if isinstance(data, dict):
        return data.get(key, default)
    return default
