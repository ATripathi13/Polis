"""
Unit test for Calendar bootstrap and container wiring.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from application.bootstrap.container import ApplicationContainer
from application.calendar import (
    CalendarAgent,
    CalendarReminderWorker,
    CalendarService,
)
from domain.calendar.repositories import CalendarRepository
from infrastructure.config.settings import Settings


def test_container_calendar_fields():
    """Verify ApplicationContainer structure holds calendar services."""
    container = ApplicationContainer(
        engine=MagicMock(),
        knowledge_base_ingestion_service=MagicMock(),
        repository=MagicMock(),
        activity_service=MagicMock(),
        activity_processor=MagicMock(),
        activity_question_service=MagicMock(),
        meeting_transcript_service=MagicMock(),
        meeting_intelligence_service=MagicMock(),
        meeting_transcript_provider=MagicMock(),
        meeting_recording_provider=MagicMock(),
        teams_subscription_repository=MagicMock(),
        teams_subscription_service=MagicMock(),
        teams_recording_subscription_service=MagicMock(),
        reminder_repository=MagicMock(),
        reminder_service=MagicMock(),
        calendar_repository=MagicMock(spec=CalendarRepository),
        calendar_service=MagicMock(spec=CalendarService),
        calendar_agent=MagicMock(spec=CalendarAgent),
        calendar_worker=MagicMock(spec=CalendarReminderWorker),
    )

    assert container.calendar_repository is not None
    assert container.calendar_service is not None
    assert container.calendar_agent is not None
    assert container.calendar_worker is not None


def test_bootstrap_calendar_wiring():
    """Verify bootstrap wires calendar agent to cognitive engine and container."""
    from application.bootstrap.bootstrap import bootstrap

    # Mock DB connections and external clients
    with patch("application.bootstrap.bootstrap.PostgreSQLCalendarRepository") as mock_repo_cls, \
         patch("application.bootstrap.bootstrap.PostgreSQLGovernanceRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLKnowledgeRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLCommunicationRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLActivityRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLMeetingTranscriptRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLMeetingRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLTeamsSubscriptionRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLReminderRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLOperationalItemRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLOrganizationEventRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLKnowledgeBaseDocumentRepository"), \
         patch("application.bootstrap.bootstrap.PostgreSQLKnowledgeBaseChunkRepository"), \
         patch("application.bootstrap.bootstrap.MinIOKnowledgeBaseStorage"), \
         patch("application.bootstrap.bootstrap.SlackClient") as mock_slack_cls, \
         patch("application.bootstrap.bootstrap.SlackIdentityService") as mock_identity_cls:

        mock_repo = MagicMock(spec=CalendarRepository)
        mock_repo_cls.return_value = mock_repo
        mock_slack_cls.return_value = MagicMock()
        mock_identity_cls.return_value = MagicMock()

        container = bootstrap()

        assert container.calendar_repository is not None
        assert container.calendar_service is not None
        assert container.calendar_agent is not None
        assert container.calendar_worker is not None
        assert container.engine.calendar_agent is container.calendar_agent
