from datetime import datetime, timezone
from types import SimpleNamespace

from application.meetings.meeting_intelligence_service import (
    MeetingIntelligenceService,
)
from domain.meetings import MeetingTranscript
from domain.common.identifier import Identifier


class FakeTranscriptRepository:
    def __init__(self, transcripts):
        self.transcripts = transcripts

    def find_by_meeting_id(self, meeting_id):
        return [
            transcript
            for transcript in self.transcripts
            if transcript.meeting_id == meeting_id
        ]


class FakeLLMClient:
    def __init__(self, response):
        self.response = response
        self.prompt = None

    def generate(self, prompt):
        self.prompt = prompt
        return self.response


class StructuredLLM:
    def __init__(self, response=None):
        self.prompt = None
        self.response = response or """
{
  "summary": "The team aligned on the Friday release.",
  "topics": ["Release plan"],
  "decisions": ["Release Friday"],
  "action_items": ["Publish the release notes."],
  "risks": [],
  "open_questions": [],
  "confidence": 0.92
}
""".strip()

    def generate(self, prompt):
        self.prompt = prompt
        return self.response


def make_transcript(meeting_id, transcript):
    return MeetingTranscript(
        identifier=Identifier(),
        meeting_id=meeting_id,
        transcript=transcript,
        source="Microsoft Teams",
        captured_at=datetime.now(timezone.utc),
    )


def test_summarize_uses_meeting_transcript():
    repository = FakeTranscriptRepository(
        [
            make_transcript(
                "meeting-001",
                "Alice: We agreed to launch Friday. Bob: I will publish the release notes.",
            )
        ]
    )
    llm = FakeLLMClient(
        "The team agreed to launch Friday. Bob will publish the release notes."
    )

    service = MeetingIntelligenceService(
        transcript_repository=repository,
        llm_client=llm,
    )

    result = service.summarize("meeting-001")

    assert (
        result.text
        == "The team agreed to launch Friday. Bob will publish the release notes."
    )
    assert result.confidence == 0.8
    assert len(result.evidence) == 1
    assert "Alice: We agreed to launch Friday." in result.evidence[0]
    assert "meeting-001" in llm.prompt


def test_summarize_returns_not_found_when_transcript_missing():
    repository = FakeTranscriptRepository([])
    llm = FakeLLMClient("unused")

    service = MeetingIntelligenceService(
        transcript_repository=repository,
        llm_client=llm,
    )

    result = service.summarize("missing-meeting")

    assert result.text == "I couldn't find a transcript for this meeting."
    assert result.confidence == 0.0
    assert result.evidence == []
    assert llm.prompt is None


def test_summarize_handles_llm_failure():
    repository = FakeTranscriptRepository(
        [
            make_transcript(
                "meeting-002",
                "The project is blocked by the missing approval.",
            )
        ]
    )

    class FailingLLM:
        def generate(self, prompt):
            raise RuntimeError("llm failure")

    service = MeetingIntelligenceService(
        transcript_repository=repository,
        llm_client=FailingLLM(),
    )

    result = service.summarize("meeting-002")

    assert (
        result.text
        == "I found the meeting transcript, but I couldn't generate a reliable summary."
    )
    assert result.confidence == 0.0
    assert len(result.evidence) == 1

def test_summarize_chunks_long_meeting_transcript():
    repository = FakeTranscriptRepository(
        [
            make_transcript(
                "meeting-long",
                "\n\n".join(
                    "A" * 10000
                    for _ in range(5)
                ),
            )
        ]
    )

    class RecordingLLM:
        def __init__(self):
            self.calls = []

        def generate(self, prompt):
            self.calls.append(prompt)
            return "Section summary."

    llm = RecordingLLM()

    service = MeetingIntelligenceService(
        transcript_repository=repository,
        llm_client=llm,
    )

    result = service.summarize("meeting-long")

    assert result.text == "Section summary."
    assert len(llm.calls) == 4
    assert all("meeting-long" in prompt for prompt in llm.calls)
    assert len(llm.calls[0]) < 25000
    assert len(llm.calls[1]) < 25000
    assert len(llm.calls[2]) < 25000

