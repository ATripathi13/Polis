from datetime import timedelta

from connectors.microsoft_teams.parsers import (
    parse_teams_vtt,
)


def test_parse_teams_vtt_extracts_speaker_segments():
    transcript = """WEBVTT

00:00:01.000 --> 00:00:03.500
<v Akshat Tripathi>Hello everyone.</v>

00:00:04.000 --> 00:00:08.250
<v Rahul Sharma>We should launch this Monday.</v>
"""

    segments = parse_teams_vtt(transcript)

    assert len(segments) == 2

    assert segments[0].speaker == "Akshat Tripathi"
    assert segments[0].text == "Hello everyone."
    assert segments[0].start == timedelta(seconds=1)
    assert segments[0].end == timedelta(seconds=3.5)

    assert segments[1].speaker == "Rahul Sharma"
    assert segments[1].text == "We should launch this Monday."
    assert segments[1].start == timedelta(seconds=4)
    assert segments[1].end == timedelta(seconds=8.25)


def test_parse_teams_vtt_ignores_non_speaker_lines():
    transcript = """WEBVTT

00:00:01.000 --> 00:00:03.000
<v Akshat Tripathi>Hello.</v>

00:00:04.000 --> 00:00:05.000
Some unrelated cue text.
"""

    segments = parse_teams_vtt(transcript)

    assert len(segments) == 1
    assert segments[0].speaker == "Akshat Tripathi"


def test_parse_teams_vtt_empty_transcript():
    assert parse_teams_vtt("") == []
    assert parse_teams_vtt("   ") == []
