"""Unified API response envelope used across all AuraSaaS routes."""

from __future__ import annotations

import uuid


def api_response(data=None, message: str = "ok", code: int = 0, trace_id: str | None = None) -> dict:
    """Build the unified API response envelope.

    Args:
        data: Response payload (dict, list, scalar, or None).
        message: Human-readable status message.
        code: 0 for success, negative values for application errors.
        trace_id: Request-scoped identifier; auto-generated when omitted.
    """
    return {
        "code": code,
        "data": data,
        "message": message,
        "trace_id": trace_id or str(uuid.uuid4()),
    }
