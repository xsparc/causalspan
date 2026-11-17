"""Deliberately small payload policy; not a general secret detector."""

import json
import re
from typing import Any

MAX_PAYLOAD_BYTES = 65_536
_SENSITIVE = re.compile(r"password|passwd|secret|token|authorization|cookie|api.?key", re.I)


def capture_json(value: Any) -> tuple[str, bool]:
    """Return bounded JSON and whether a sensitive mapping key was redacted."""
    redacted = False

    def clean(item: Any, depth: int = 0) -> Any:
        nonlocal redacted
        if depth > 32:
            raise ValueError("payload nesting limit exceeded")
        if isinstance(item, dict):
            result = {}
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("payload keys must be strings")
                if _SENSITIVE.search(key):
                    result[key] = "[REDACTED]"
                    redacted = True
                else:
                    result[key] = clean(child, depth + 1)
            return result
        if isinstance(item, list):
            return [clean(child, depth + 1) for child in item]
        if item is None or type(item) in (str, int, float, bool):
            return item
        raise ValueError("payload must contain only JSON values")

    encoded = json.dumps(clean(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError("payload size limit exceeded")
    return encoded, redacted
