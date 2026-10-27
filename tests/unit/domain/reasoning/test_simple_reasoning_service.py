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
    def __init__(self, response: str = "We use PostgreSQL."):
        self.response = response
        self.last_prompt: str | None = None

    def generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self.response


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


# ==========================================================
# REGRESSION TESTS
# ==========================================================

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def test_exact_phrase_containing_today_regression_a():
    """
    Case A: Quoted exact phrase containing 'today' must not activate
    current-day filtering, and matching historical messages remain eligible.
    Legitimate questions about 'today' must continue to filter to current day.
    """
    query_exact = 'Search the exact phrase "I am working on Publishing Calendar today".'

    # 1. Date window resolution: quoted phrase should not trigger current day
    start_time, end_time = SimpleReasoningService._resolve_date_window(query_exact)
    assert start_time is None
    assert end_time is None

    # 2. Historical message from 18 September 2026 must be eligible for retrieval
    repo = InMemoryCommunicationRepository()
    hist_comm = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="hist-slack-1",
        actor=Actor(
            identity=CommunicationIdentity(internal_id="U0BB8T4BVEK"),
            display_name="AgenT",
        ),
        channel=Channel(
            identity=CommunicationIdentity(internal_id="C0BG7NWMD6D"),
            name="polis_tests",
            channel_type="public",
        ),
        content=Content(
            body="I am working on Publishing Calendar today - TEST 123",
        ),
    )
    hist_comm.created_at = datetime(2026, 9, 18, 7, 47, 50, tzinfo=timezone.utc)
    repo.save(hist_comm)

    service = SimpleReasoningService(
        repository=None,
        communication_repository=repo,
        llm_client=FakeLLM(),
    )

    evidence = service.retrieve_evidence(
        Question(text=query_exact)
    )
    assert len(evidence) == 1
    assert "Publishing Calendar" in evidence[0]

    # 3. Legitimate questions about today must still trigger current day window
    legit_start, legit_end = SimpleReasoningService._resolve_date_window("What am I working on today?")
    today_start, today_end = SimpleReasoningService._today_window()
    assert legit_start == today_start
    assert legit_end == today_end


def test_historical_date_query_regression_b():
    """
    Case B: Historical date query must retain its historical date window
    and not accidentally apply current-day filtering.
    """
    query = "What task did AgenT explicitly state in the message posted on 18 September 2026?"
    start_time, end_time = SimpleReasoningService._resolve_date_window(query)

    expected_start = datetime(2026, 9, 18, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    expected_end = datetime(2026, 9, 19, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    assert start_time == expected_start
    assert end_time == expected_end

    # Current-day window must not be applied
    today_start, today_end = SimpleReasoningService._today_window()
    assert start_time != today_start


def test_sender_aware_evidence_regression_c():
    """
    Case C: Communication evidence must include the sender's display name and stable ID
    when available. Unknown senders must be handled safely without crashing or inventing
    an identity. Message text, timestamp, timezone, and ordering remain unchanged.
    """
    repo = InMemoryCommunicationRepository()

    # Communication 1: Full actor with display name and stable ID
    comm1 = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="comm-1",
        actor=Actor(
            identity=CommunicationIdentity(internal_id="U0BB8T4BVEK"),
            display_name="AgenT",
        ),
        channel=Channel(
            identity=CommunicationIdentity(internal_id="C001"),
            name="general",
            channel_type="public",
        ),
        content=Content(body="I am working on Publishing Calendar today - TEST 123"),
    )
    comm1.created_at = datetime(2026, 9, 18, 7, 47, 50, tzinfo=timezone.utc)
    repo.save(comm1)

    # Communication 2: Unknown sender (actor is None)
    comm2 = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="comm-2",
        actor=Actor(
            identity=CommunicationIdentity(internal_id="TEMP"),
            display_name="Placeholder",
        ),
        channel=Channel(
            identity=CommunicationIdentity(internal_id="C001"),
            name="general",
            channel_type="public",
        ),
        content=Content(body="System automated alert triggered"),
    )
    comm2.created_at = datetime(2026, 9, 18, 8, 0, 0, tzinfo=timezone.utc)
    comm2.actor = None  # test unknown actor
    repo.save(comm2)

    # Communication 3: Actor with only display name
    comm3_actor = Actor(
        identity=CommunicationIdentity(internal_id="U_ALICE"),
        display_name="Alice",
    )
    comm3 = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="comm-3",
        actor=comm3_actor,
        channel=Channel(
            identity=CommunicationIdentity(internal_id="C001"),
            name="general",
            channel_type="public",
        ),
        content=Content(body="Reviewing pull request"),
    )
    comm3.created_at = datetime(2026, 9, 18, 8, 30, 0, tzinfo=timezone.utc)
    # Simulate missing internal_id
    comm3.actor = type("PartialActor", (), {"display_name": "Alice", "identity": None})()
    repo.save(comm3)

    # Communication 4: Actor with only internal_id
    comm4 = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="comm-4",
        actor=comm3_actor,
        channel=Channel(
            identity=CommunicationIdentity(internal_id="C001"),
            name="general",
            channel_type="public",
        ),
        content=Content(body="Deployed artifact"),
    )
    comm4.created_at = datetime(2026, 9, 18, 9, 0, 0, tzinfo=timezone.utc)
    comm4.actor = type(
        "PartialActor",
        (),
        {"display_name": None, "identity": type("Id", (), {"internal_id": "U_BOB"})()},
    )()
    repo.save(comm4)

    service = SimpleReasoningService(
        repository=None,
        communication_repository=repo,
        llm_client=FakeLLM(),
    )

    # Retrieve comm1 specifically
    ev1 = service.retrieve_evidence(
        Question(text='Search the exact phrase "Publishing Calendar"')
    )
    assert len(ev1) == 1
    assert "Sender: AgenT" in ev1[0]
    assert "U0BB8T4BVEK" not in ev1[0]
    assert "Message: I am working on Publishing Calendar today - TEST 123" in ev1[0]
    assert "Communication time: 2026-09-18 13:17:50 IST" in ev1[0]

    # Retrieve comm2 (unknown actor)
    ev2 = service.retrieve_evidence(
        Question(text='Search the exact phrase "automated alert"')
    )
    assert len(ev2) == 1
    assert "Sender:" not in ev2[0]  # No invented identity
    assert "Message: System automated alert triggered" in ev2[0]
    assert "Communication time: 2026-09-18 13:30:00 IST" in ev2[0]

    # Retrieve comm3 (display name only)
    ev3 = service.retrieve_evidence(
        Question(text='Search the exact phrase "pull request"')
    )
    assert len(ev3) == 1
    assert "Sender: Alice" in ev3[0]

    # Retrieve comm4 (internal_id only)
    ev4 = service.retrieve_evidence(
        Question(text='Search the exact phrase "Deployed artifact"')
    )
    assert len(ev4) == 1
    assert "Sender: U_BOB" in ev4[0]


