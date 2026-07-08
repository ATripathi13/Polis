from __future__ import annotations

from contextvars import ContextVar

correlation_id: ContextVar[str] = ContextVar(
    "correlation_id",
    default="-",
)

engine_name: ContextVar[str] = ContextVar(
    "engine_name",
    default="platform",
)