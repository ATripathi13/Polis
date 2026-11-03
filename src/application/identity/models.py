from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class IdentityResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    PROVISIONAL = "provisional"
    AMBIGUOUS = "ambiguous"


class PlatformType(str, Enum):
    SLACK = "slack"
    TEAMS = "microsoft_teams"
    INTERNAL = "internal"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class CanonicalEmployeeIdentity:
    """
    Canonical POLIS employee identity representation.
    Preserves platform-specific identifiers while providing a stable internal mapping.
    """

    internal_id: str
    canonical_name: str
    platform: str
    platform_user_id: str
    email: str | None = None
    display_name: str = ""
    resolution_status: IdentityResolutionStatus = IdentityResolutionStatus.RESOLVED
    last_verified_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "internal_id": self.internal_id,
            "canonical_name": self.canonical_name,
            "platform": self.platform,
            "platform_user_id": self.platform_user_id,
            "email": self.email,
            "display_name": self.display_name,
            "resolution_status": self.resolution_status.value,
            "last_verified_at": (
                self.last_verified_at.isoformat()
                if self.last_verified_at
                else None
            ),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class CanonicalChannelIdentity:
    """
    Canonical POLIS channel / conversation identity representation.
    """

    platform: str
    platform_channel_id: str
    channel_name: str
    channel_type: str
    team_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "platform_channel_id": self.platform_channel_id,
            "channel_name": self.channel_name,
            "channel_type": self.channel_type,
            "team_id": self.team_id,
            "metadata": dict(self.metadata),
        }
