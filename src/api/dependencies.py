"""
Dependency providers.
"""

from __future__ import annotations

from application.bootstrap import (
    bootstrap,
)

from application.cognitive import (
    CognitiveEngine,
)

from application.activity import (
    ActivityProcessor,
    ActivityQuestionService,
)

from connectors.slack.normalizers import (
    SlackNormalizer,
)

from connectors.slack.services import (
    SlackService,
)

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
    """
    Return the shared communication repository.
    """

    return _repository


def get_communication_service() -> CommunicationService:
    """
    Return the shared communication service.
    """

    return _service


def get_slack_normalizer() -> SlackNormalizer:
    """
    Return the shared Slack normalizer.
    """

    return _normalizer


def get_slack_service() -> SlackService:
    """
    Return the shared Slack service.
    """

    return _slack_service


def get_cognitive_engine() -> CognitiveEngine:
    """
    Return the shared POLIS cognitive engine.
    """

    return _cognitive_engine


def get_activity_processor() -> ActivityProcessor:
    """
    Return the shared activity processor.
    """

    return _application.activity_processor


def get_activity_question_service() -> ActivityQuestionService:
    """
    Return the shared activity question service.
    """

    return _application.activity_question_service