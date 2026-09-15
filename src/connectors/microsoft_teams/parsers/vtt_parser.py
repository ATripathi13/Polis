"""
Parser for Microsoft Teams WebVTT transcripts.
"""

from __future__ import annotations

import re
from datetime import timedelta

from connectors.microsoft_teams.models import (
    TeamsTranscriptSegment,
)


_TIMESTAMP_RE = re.compile(
    r"^\s*"
    r"(?P<start>\d{2}:\d{2}:\d{2}\.\d{3})"
    r"\s*-->\s*"
    r"(?P<end>\d{2}:\d{2}:\d{2}\.\d{3})"
    r"\s*$"
)

_SPEAKER_RE = re.compile(
    r"<v\s+([^>]+)>(.*?)</v>",
    re.DOTALL,
)


def _parse_timestamp(value: str) -> timedelta:
    hours, minutes, seconds = value.split(":")
    whole_seconds, milliseconds = seconds.split(".")

    return timedelta(
        hours=int(hours),
        minutes=int(minutes),
        seconds=int(whole_seconds),
        milliseconds=int(milliseconds),
    )


def parse_teams_vtt(
    transcript: str,
) -> list[TeamsTranscriptSegment]:
    """
    Parse a Teams WebVTT transcript into speaker segments.

    The parser is intentionally deterministic and does not
    perform semantic interpretation.
    """

    if not transcript or not transcript.strip():
        return []

    lines = transcript.splitlines()

    segments: list[TeamsTranscriptSegment] = []

    current_start: timedelta | None = None
    current_end: timedelta | None = None

    for line in lines:
        timestamp_match = _TIMESTAMP_RE.match(line)

        if timestamp_match:
            current_start = _parse_timestamp(
                timestamp_match.group("start")
            )
            current_end = _parse_timestamp(
                timestamp_match.group("end")
            )
            continue

        if current_start is None or current_end is None:
            continue

        speaker_match = _SPEAKER_RE.search(line)

        if not speaker_match:
            continue

        speaker = speaker_match.group(1).strip()
        text = speaker_match.group(2).strip()

        if not speaker or not text:
            continue

        segments.append(
            TeamsTranscriptSegment(
                speaker=speaker,
                text=text,
                start=current_start,
                end=current_end,
            )
        )

        current_start = None
        current_end = None

    return segments
