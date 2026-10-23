"""
Unit tests for AudienceResolutionService and membership resolution boundary.
"""

from __future__ import annotations

import pytest

from domain.calendar import CalendarAudienceType, InvalidAudienceError
from application.calendar import (
    AudienceResolutionService,
    SlackMembershipDirectoryProvider,
)


class FakeSlackIdentityService:
    def __init__(self):
        self.directory = [
            {"id": "U_ALICE", "name": "alice", "real_name": "Alice Smith"},
            {"id": "U_BOB", "name": "bob", "real_name": "Bob Jones"},
        ]

    def resolve_user(self, name: str) -> dict | None:
        normalized = name.lower().strip()
        for u in self.directory:
            if (
                u["name"].lower() == normalized
                or u["real_name"].lower() == normalized
                or u["id"].lower() == normalized
            ):
                return u
        return None

    def get_user_id(self, user: dict | None) -> str | None:
        return user.get("id") if user else None

    def get_workspace_users(self) -> list[dict]:
        return self.directory


class FakeTeamProvider:
    def __init__(self):
        self.rosters = {
            "engineering": ["U_ALICE", "U_BOB"],
            "marketing": ["U_CHARLIE"],
        }

    def get_team_members(self, team_name: str) -> list[str]:
        return self.rosters.get(team_name.lower().strip(), [])


@pytest.fixture
def audience_service() -> AudienceResolutionService:
    provider = SlackMembershipDirectoryProvider(
        slack_identity_service=FakeSlackIdentityService(),
        team_roster_provider=FakeTeamProvider(),
    )
    return AudienceResolutionService(
        directory_provider=provider,
        organization_channel_id="C_ANNOUNCEMENTS",
    )


def test_resolve_individual_via_mention(audience_service):
    aud = audience_service.resolve(
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="<@U_ALICE|alice>",
    )
    assert aud.audience_type == CalendarAudienceType.INDIVIDUAL
    assert aud.audience_id == "U_ALICE"
    assert aud.resolved_recipients == ("U_ALICE",)


def test_resolve_individual_via_username(audience_service):
    aud = audience_service.resolve(
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="Bob Jones",
    )
    assert aud.audience_type == CalendarAudienceType.INDIVIDUAL
    assert aud.audience_id == "U_BOB"
    assert aud.resolved_recipients == ("U_BOB",)


def test_resolve_individual_unresolvable_raises_error(audience_service):
    with pytest.raises(InvalidAudienceError, match="Cannot resolve individual recipient"):
        audience_service.resolve(
            audience_type=CalendarAudienceType.INDIVIDUAL,
            audience_identifier="nonexistent_user_999",
        )


def test_resolve_team_with_members(audience_service):
    aud = audience_service.resolve(
        audience_type=CalendarAudienceType.TEAM,
        audience_identifier="engineering",
    )
    assert aud.audience_type == CalendarAudienceType.TEAM
    assert aud.audience_id == "engineering"
    assert set(aud.resolved_recipients) == {"U_ALICE", "U_BOB"}

def test_resolve_team_without_roster_raises_error():
    provider = SlackMembershipDirectoryProvider(
        slack_identity_service=FakeSlackIdentityService(),
    )
    service = AudienceResolutionService(directory_provider=provider)

    with pytest.raises(
        InvalidAudienceError,
        match="authoritative member roster",
    ):
        service.resolve(
            audience_type=CalendarAudienceType.TEAM,
            audience_identifier="unknown-team",
        )


def test_resolve_organization_uses_channel_policy(audience_service):
    aud = audience_service.resolve(
        audience_type=CalendarAudienceType.ORGANIZATION,
        audience_identifier="organization",
    )
    assert aud.audience_type == CalendarAudienceType.ORGANIZATION
    assert aud.resolved_recipients == ("C_ANNOUNCEMENTS",)


def test_resolve_organization_without_channel_policy_raises_error():
    provider = SlackMembershipDirectoryProvider(
        slack_identity_service=FakeSlackIdentityService(),
    )
    service_no_channel = AudienceResolutionService(
        directory_provider=provider,
        organization_channel_id="",
    )

    with pytest.raises(
        InvalidAudienceError,
        match="CALENDAR_ORGANIZATION_CHANNEL",
    ):
        service_no_channel.resolve(
            audience_type=CalendarAudienceType.ORGANIZATION,
            audience_identifier="organization",
        )

def test_reject_unsupported_audience_type(audience_service):
    with pytest.raises(InvalidAudienceError, match="Unsupported audience type"):
        audience_service.resolve(
            audience_type="worldwide_public",
            audience_identifier="all",
        )
