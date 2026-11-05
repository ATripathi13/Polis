from fastapi import APIRouter

from connectors.slack.api.router import router as slack_router
from interfaces.api.routes.teams import router as teams_router
from interfaces.api.routes.meetings import router as meetings_router
from interfaces.api.routes.ask import router as ask_router
from interfaces.api.routes.conversations import router as conversations_router
from interfaces.api.routes.employees import router as employees_router
from interfaces.api.routes.priorities import router as priorities_router

api_router = APIRouter()

api_router.include_router(slack_router)
api_router.include_router(teams_router)
api_router.include_router(meetings_router)
api_router.include_router(ask_router)
api_router.include_router(conversations_router)
api_router.include_router(employees_router)
api_router.include_router(priorities_router)
