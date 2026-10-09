from fastapi import APIRouter

from connectors.slack.api.router import router as slack_router
from interfaces.api.routes.teams import router as teams_router
from interfaces.api.routes.meetings import router as meetings_router

api_router = APIRouter()

api_router.include_router(slack_router)
api_router.include_router(teams_router)
api_router.include_router(meetings_router)