def test_named_person_grounding_regression_d():
    """
    Case D: When a question names AgenT and retrieved evidence identifies
    the sender as AgenT, the evidence supplied to reasoning contains enough
    information to associate the message with that person.
    """
    repo = InMemoryCommunicationRepository()
    comm = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="comm-agent-1",
        actor=Actor(
            identity=CommunicationIdentity(internal_id="U0BB8T4BVEK"),
            display_name="AgenT",
        ),
        channel=Channel(
            identity=CommunicationIdentity(internal_id="C0BG7NWMD6D"),
            name="polis_tests",
            channel_type="public",
        ),
        content=Content(body="I am working on Publishing Calendar today - TEST 123"),
    )
    comm.created_at = datetime(2026, 9, 18, 7, 47, 50, tzinfo=timezone.utc)
    repo.save(comm)

    fake_llm = FakeLLM(response="AgenT was working on Publishing Calendar.")
    service = SimpleReasoningService(
        repository=None,
        communication_repository=repo,
        llm_client=fake_llm,
    )

    q = Question(
        text='Search the exact phrase "Publishing Calendar"',
        target_user_id="U0BB8T4BVEK",
        target_user_name="AgenT",
    )

    evidence = service.retrieve_evidence(q)
    assert len(evidence) == 1
    assert "Sender: AgenT" in evidence[0]
    assert "U0BB8T4BVEK" not in evidence[0]

    answer = service.answer_from_evidence(q, evidence)
    assert fake_llm.last_prompt is not None
    assert "Sender: AgenT" in fake_llm.last_prompt
    assert "U0BB8T4BVEK" not in fake_llm.last_prompt
    assert "I am working on Publishing Calendar today - TEST 123" in fake_llm.last_prompt
    assert answer.text == "AgenT was working on Publishing Calendar."


