"""
POLIS API application.
"""

from __future__ import annotations

from fastapi import FastAPI

from .routes.slack import router as slack_router
from .routes.ask import router as ask_router
from .routes.debug import (router as debug_router,)
app = FastAPI(
    title="POLIS",
    version="1.0.0",
)


app.include_router(
    slack_router,
)

app.include_router(
    debug_router,
)
app.include_router(
    ask_router,
)