from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.dependencies import get_teams_subscription_service
from api.router import api_router
from application.meetings.teams_subscription_renewal import (
    TeamsSubscriptionRenewal,
)


teams_subscription_renewal = TeamsSubscriptionRenewal(
    get_teams_subscription_service()
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await teams_subscription_renewal.start()

    try:
        yield
    finally:
        await teams_subscription_renewal.stop()


app = FastAPI(
    title="Polis",
    description="Organizational Operating System",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "polis",
    }


app.include_router(api_router)