def test_regression_safety_e():
    """
    Case E: Normal questions about 'today', 'yesterday', and explicit dates
    must retain their intended behavior.
    """
    today_start, today_end = SimpleReasoningService._today_window()

    # 'today'
    s1, e1 = SimpleReasoningService._resolve_date_window("What am I working on today?")
    assert s1 == today_start
    assert e1 == today_end

    # 'yesterday'
    s2, e2 = SimpleReasoningService._resolve_date_window("What was completed yesterday?")
    assert s2 == today_start - (today_end - today_start)
    assert e2 == today_start

    # Explicit date with day first
    s3, e3 = SimpleReasoningService._resolve_date_window("What happened on 18 September 2026?")
    assert s3 == datetime(2026, 9, 18, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert e3 == datetime(2026, 9, 19, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    # Explicit date with month first
    s4, e4 = SimpleReasoningService._resolve_date_window("Updates from September 18, 2026")
    assert s4 == datetime(2026, 9, 18, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert e4 == datetime(2026, 9, 19, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    # Temporal intent outside quotes preserved
    s5, e5 = SimpleReasoningService._resolve_date_window('Search "I am working on Publishing Calendar today" today')
    assert s5 == today_start
    assert e5 == today_end

    # Question without dates
    s6, e6 = SimpleReasoningService._resolve_date_window("What database do we use?")
    assert s6 is None
    assert e6 is None


def test_raw_slack_id_never_treated_as_display_name():
    """
    Ensure raw Slack IDs and mentions are never exposed as human-readable display names,
    even if an actor's display_name was set to the raw ID.
    """
    # 1. Raw Slack user ID in display_name
    actor_with_raw_name = {
        "display_name": "U0BU14F6CTD",
        "identity": {"internal_id": "U0BU14F6CTD"},
    }
    assert SimpleReasoningService._format_actor(actor_with_raw_name) is None

    # 2. Raw Slack mention in display_name
    actor_with_mention = {
        "display_name": "<@U0BU14F6CTD>",
        "identity": {"internal_id": "U0BU14F6CTD"},
    }
    assert SimpleReasoningService._format_actor(actor_with_mention) is None

    # 3. Raw Slack ID in internal_id with missing display_name
    actor_with_raw_id_only = {
        "display_name": None,
        "identity": {"internal_id": "U0BU14F6CTD"},
    }
    assert SimpleReasoningService._format_actor(actor_with_raw_id_only) is None

    # 4. Valid human display name with raw Slack internal_id
    actor_with_resolved_name = {
        "display_name": "Hemant Kumar Sah",
        "identity": {"internal_id": "U0BU14F6CTD"},
    }
    assert SimpleReasoningService._format_actor(actor_with_resolved_name) == "Hemant Kumar Sah"


def test_raw_slack_id_resolved_via_identity_resolver():
    """
    When an identity resolver is available, raw Slack IDs are resolved to display names.
    If resolution fails, it returns None rather than leaking the raw ID.
    """
    class MockIdentityResolver:
        def get_display_name(self, user_id: str) -> str:
            if user_id == "U0BU14F6CTD":
                return "Hemant Kumar Sah"
            raise RuntimeError("User not found")

    resolver = MockIdentityResolver()

    # Actor has raw ID in display_name and internal_id
    actor = {
        "display_name": "U0BU14F6CTD",
        "identity": {"internal_id": "U0BU14F6CTD"},
    }
    formatted = SimpleReasoningService._format_actor(actor, identity_resolver=resolver)
    assert formatted == "Hemant Kumar Sah"

    # Actor with unresolvable raw ID
    unresolvable_actor = {
        "display_name": "U9999999999",
        "identity": {"internal_id": "U9999999999"},
    }
    formatted_unresolved = SimpleReasoningService._format_actor(
        unresolvable_actor, identity_resolver=resolver
    )
    assert formatted_unresolved is None


def test_internal_id_filtering_preserved_while_hiding_raw_id():
    """
    Verify that internal IDs remain fully functional for database retrieval and filtering,
    while evidence generation prevents the raw ID from being output as a person's name.
    """
    repo = InMemoryCommunicationRepository()
    comm = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="comm-raw-id",
        actor=Actor(
            identity=CommunicationIdentity(internal_id="U0BU14F6CTD"),
            display_name="U0BU14F6CTD",  # Discarded/unresolved name scenario
        ),
        channel=Channel(
            identity=CommunicationIdentity(internal_id="C001"),
            name="general",
            channel_type="public",
        ),
        content=Content(body="Granted calendar access to project sync"),
    )
    comm.created_at = datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc)
    repo.save(comm)

    # 1. Without identity resolver: internal ID filtering works, but Sender line is omitted
    service_no_resolver = SimpleReasoningService(
        repository=None,
        communication_repository=repo,
        llm_client=FakeLLM(),
    )
    question = Question(
        text="calendar access",
        target_user_id="U0BU14F6CTD",
    )
    evidence = service_no_resolver.retrieve_evidence(question)
    assert len(evidence) == 1
    assert "Granted calendar access to project sync" in evidence[0]
    assert "Sender:" not in evidence[0]
    assert "U0BU14F6CTD" not in evidence[0]

    # 2. With identity resolver: internal ID filtering works AND display name is resolved
    class MockIdentityResolver:
        def get_display_name(self, user_id: str) -> str:
            if user_id == "U0BU14F6CTD":
                return "Hemant Kumar Sah"
            return user_id

    service_with_resolver = SimpleReasoningService(
        repository=None,
        communication_repository=repo,
        llm_client=FakeLLM(),
        identity_resolver=MockIdentityResolver(),
    )
    evidence_resolved = service_with_resolver.retrieve_evidence(question)
    assert len(evidence_resolved) == 1
    assert "Sender: Hemant Kumar Sah" in evidence_resolved[0]
    assert "U0BU14F6CTD" not in evidence_resolved[0]