def test_analyze_returns_structured_meeting_intelligence():
    class FakeOrganizationEventRepository:
        def all(self):
            return [
                SimpleNamespace(
                    event_type=SimpleNamespace(value="task_created"),
                    summary="Publish the release notes.",
                    confidence=0.9,
                    observations=[
                        SimpleNamespace(
                            evidence=["transcript-001:10.000:15.000:Alice"]
                        )
                    ],
                ),
                SimpleNamespace(
                    event_type=SimpleNamespace(value="decision_made"),
                    summary="Release Friday.",
                    confidence=0.95,
                    observations=[
                        SimpleNamespace(
                            evidence=["transcript-001:20.000:25.000:Bob"]
                        )
                    ],
                ),
            ]

    class StructuredLLM:
        def __init__(self):
            self.prompt = None

        def generate(self, prompt):
            self.prompt = prompt
            return """
{
  "summary": "The team aligned on the Friday release.",
  "topics": ["Release plan"],
  "decisions": ["Release Friday"],
  "action_items": ["Publish the release notes."],
  "risks": [],
  "open_questions": [],
  "confidence": 0.92
}
""".strip()

    repository = FakeTranscriptRepository(
        [
            make_transcript(
                "meeting-structured",
                "Alice: We need to publish the release notes.\n\n"
                "Bob: We will release Friday.",
            )
        ]
    )
    repository.transcripts[0].metadata["transcript_id"] = "transcript-001"

    llm = StructuredLLM()

    service = MeetingIntelligenceService(
        transcript_repository=repository,
        llm_client=llm,
        organization_event_repository=FakeOrganizationEventRepository(),
    )

    result = service.analyze("meeting-structured")

    assert result.summary == "The team aligned on the Friday release."
    assert result.topics == ["Release plan"]
    assert result.decisions == ["Release Friday"]
    assert result.action_items == ["Publish the release notes."]
    assert result.risks == []
    assert result.open_questions == []
    assert result.confidence == 0.92
    assert "Publish the release notes." in llm.prompt
    assert "Release Friday." in llm.prompt


def test_analyze_returns_fallback_when_meeting_transcript_missing():
    repository = FakeTranscriptRepository([])
    llm = FakeLLMClient("unused")

    service = MeetingIntelligenceService(
        transcript_repository=repository,
        llm_client=llm,
        organization_event_repository=None,
    )

    try:
        service.analyze("missing-meeting")
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert str(exc) == "Meeting transcript not found."


def test_analyze_chunks_long_meeting_transcript():
    repository = FakeTranscriptRepository(
        [
            make_transcript(
                "meeting-long-structured",
                "\n\n".join(
                    "Topic discussed in detail. " * 300
                    for _ in range(6)
                ),
            )
        ]
    )

    class RecordingStructuredLLM:
        def __init__(self):
            self.calls = []

        def generate(self, prompt):
            self.calls.append(prompt)
            return """
{
  "summary": "Chunk analysis summary.",
  "topics": ["Architecture"],
  "decisions": ["Adopt microservices"],
  "action_items": ["Draft RFC"],
  "risks": ["Migration complexity"],
  "open_questions": ["Timeline?"],
  "confidence": 0.88
}
""".strip()

    llm = RecordingStructuredLLM()

    service = MeetingIntelligenceService(
        transcript_repository=repository,
        llm_client=llm,
    )

    result = service.analyze("meeting-long-structured")

    assert result.summary == "Chunk analysis summary."
    assert result.topics == ["Architecture"]
    assert result.decisions == ["Adopt microservices"]
    assert result.action_items == ["Draft RFC"]
    assert result.risks == ["Migration complexity"]
    assert result.open_questions == ["Timeline?"]
    assert result.confidence == 0.88
    # Should have chunk section calls plus final synthesis call
    assert len(llm.calls) > 1
    # Final call should be synthesis prompt containing section summaries
    assert "Chunk analysis summary." in llm.calls[-1]


def test_analyze_handles_malformed_llm_json_and_types():
    repository = FakeTranscriptRepository(
        [
            make_transcript(
                "meeting-malformed",
                "Alice: Let's discuss testing.",
            )
        ]
    )

    # 1. Non-dict JSON (array)
    service_array = MeetingIntelligenceService(
        transcript_repository=repository,
        llm_client=FakeLLMClient("[1, 2, 3]"),
    )
    result_array = service_array.analyze("meeting-malformed")
    assert result_array.confidence == 0.0
    assert "couldn't generate reliable structured meeting intelligence" in result_array.summary

    # 2. Complete invalid JSON
    service_invalid = MeetingIntelligenceService(
        transcript_repository=repository,
        llm_client=FakeLLMClient("not valid json at all"),
    )
    result_invalid = service_invalid.analyze("meeting-malformed")
    assert result_invalid.confidence == 0.0
    assert "couldn't generate reliable structured meeting intelligence" in result_invalid.summary

    # 3. String confidence / out-of-range confidence clamping
    service_clamped = MeetingIntelligenceService(
        transcript_repository=repository,
        llm_client=FakeLLMClient('{"summary": "Valid summary", "confidence": 1.7, "topics": "not a list"}'),
    )
    result_clamped = service_clamped.analyze("meeting-malformed")
    assert result_clamped.summary == "Valid summary"
    assert result_clamped.confidence == 1.0
    assert result_clamped.topics == []

    # 4. Non-numeric confidence
    service_str_conf = MeetingIntelligenceService(
        transcript_repository=repository,
        llm_client=FakeLLMClient('{"summary": "Valid summary", "confidence": "high"}'),
    )
    result_str_conf = service_str_conf.analyze("meeting-malformed")
    assert result_str_conf.summary == "Valid summary"
    assert result_str_conf.confidence == 0.0


