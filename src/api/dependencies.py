"""
Dependency providers.
"""

from __future__ import annotations

from application.bootstrap.bootstrap import bootstrap
from application.cognitive import CognitiveEngine

from connectors.slack.normalizers import SlackNormalizer
from connectors.slack.services import SlackService

from engines.communication.application.services import (
    CommunicationService,
)

from engines.communication.infrastructure.repositories import (
    InMemoryCommunicationRepository,
)

from domain.events import (
    EventDispatcher,
    EventRegistry,
)

from engines.communication.handlers import (
    CommunicationCreatedHandler,
)

from engines.communication.domain.events import (
    CommunicationCreatedEvent,
)


# ==========================================================
# POLIS APPLICATION
# ==========================================================

_application = bootstrap()

_cognitive_engine = _application.engine


# ==========================================================
# COMMUNICATION INFRASTRUCTURE
# ==========================================================

_repository = InMemoryCommunicationRepository()

_registry = EventRegistry()

_registry.register(
    CommunicationCreatedEvent,
    CommunicationCreatedHandler(),
)

_dispatcher = EventDispatcher(
    _registry,
)


# ==========================================================
# COMMUNICATION SERVICE
# ==========================================================

_service = CommunicationService(
    repository=_repository,
    dispatcher=_dispatcher,
)


# ==========================================================
# SLACK
# ==========================================================

_normalizer = SlackNormalizer()

_slack_service = SlackService(
    normalizer=_normalizer,
    communication_service=_service,
    cognitive_engine=_cognitive_engine,
)


# ==========================================================
# DEPENDENCIES
# ==========================================================

def get_repository():
    return _repository


def get_communication_service() -> CommunicationService:
    return _service


def get_slack_normalizer() -> SlackNormalizer:
    return _normalizer


def get_slack_service() -> SlackService:
    return _slack_service


def get_cognitive_engine() -> CognitiveEngine:
    return _cognitive_engine