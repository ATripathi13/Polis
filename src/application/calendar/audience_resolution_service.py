"""
Audience resolution service and membership directory boundary for POLIS Calendar.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from domain.calendar.enums import CalendarAudienceType
from domain.calendar.exceptions import InvalidAudienceError
from domain.calendar.value_objects import CalendarAudience

logger = logging.getLogger(__name__)


class MembershipDirectoryProvider(Protocol):
    """Authoritative integration boundary for organization directory and team membership."""

    def resolve_user(self, identifier_or_name: str) -> dict | None:
        """Resolve a user identifier or display name to authoritative user data."""
        ...

    def get_user_id(self, user: dict | None) -> str | None:
        """Extract authoritative user ID from resolved user data."""
        ...

    def get_team_members(self, team_id_or_name: str) -> list[str]:
        """Resolve a team identifier or name to authoritative member user IDs."""
        ...

    def get_all_workspace_user_ids(self) -> list[str]:
        """Retrieve all active workspace user IDs."""
        ...


class SlackMembershipDirectoryProvider:
    """
    Default membership provider backed by Slack workspace directory.

    Uses SlackIdentityService for user resolution and configurable team mapping.
    """

    def __init__(
        self,
        slack_identity_service: Any = None,
        team_roster_provider: Any = None,
    ) -> None:
        self._identity_service = slack_identity_service
        self._team_roster_provider = team_roster_provider

    def resolve_user(self, identifier_or_name: str) -> dict | None:
        if not identifier_or_name:
            return None
        cleaned = identifier_or_name.strip()
        # Handle Slack mention format <@U123456>
        if cleaned.startswith("<@") and cleaned.endswith(">"):
            user_id = cleaned[2:-1].split("|")[0]
            return {"id": user_id, "name": user_id}

        if self._identity_service is not None:
            try:
                user = self._identity_service.resolve_user(cleaned)
                if user:
                    return user
            except Exception:
                logger.warning(
                    "Slack identity lookup failed for '%s'",
                    identifier_or_name,
                    exc_info=True,
                )

        # Direct Slack ID format (e.g. U12345678, W12345678)
        if (
            len(cleaned) >= 8
            and cleaned[0] in ("U", "W")
            and cleaned[1:].isalnum()
        ):
            return {"id": cleaned, "name": cleaned}

        return None

    def get_user_id(self, user: dict | None) -> str | None:
        if not user:
            return None
        if self._identity_service is not None and hasattr(
            self._identity_service, "get_user_id"
        ):
            return self._identity_service.get_user_id(user)
        return user.get("id")

    def get_team_members(self, team_id_or_name: str) -> list[str]:
        if not team_id_or_name:
            return []
        if self._team_roster_provider is not None:
            if callable(self._team_roster_provider):
                return self._team_roster_provider(team_id_or_name)
            if hasattr(self._team_roster_provider, "get_team_members"):
                return self._team_roster_provider.get_team_members(team_id_or_name)
        # Fallback empty list if no external team provider is registered
        return []

    def get_all_workspace_user_ids(self) -> list[str]:
        if self._identity_service is not None and hasattr(
            self._identity_service, "get_workspace_users"
        ):
            try:
                users = self._identity_service.get_workspace_users()
                return [
                    u["id"]
                    for u in users
                    if not u.get("deleted") and not u.get("is_bot") and "id" in u
                ]
            except Exception:
                logger.warning("Failed to retrieve workspace users", exc_info=True)
        return []


class AudienceResolutionService:
    """
    Validates and resolves calendar audiences into stable identifiers and delivery targets.
    """

    def __init__(
        self,
        directory_provider: MembershipDirectoryProvider | None = None,
        organization_channel_id: str = "",
    ) -> None:
        self._provider = directory_provider or SlackMembershipDirectoryProvider()
        self._org_channel = organization_channel_id.strip()

    def resolve(
        self,
        audience_type: CalendarAudienceType | str,
        audience_identifier: str,
        display_name: str = "",
    ) -> CalendarAudience:
        """
        Validate and resolve the requested audience.

        Raises InvalidAudienceError if the audience cannot be validated against
        authoritative membership sources.
        """
        if isinstance(audience_type, str):
            try:
                audience_type = CalendarAudienceType(audience_type.lower())
            except ValueError as err:
                raise InvalidAudienceError(
                    f"Unsupported audience type: '{audience_type}'. "
                    f"Supported types: individual, team, organization."
                ) from err

        target = audience_identifier.strip()
        if not target and audience_type != CalendarAudienceType.ORGANIZATION:
            raise InvalidAudienceError(
                f"Audience identifier is required for '{audience_type.value}' audience."
            )

        if audience_type == CalendarAudienceType.INDIVIDUAL:
            user_data = self._provider.resolve_user(target)
            user_id = self._provider.get_user_id(user_data)
            if not user_id:
                raise InvalidAudienceError(
                    f"Cannot resolve individual recipient '{target}' against "
                    "workspace directory. Please verify username or mention."
                )
            name = display_name or user_data.get("real_name") or target
            return CalendarAudience.individual(user_id=user_id, display_name=name)

        if audience_type == CalendarAudienceType.TEAM:
            member_ids = tuple(
                dict.fromkeys(
                    member_id
                    for member_id in self._provider.get_team_members(target)
                    if isinstance(member_id, str) and member_id.strip()
                )
            )
            if not member_ids:
                raise InvalidAudienceError(
                    f"Cannot resolve team '{target}' to an authoritative member roster. "
                    "Configure the team roster before scheduling reminders."
                )

            return CalendarAudience.team(
                team_id=target.lower(),
                display_name=display_name or target,
                member_ids=member_ids,
            )

        if audience_type == CalendarAudienceType.ORGANIZATION:
            if not self._org_channel:
                raise InvalidAudienceError(
                    "Organization-wide calendar reminders require "
                    "CALENDAR_ORGANIZATION_CHANNEL to be configured. "
                    "No workspace-wide direct-message fallback is allowed."
                )

            return CalendarAudience.organization(
                organization_id="organization",
                display_name=display_name or "Whole Organization",
                recipient_ids=(self._org_channel,),
            )

        raise InvalidAudienceError(f"Unhandled audience type: {audience_type}")
