from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from application.identity import (
    CanonicalChannelIdentity,
    CanonicalEmployeeIdentity,
    CanonicalIdentityService,
    IdentityResolutionStatus,
    PlatformType,
)


def test_resolve_slack_user_success():
    mock_slack = MagicMock()
    mock_slack.get_workspace_users.return_value = [
        {
            "id": "U012345",
            "name": "akshat",
            "real_name": "Akshat Tripathi",
            "profile": {
                "display_name": "Akshat",
                "email": "akshat@example.com",
            },
        }
    ]

    service = CanonicalIdentityService(slack_identity_service=mock_slack)
    identity = service.resolve_user("U012345", platform="slack")

    assert identity.platform_user_id == "U012345"
    assert identity.internal_id == "emp_akshat@example.com"
    assert identity.canonical_name == "Akshat Tripathi"
    assert identity.display_name == "Akshat"
    assert identity.email == "akshat@example.com"
    assert identity.resolution_status == IdentityResolutionStatus.RESOLVED
    assert identity.metadata["external_ids"]["slack"] == "U012345"


def test_resolve_slack_user_fallback_when_not_in_directory():
    mock_slack = MagicMock()
    mock_slack.get_workspace_users.return_value = []

    service = CanonicalIdentityService(slack_identity_service=mock_slack)
    identity = service.resolve_user(
        "UUNKNOWN",
        platform="slack",
        display_name_hint="Unknown Colleague",
    )

    assert identity.platform_user_id == "UUNKNOWN"
    assert identity.internal_id == "UUNKNOWN"
    assert identity.canonical_name == "Unknown Colleague"
    assert identity.resolution_status == IdentityResolutionStatus.PROVISIONAL


def test_resolve_teams_user():
    service = CanonicalIdentityService()
    identity = service.resolve_user(
        "john.doe@company.com",
        platform="microsoft_teams",
        display_name_hint="John Doe",
        email_hint="john.doe@company.com",
    )

    assert identity.platform == PlatformType.TEAMS.value
    assert identity.platform_user_id == "john.doe@company.com"
    assert identity.internal_id == "emp_john.doe@company.com"
    assert identity.display_name == "John Doe"
    assert identity.email == "john.doe@company.com"
    assert identity.resolution_status == IdentityResolutionStatus.RESOLVED


def test_cross_platform_identity_resolution_same_canonical_id():
    """
    Point 1 Architecture Requirement:
    Verify that the same employee using Slack and Microsoft Teams resolves
    to exactly the same canonical POLIS internal employee ID, while platform-specific
    IDs remain external identifiers.
    """
    mock_slack = MagicMock()
    mock_slack.get_workspace_users.return_value = [
        {
            "id": "U_SARAH",
            "name": "sarah",
            "real_name": "Sarah Connor",
            "profile": {
                "display_name": "Sarah",
                "email": "sarah.connor@cyberdyne.com",
            },
        }
    ]

    service = CanonicalIdentityService(slack_identity_service=mock_slack)

    # 1. Resolve Slack identity
    slack_id = service.resolve_user("U_SARAH", platform="slack")

    # 2. Resolve Teams identity for the same employee
    teams_id = service.resolve_user(
        "29:teams_sarah_101",
        platform="microsoft_teams",
        display_name_hint="Sarah Connor",
        email_hint="sarah.connor@cyberdyne.com",
    )

    # Cross-platform internal ID must be unified
    assert slack_id.internal_id == "emp_sarah.connor@cyberdyne.com"
    assert teams_id.internal_id == "emp_sarah.connor@cyberdyne.com"
    assert slack_id.internal_id == teams_id.internal_id

    # Platform-specific IDs must remain external identifiers
    assert slack_id.platform_user_id == "U_SARAH"
    assert teams_id.platform_user_id == "29:teams_sarah_101"
    assert slack_id.metadata["external_ids"]["slack"] == "U_SARAH"
    assert teams_id.metadata["external_ids"]["microsoft_teams"] == "29:teams_sarah_101"

    # All identifiers association
    all_sarah_ids = service.get_all_identifiers_for_user("U_SARAH")
    assert "emp_sarah.connor@cyberdyne.com" in all_sarah_ids
    assert "U_SARAH" in all_sarah_ids
    assert "29:teams_sarah_101" in all_sarah_ids
    assert "sarah.connor@cyberdyne.com" in all_sarah_ids


def test_resolve_user_by_mention():
    mock_slack = MagicMock()
    mock_slack.get_workspace_users.return_value = [
        {
            "id": "U999",
            "name": "hemant",
            "real_name": "Hemant Sharma",
            "profile": {"display_name": "Hemant", "email": "hemant@example.com"},
        }
    ]

    service = CanonicalIdentityService(slack_identity_service=mock_slack)
    identity = service.resolve_user_by_name_or_mention("<@U999|hemant>")

    assert identity is not None
    assert identity.internal_id == "emp_hemant@example.com"
    assert identity.platform_user_id == "U999"
    assert identity.canonical_name == "Hemant Sharma"


def test_resolve_user_by_name_exact_unique():
    mock_slack = MagicMock()
    mock_slack.get_workspace_users.return_value = [
        {
            "id": "U555",
            "name": "vijay",
            "real_name": "Vijay Kumar",
            "profile": {"display_name": "Vijay", "email": "vijay@example.com"},
        }
    ]

    service = CanonicalIdentityService(slack_identity_service=mock_slack)
    identity = service.resolve_user_by_name_or_mention("Vijay")

    assert identity is not None
    assert identity.internal_id == "emp_vijay@example.com"
    assert identity.platform_user_id == "U555"
    assert identity.canonical_name == "Vijay Kumar"


def test_resolve_user_by_name_duplicate_collision_refuses_to_guess():
    mock_slack = MagicMock()
    mock_slack.get_workspace_users.return_value = [
        {
            "id": "U101",
            "name": "hemant_s",
            "real_name": "Hemant Sharma",
            "profile": {"display_name": "Hemant"},
        },
        {
            "id": "U102",
            "name": "hemant_v",
            "real_name": "Hemant Verma",
            "profile": {"display_name": "Hemant"},
        },
    ]

    service = CanonicalIdentityService(slack_identity_service=mock_slack)
    # Both display names match "Hemant" -> must NOT arbitrarily guess
    identity = service.resolve_user_by_name_or_mention("Hemant")
    assert identity is None


def test_resolve_channel_types():
    service = CanonicalIdentityService()

    dm = service.resolve_channel("D012345")
    assert dm.channel_type == "im"

    mpim = service.resolve_channel("G012345")
    assert mpim.channel_type == "mpim"

    public_ch = service.resolve_channel("C012345", channel_name_hint="general")
    assert public_ch.channel_type == "public"
    assert public_ch.channel_name == "general"

    teams_meet = service.resolve_channel("meeting-xyz", platform="microsoft_teams")
    assert teams_meet.channel_type == "meeting"
