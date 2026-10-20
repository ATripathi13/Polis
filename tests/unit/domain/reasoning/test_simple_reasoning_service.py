from engines.communication.domain.aggregates import (
    CommunicationEvent,
)
from engines.communication.domain.enums import (
    EventSource,
)
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
)
from engines.communication.infrastructure.repositories import (
    InMemoryCommunicationRepository,
)
from domain.common.identifier import Identifier
from domain.reasoning import (
    Question,
    SimpleReasoningService,
)


class FakeLLM:
    def generate(self, prompt: str) -> str:
        return "We use PostgreSQL."


def test_answer_question_from_communication_memory():

    communication_repository = (
        InMemoryCommunicationRepository()
    )

    communication = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="test-1",
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id="USER-001",
            ),
            display_name="John Doe",
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id="CHANNEL-001",
            ),
            name="general",
            channel_type="public",
        ),
        content=Content(
            body="We use PostgreSQL as our database.",
        ),
    )

    communication_repository.save(
        communication
    )

    service = SimpleReasoningService(
        repository=None,
        communication_repository=(
            communication_repository
        ),
        llm_client=FakeLLM(),
    )

    answer = service.answer(
        Question(
            text="What database do we use?",
        )
    )

    assert answer.text == "We use PostgreSQL."
    assert answer.confidence == 0.8
    assert answer.evidence == [
        "We use PostgreSQL as our database."
    ]

def test_exact_phrase_containing_today_does_not_force_current_date_window():
    start, end = SimpleReasoningService._resolve_date_window(
        'Search the exact phrase "I am working on Publishing Calendar today".'
    )
    assert start is None
    assert end is None


def test_historical_date_query_parses_explicit_year():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    start, end = SimpleReasoningService._resolve_date_window(
        "What task did AgenT explicitly state in the message posted on 18 September 2026?"
    )
    tz = ZoneInfo("Asia/Kolkata")
    assert start == datetime(2026, 9, 18, 0, 0, tzinfo=tz)
    assert end == datetime(2026, 9, 19, 0, 0, tzinfo=tz)


def test_today_question_still_uses_current_date_window():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    start, end = SimpleReasoningService._resolve_date_window(
        "What am I working on today?"
    )
    assert start is not None
    assert end is not None
    assert start.tzinfo == ZoneInfo("Asia/Kolkata")
    assert end > start


def test_sender_identity_is_in_retrieved_evidence():
    from engines.communication.domain.aggregates import CommunicationEvent
    from engines.communication.domain.enums import EventSource
    from engines.communication.domain.value_objects import Actor, Channel, CommunicationIdentity, Content
    from engines.communication.infrastructure.repositories import InMemoryCommunicationRepository
    from domain.common.identifier import Identifier

    repo = InMemoryCommunicationRepository()
    event = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="sender-evidence-test",
        actor=Actor(
            identity=CommunicationIdentity(internal_id="U0BB8T4BVEK"),
            display_name="AgenT",
        ),
        channel=Channel(
            identity=CommunicationIdentity(internal_id="CHANNEL-TEST"),
            name="polis_tests",
            channel_type="public",
        ),
        content=Content(body="I am working on Publishing Calendar today - TEST 123"),
    )
    repo.save(event)

    service = SimpleReasoningService(
        repository=None,
        communication_repository=repo,
        llm_client=FakeLLM(),
    )
    evidence = service.retrieve_evidence(
        Question(text="Publishing Calendar")
    )

    assert evidence
    assert any("Sender: AgenT (U0BB8T4BVEK)" in item for item in evidence)
    assert any("I am working on Publishing Calendar today - TEST 123" in item for item in evidence)


def test_exact_phrase_is_extracted_for_retrieval():
    service = SimpleReasoningService(
        repository=None,
        communication_repository=None,
        llm_client=FakeLLM(),
    )
    query = service._build_retrieval_query(
        Question(text='Search the exact phrase "I am working on Publishing Calendar today".')
    )
    assert query == "I am working on Publishing Calendar today"


def test_explicit_year_is_used_instead_of_current_year():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    start, end = SimpleReasoningService._resolve_date_window(
        "What happened on 18 September 2024?"
    )
    tz = ZoneInfo("Asia/Kolkata")
    assert start == datetime(2024, 9, 18, 0, 0, tzinfo=tz)
    assert end == datetime(2024, 9, 19, 0, 0, tzinfo=tz)


def test_month_first_date_with_explicit_year():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    start, end = SimpleReasoningService._resolve_date_window(
        "What happened on September 18, 2024?"
    )
    tz = ZoneInfo("Asia/Kolkata")
    assert start == datetime(2024, 9, 18, 0, 0, tzinfo=tz)
    assert end == datetime(2024, 9, 19, 0, 0, tzinfo=tz)