def test_analyze_prefers_find_by_correlation_and_filters_unrelated_events():
    class CorrelatedEventRepo:
        def __init__(self):
            self.find_by_correlation_called = False
            self.all_called = False

        def find_by_correlation(self, correlation_id):
            self.find_by_correlation_called = True
            return [
                SimpleNamespace(
                    event_type=SimpleNamespace(value="decision_made"),
                    summary="Correlated decision for meeting-corr",
                    confidence=0.9,
                    correlation_id=SimpleNamespace(business_id=correlation_id),
                    observations=[
                        SimpleNamespace(
                            evidence=[f"transcript-corr:1.0:2.0:Alice"]
                        )
                    ],
                ),
                SimpleNamespace(
                    event_type=SimpleNamespace(value="task_created"),
                    summary="Unrelated event from another meeting",
                    confidence=0.8,
                    correlation_id=SimpleNamespace(business_id="other-meeting"),
                    observations=[
                        SimpleNamespace(
                            evidence=["other-transcript:1.0:2.0:Bob"]
                        )
                    ],
                ),
            ]

        def all(self):
            self.all_called = True
            return []

    repo = CorrelatedEventRepo()
    transcript_repo = FakeTranscriptRepository(
        [
            make_transcript(
                "meeting-corr",
                "Alice: We made the decision.",
            )
        ]
    )
    transcript_repo.transcripts[0].metadata["transcript_id"] = "transcript-corr"

    llm = StructuredLLM()
    service = MeetingIntelligenceService(
        transcript_repository=transcript_repo,
        llm_client=llm,
        organization_event_repository=repo,
    )

    result = service.analyze("meeting-corr")

    assert repo.find_by_correlation_called is True
    assert repo.all_called is False
    assert "Correlated decision for meeting-corr" in llm.prompt
    assert "Unrelated event from another meeting" not in llm.prompt


def test_cognitive_engine_meeting_intelligence_integration():
    from application.cognitive import SimpleCognitiveEngine

    fake_meeting_service = SimpleNamespace(
        summarize=lambda m_id: SimpleNamespace(text=f"Summary for {m_id}", confidence=0.8, evidence=[]),
        analyze=lambda m_id: SimpleNamespace(summary=f"Analysis for {m_id}", confidence=0.9),
    )

    engine = SimpleCognitiveEngine(
        pipeline=None,
        question_answering=None,
        meeting_intelligence_service=fake_meeting_service,
    )

    assert engine.meeting_intelligence_service is fake_meeting_service

    summary_result = engine.summarize_meeting("meeting-99")
    assert summary_result.text == "Summary for meeting-99"

    analysis_result = engine.analyze_meeting("meeting-99")
    assert analysis_result.summary == "Analysis for meeting-99"

    # When unconfigured
    unconfigured_engine = SimpleCognitiveEngine(
        pipeline=None,
        question_answering=None,
        meeting_intelligence_service=None,
    )
    fallback_summary = unconfigured_engine.summarize_meeting("meeting-99")
    assert fallback_summary.text == "Meeting intelligence service is not configured."

    try:
        unconfigured_engine.analyze_meeting("meeting-99")
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "not configured" in str(exc)


def test_analyze_does_not_scan_all_events_when_correlation_lookup_is_empty():
    class EmptyCorrelationRepo:
        def __init__(self):
            self.all_called = False

        def find_by_correlation(self, correlation_id):
            return []

        def all(self):
            self.all_called = True
            raise AssertionError("Full-table scan should not be used")

    repository = FakeTranscriptRepository(
        [make_transcript("meeting-empty-events", "Alice: No decisions recorded.")]
    )
    repo = EmptyCorrelationRepo()
    service = MeetingIntelligenceService(
        transcript_repository=repository,
        llm_client=StructuredLLM(),
        organization_event_repository=repo,
    )

    service.analyze("meeting-empty-events")

    assert repo.all_called is False
