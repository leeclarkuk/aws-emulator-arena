"""Trim a response down to the fields the gallery can publish.

Secret-looking keys are replaced. Long strings and long lists are cut.
The result is JSON-safe: no streams, no bytes, no nan.
"""

from __future__ import annotations

import math

_SECRET_PARTS = ("secret", "password", "token", "authorization", "accesskey", "credential")
_MAX_DEPTH = 5
_MAX_STRING = 240
_MAX_LIST = 8
_MAX_KEYS = 24


def public_copy(value, depth: int = 0):
    """Return a JSON-safe copy with secrets removed and bulky values trimmed."""

    if depth > _MAX_DEPTH:
        return "..."
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, str):
        if len(value) > _MAX_STRING:
            return value[:_MAX_STRING] + "..."
        return value
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if isinstance(value, dict):
        copied = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_KEYS:
                copied["_truncated"] = f"{len(value) - _MAX_KEYS} more keys"
                break
            name = str(key)
            if name == "ResponseMetadata":
                status = item.get("HTTPStatusCode") if isinstance(item, dict) else None
                if status is not None and "httpStatus" not in copied:
                    copied["httpStatus"] = public_copy(status, depth + 1)
                continue
            if _secret_key(name):
                copied[name] = "[redacted]"
                continue
            copied[name] = public_copy(item, depth + 1)
        return copied
    if isinstance(value, (list, tuple)):
        copied = [public_copy(item, depth + 1) for item in list(value)[:_MAX_LIST]]
        if len(value) > _MAX_LIST:
            copied.append(f"... {len(value) - _MAX_LIST} more")
        return copied
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return str(isoformat())
        except Exception:
            return f"<{type(value).__name__}>"
    return f"<{type(value).__name__}>"


def _secret_key(name: str) -> bool:
    compact = "".join(ch for ch in name.lower() if ch.isalnum())
    return any(part in compact for part in _SECRET_PARTS)
