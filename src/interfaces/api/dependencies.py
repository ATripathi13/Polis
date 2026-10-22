"""
Dependency providers for the API.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status
from infrastructure.config.settings import get_settings

from application.cognitive import (
    SimpleCognitiveEngine,
)

from application.bootstrap import (
    get_container,
)

from domain.knowledge import (
    KnowledgeRepository,
)

from application.activity.activity_processor import (
    ActivityProcessor,
)


def get_cognitive_engine(
) -> SimpleCognitiveEngine:
    """
    Return the application's
    cognitive engine.
    """

    container = get_container()

    return container.engine


def get_repository(
) -> KnowledgeRepository:
    """
    Return the shared knowledge repository.
    """

    container = get_container()

    return container.repository


def get_activity_processor() -> ActivityProcessor:
    """
    Return the shared activity processor.
    """

    container = get_container()

    return container.activity_processor


def get_knowledge_agent():
    """
    Return the specialist Knowledge Agent.
    """

    container = get_container()

    return container.knowledge_agent


def get_operations_agent():
    """
    Return the specialist Operations Agent.
    """

    container = get_container()

    return container.operations_agent


def get_governance_agent():
    """
    Return the specialist Governance Agent.
    """

    container = get_container()

    return container.governance_agent


def get_meeting_intelligence_service():
    """
    Return the specialist Meeting Intelligence Service.
    """

    container = get_container()

    return container.meeting_intelligence_service

def require_internal_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Authenticate trusted internal service requests."""
    expected_key = get_settings().polis_api_key

    if (
        not expected_key
        or not x_api_key
        or not hmac.compare_digest(x_api_key, expected_key)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )