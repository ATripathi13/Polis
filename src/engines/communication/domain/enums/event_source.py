"""
Canonical communication sources supported by Polis.
"""

from enum import Enum


class EventSource(str, Enum):
    """Supported communication sources."""

    SLACK = "slack"
    GMAIL = "gmail"
    MICROSOFT_TEAMS = "microsoft_teams"
    WHATSAPP = "whatsapp"
    DISCORD = "discord"
    GITHUB = "github"
    GOOGLE_MEET = "google_meet"
    ZOOM = "zoom"
    JIRA = "jira"
    NOTION = "notion"
    DOCUMENT = "document"
    VOICE = "voice"
    MANUAL = "manual"