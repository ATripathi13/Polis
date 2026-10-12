from application.meetings.meeting_intelligence_result import (
    MeetingIntelligenceResult,
)


def test_meeting_intelligence_result_defaults_are_empty():
    result = MeetingIntelligenceResult(
        summary="Meeting summary",
    )

    assert result.summary == "Meeting summary"
    assert result.topics == []
    assert result.decisions == []
    assert result.action_items == []
    assert result.risks == []
    assert result.open_questions == []
    assert result.confidence == 0.0
    assert result.evidence == []


def test_meeting_intelligence_result_accepts_structured_data():
    result = MeetingIntelligenceResult(
        summary="The team aligned on the release plan.",
        topics=["Release plan"],
        decisions=["Release Friday"],
        action_items=["Publish release notes"],
        risks=["Approval dependency"],
        open_questions=["Who owns final approval?"],
        confidence=0.9,
        evidence=["meeting-transcript-001"],
    )

    assert result.topics == ["Release plan"]
    assert result.decisions == ["Release Friday"]
    assert result.action_items == ["Publish release notes"]
    assert result.risks == ["Approval dependency"]
    assert result.open_questions == ["Who owns final approval?"]
    assert result.confidence == 0.9
    assert result.evidence == ["meeting-transcript-001"]


def test_meeting_intelligence_result_rejects_empty_summary():
    try:
        MeetingIntelligenceResult(summary="   ")
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert str(exc) == "summary must not be empty"


def test_meeting_intelligence_result_rejects_invalid_confidence():
    try:
        MeetingIntelligenceResult(
            summary="Meeting summary",
            confidence=1.1,
        )
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert str(exc) == "confidence must be between 0.0 and 1.0"
