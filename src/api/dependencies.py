"""
Dependency providers.
"""

from __future__ import annotations

from connectors.slack.normalizers import SlackNormalizer

from engines.communication.application.services import (
    CommunicationService,
)

from engines.communication.infrastructure.repositories import (
    InMemoryCommunicationRepository,
)
from connectors.slack.services import SlackService

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


# Repository
_repository = InMemoryCommunicationRepository()


# Event Infrastructure
_registry = EventRegistry()

_registry.register(
    CommunicationCreatedEvent,
    CommunicationCreatedHandler(),
)

_dispatcher = EventDispatcher(
    _registry,
)


# Application Service
_service = CommunicationService(
    repository=_repository,
    dispatcher=_dispatcher,
)


# Slack Components
_normalizer = SlackNormalizer()

_slack_service = SlackService(
    normalizer=_normalizer,
    communication_service=_service,
)


def get_repository() -> InMemoryCommunicationRepository:
    return _repository


def get_communication_service() -> CommunicationService:
    return _service


def get_slack_normalizer() -> SlackNormalizer:
    return _normalizer


def get_slack_service() -> SlackService:
    return _slack_service

