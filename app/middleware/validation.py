"""
Shared validation utilities for API routes.
"""
from __future__ import annotations

import re

from quart import jsonify

# UUID v4 pattern (all variants accepted for flexibility).
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def is_valid_uuid(value: str) -> bool:
    """Return True if *value* looks like a UUID."""
    return bool(_UUID_RE.match(value))


def bad_uuid(param_name: str = "id"):
    """Return a 404 JSON response for a malformed UUID path parameter."""
    return (
        jsonify({"error": f"Not found — invalid {param_name}.", "code": "NOT_FOUND"}),
        404,
    )
