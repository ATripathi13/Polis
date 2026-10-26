"""
Unit tests for POLIS natural first-person communication style across prompts,
services, fallbacks, and structured outputs.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest

from domain.calendar import (
    CalendarAudienceType,
    CalendarEntryType,
    CalendarReminderPolicy,
    InMemoryCalendarRepository,
)
from domain.knowledge_base import KnowledgeBaseChunk
from domain.reasoning import (
    Answer,
    Question,
    SimpleReasoningService,
)
from domain.reasoning.communication_style import (
    COMMUNICATION_STYLE_PROMPT_INSTRUCTIONS,
    NO_INFORMATION_RESPONSE,
)
from application.calendar import (
    AudienceResolutionService,
    CalendarAgent,
    CalendarService,
    SlackMembershipDirectoryProvider,
)
from application.knowledge_base.knowledge_base_answer_service import (
    KnowledgeBaseAnswerService,
)
from application.knowledge.knowledge_agent import KnowledgeAgent
from application.meetings.meeting_intelligence_service import (
    MeetingIntelligenceService,
)
from infrastructure.llm.operational_understanding import (
    LLMOperationalUnderstanding,
)
from infrastructure.llm.knowledge_understanding import (
    LLMKnowledgeUnderstanding,
)
from infrastructure.llm.organizational_intent_understanding import (
    LLMOrganizationalIntentUnderstanding,
)


class RecordingLLM:
    def __init__(self, response: str = "Test response"):
        self.response = response
        self.last_prompt: str | None = None

    def generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self.response


# =============================================================================
# 1. SIMPLE REASONING SERVICE PROMPT & FALLBACK TESTS
# =============================================================================

def test_simple_reasoning_prompts_request_first_person_and_plain_language():
    """Verify that SimpleReasoningService prompts request natural first-person style."""
    mock_llm = RecordingLLM("I found the database we use.")
    service = SimpleReasoningService(
        repository=None,
        communication_repository=MagicMock(),
        llm_client=mock_llm,
    )

    q = Question(text="What database do we use?")
    evidence = ["We use PostgreSQL in production."]

    service.answer_from_evidence(q, evidence)

    prompt = mock_llm.last_prompt
    assert prompt is not None

    # First-person style instructions
    assert 'first person as a helpful, thoughtful teammate' in prompt
    assert '"I", "I\'ll", "I\'ve", "don\'t", "can\'t"' in prompt
    assert 'everyday English instead of corporate or technical jargon' in prompt
    assert 'short, clear sentences' in prompt

    # Uncertainty in first person
    assert "I don't have enough information to answer that confidently" in prompt

    # Factual grounding and anti-hallucination rules intact
    assert "Do not invent facts" in prompt
    assert "Do not assume information that is not present" in prompt
    assert "Never mention documents, provided information, evidence, sources" in prompt
    assert "Never output safety classifications or moderation metadata" in prompt

    # Source-referencing instruction permits natural "I found"
    assert '"I found..." or "I don\'t have..." are welcome' in prompt


def test_simple_reasoning_answer_prompt_requests_first_person():
    """Verify SimpleReasoningService.answer prompt includes first-person instructions."""
    comm_repo = MagicMock()
    mock_comm = MagicMock()
    mock_comm.content.body = "We use PostgreSQL."
    comm_repo.search.return_value = [mock_comm]

    mock_llm = RecordingLLM("We use PostgreSQL.")
    service = SimpleReasoningService(
        repository=None,
        communication_repository=comm_repo,
        llm_client=mock_llm,
    )

    service.answer(Question(text="What database do we use?"))

    prompt = mock_llm.last_prompt
    assert prompt is not None
    assert 'first person as a helpful, thoughtful teammate' in prompt
    assert "I don't have enough information to answer that confidently" in prompt
    assert "Never output safety classifications or moderation metadata" in prompt


def test_simple_reasoning_no_information_fallback_is_first_person():
    """Verify SimpleReasoningService default no-info response is in first person."""
    service = SimpleReasoningService(
        repository=None,
        communication_repository=MagicMock(),
        llm_client=RecordingLLM(),
    )

    no_info = service._no_information_text(Question(text="Unknown topic"))
    assert no_info == NO_INFORMATION_RESPONSE
    assert "I don't have enough information" in no_info
    assert "POLIS does not have enough information" not in no_info


# =============================================================================
# 2. KNOWLEDGE BASE ANSWER SERVICE PROMPT TESTS
# =============================================================================

def test_knowledge_base_answer_prompt_requests_first_person_teammate():
    """Verify KnowledgeBaseAnswerService prompt requests first-person teammate tone."""
    mock_llm = RecordingLLM("Employees receive 25 days of annual leave.")
    service = KnowledgeBaseAnswerService(llm_client=mock_llm)

    chunk = KnowledgeBaseChunk(
        id="c1",
        document_id="d1",
        chunk_index=0,
        content="Annual leave is 25 days.",
        qdrant_point_id="p1",
        metadata={"document_name": "handbook.md"},
    )
    service.answer("How many days of leave do we get?", [(chunk, 0.95)])

    prompt = mock_llm.last_prompt
    assert prompt is not None

    # First-person tone
    assert 'first person as a helpful, thoughtful teammate' in prompt
    assert 'everyday English instead of corporate or technical jargon' in prompt
    assert 'short, clear sentences' in prompt

    # Uncertainty instruction in first person
    assert "I don't have enough information in the knowledge base to answer that confidently" in prompt

    # Grounding contract intact
    assert "Answer the user's question using ONLY the Knowledge Base" in prompt
    assert "Do not invent or assume facts" in prompt
    assert "Do not mention embeddings, vector search, retrieval, databases" in prompt


# =============================================================================
# 3. KNOWLEDGE AGENT PROMPT & FALLBACK TESTS
# =============================================================================

def test_knowledge_agent_prompt_and_fallback_first_person():
    """Verify KnowledgeAgent prompt and fallback use first person."""
    mock_llm = RecordingLLM("PostgreSQL is used for persistence.")
    agent = KnowledgeAgent(
        knowledge_repository=MagicMock(),
        llm_client=mock_llm,
    )

    # Empty evidence fallback
    ans = agent._generate_answer("What is the DB?", [], [])
    assert ans.text == "I don't have enough information to answer that question."
    assert "POLIS does not have enough information" not in ans.text

    # Prompt with evidence
    agent._generate_answer("What is the DB?", [], ["DB evidence line"])
    assert mock_llm.last_prompt is not None
    assert "first person as a helpful, thoughtful teammate" in mock_llm.last_prompt
    assert "plain first person" in mock_llm.last_prompt


# =============================================================================
# 4. MEETING INTELLIGENCE SERVICE PROMPTS
# =============================================================================

def test_meeting_summary_prompt_requests_plain_english():
    """Verify meeting summary prompt requests plain everyday English without corporate jargon."""
    mock_llm = RecordingLLM("The team decided to release on Friday.")
    service = MeetingIntelligenceService(
        transcript_repository=MagicMock(),
        llm_client=mock_llm,
    )

    summary_prompt = service._build_summary_prompt(
        meeting_id="m-123",
        context="Alice: We agreed to launch Friday.",
    )
    assert "everyday plain English rather than corporate jargon" in summary_prompt
    assert "short, clear sentences" in summary_prompt
    assert "Do not invent participants, decisions, actions, dates, or outcomes" in summary_prompt

    synthesis_prompt = service._build_synthesis_prompt(
        meeting_id="m-123",
        context="Section 1: Release on Friday agreed.",
    )
    assert "everyday plain English rather than corporate jargon" in synthesis_prompt
    assert "short, clear sentences" in synthesis_prompt


def test_meeting_structured_analysis_prompts_remain_strict_json():
    """Verify meeting structured analysis prompts strictly require valid JSON."""
    service = MeetingIntelligenceService(
        transcript_repository=MagicMock(),
        llm_client=RecordingLLM(),
    )

    analysis_prompt = service._build_analysis_prompt(
        meeting_id="m-123",
        context="transcript text",
        canonical_events="None recorded.",
    )
    assert "Return ONLY valid JSON in this exact structure:" in analysis_prompt
    assert '"summary":' in analysis_prompt
    assert '"topics":' in analysis_prompt
    assert '"confidence": 0.0' in analysis_prompt

    chunk_prompt = service._build_analysis_chunk_prompt(
        meeting_id="m-123",
        chunk="chunk text",
        index=1,
        total=2,
        canonical_events="None.",
    )
    assert "Return ONLY valid JSON with summary, topics, decisions" in chunk_prompt



# =============================================================================
# 5. CALENDAR AGENT NATURAL FIRST-PERSON & TRUTHFUL CONFIRMATION
# =============================================================================

@pytest.fixture
def calendar_agent() -> CalendarAgent:
    repo = InMemoryCalendarRepository()
    mock_provider = MagicMock()
    mock_provider.resolve_user_id.return_value = "U_TARGET"
    mock_provider.resolve_team_members.return_value = ["U_DEV1"]
    mock_provider.get_organization_channel_id.return_value = "C_MAIN"

    audience_service = AudienceResolutionService(
        directory_provider=mock_provider,
        organization_channel_id="C_MAIN",
    )
    service = CalendarService(
        repository=repo,
        audience_service=audience_service,
        reminder_policy=CalendarReminderPolicy(offset_hours=15),
        default_timezone="Asia/Kolkata",
    )
    return CalendarAgent(
        service=service,
        default_timezone="Asia/Kolkata",
    )


def test_calendar_schedule_natural_first_person_on_success(calendar_agent):
    """Calendar schedule emits 'Done! I’ve added it to the calendar.' only after confirmed success."""
    msg = "schedule activity 'Product Roadmap Sync' on 2026-11-25 14:00 for organization"
    res = calendar_agent.handle_message(msg, user_id="U_CREATOR")

    assert res is not None
    assert "Done! I've added it to the calendar." in res
    assert "Successfully scheduled" in res
    assert "Product Roadmap Sync" in res

    # Verify actually persisted
    entries = calendar_agent.service.list_entries()
    assert len(entries) == 1
    assert entries[0].title == "Product Roadmap Sync"


def test_calendar_cancel_natural_first_person_on_success(calendar_agent):
    """Calendar cancel emits first-person confirmation only after confirmed cancellation."""
    entry = calendar_agent.service.create_entry(
        title="1:1 Sync",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc),
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_CREATOR",
    )

    res = calendar_agent.handle_message(f"cancel event {entry.entry_id}", user_id="U_CREATOR")
    assert res is not None
    assert "Done! I've cancelled it." in res
    assert "Successfully cancelled" in res


def test_calendar_update_natural_first_person_on_success(calendar_agent):
    """Calendar reschedule emits first-person confirmation only after confirmed update."""
    entry = calendar_agent.service.create_entry(
        title="Sprint Retro",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_CREATOR",
        start_time=datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc),
        audience_type=CalendarAudienceType.INDIVIDUAL,
        audience_identifier="U_CREATOR",
    )

    res = calendar_agent.handle_message(
        f"reschedule event {entry.entry_id} to 2026-12-02 11:00",
        user_id="U_CREATOR",
    )
    assert res is not None
    assert "Done! I've updated the calendar." in res
    assert "Successfully rescheduled" in res


def test_calendar_empty_list_natural_first_person(calendar_agent):
    """Empty calendar listing gives natural first-person response."""
    res = calendar_agent.handle_message("what is on the calendar?", user_id="U_USER")
    assert res is not None
    assert "I didn't find any scheduled upcoming entries on the calendar." in res


def test_calendar_unauthorized_action_first_person(calendar_agent):
    """Unauthorized calendar attempt gives clear, polite first-person response."""
    entry = calendar_agent.service.create_entry(
        title="Admin Meeting",
        entry_type=CalendarEntryType.ACTIVITY,
        creator_id="U_ADMIN",
        start_time=datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc),
        audience_type=CalendarAudienceType.ORGANIZATION,
        audience_identifier="organization",
    )

    res = calendar_agent.handle_message(f"cancel event {entry.entry_id}", user_id="U_OTHER")
    assert res is not None
    assert "not authorized" in res.lower()
    assert "I can't cancel this calendar entry because you are not authorized" in res


# =============================================================================
# 6. INTERNAL STRUCTURED ANALYZERS REMAIN UNTOUCHED STRICT JSON
# =============================================================================

def test_internal_analyzers_remain_strict_json():
    """Verify internal LLM analyzers strictly enforce valid JSON schemas."""
    mock_client = MagicMock()
    mock_client.generate.return_value = '{"is_operational": false}'

    op = LLMOperationalUnderstanding(mock_client)
    op.analyze("Some text")
    prompt = mock_client.generate.call_args[0][0]
    assert "Return ONLY valid JSON in this exact structure:" in prompt
    assert '"is_operational": true' in prompt

    mock_client.generate.return_value = '{"is_knowledge": false}'
    kw = LLMKnowledgeUnderstanding(mock_client)
    kw.analyze("Some text")
    prompt_kw = mock_client.generate.call_args[0][0]
    assert "Return ONLY valid JSON in this exact structure:" in prompt_kw
    assert '"is_knowledge": true' in prompt_kw

    mock_client.generate.return_value = '{"has_intent": false, "intent_type": null, "confidence": 0.0, "explanation": null}'
    intent = LLMOrganizationalIntentUnderstanding(mock_client)
    intent.analyze("Some text")
    prompt_intent = mock_client.generate.call_args[0][0]
    assert "Return ONLY valid JSON in this exact structure:" in prompt_intent
