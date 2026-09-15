"""
Structured Teams transcript segment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True, slots=True)
class TeamsTranscriptSegment:
    """
    One speaker-attributed segment from a Teams VTT transcript.
    """

    speaker: str
    text: str
    start: timedelta
    end: timedelta
