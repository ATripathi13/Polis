"""
Slack message DTO.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SlackMessage:
    """
    Raw Slack message received
    from the Slack Events API.
    """

    user: str

    channel: str

    text: str

    ts: str

    event_ts: str

    thread_ts: str | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict,
    )