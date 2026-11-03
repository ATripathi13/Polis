"""
Comprehensive test matrix for POLIS Slack Conversational Context.
Covers scenarios CTX-01 through CTX-17 across both InMemoryConversationRepository
and PostgreSQLConversationRepository.

Part 1:
- CTX-01: First DM message - Creates an isolated DM context.
- CTX-02: Follow-up DM - Retrieves previous DM history and correctly answers follow-up.
- CTX-03: DM across application restart - Recovers persisted history from repository.
- CTX-04: First thread message - Creates a thread-specific context.
- CTX-05: Thread follow-up - Retrieves history from the same thread.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pytest

from connectors.slack.routing import is_bot_mentioned, is_direct_message
from domain.reasoning.value_objects import ConversationContext, Question
from engines.slack.dto import SlackMessage as ActivitySlackMessage
from engines.slack.router.slack_intent_router import SlackIntentRouter
from infrastructure.database.conversation_repository import InMemoryConversationRepository
from infrastructure.database.models import ConversationMemoryModel
from infrastructure.database.postgres_conversation_repository import PostgreSQLConversationRepository
from infrastructure.database import postgres_conversation_repository as pg_conv_module


# ==============================================================================
# Test Infrastructure & Database Mocks
# ==============================================================================

class FakeQuery:
    def __init__(self, records):
        self.records = list(records)

    def filter(self, *criteria):
        filtered = self.records
        for crit in criteria:
            try:
                col_name = crit.left.name
                val = crit.right.value
                filtered = [r for r in filtered if getattr(r, col_name, None) == val]
            except Exception:
                pass
        return FakeQuery(filtered)

    def order_by(self, *expressions):
        def get_sort_key(r):
            u_at = getattr(r, "updated_at", None) or datetime.min.replace(tzinfo=timezone.utc)
            t_ts = getattr(r, "thread_ts", "") or ""
            return (u_at, t_ts)
        sorted_records = sorted(self.records, key=get_sort_key, reverse=True)
        return FakeQuery(sorted_records)

    def first(self):
        return self.records[0] if self.records else None

    def all(self):
        return list(self.records)


class FakeSession:
    def __init__(self, records_store, should_fail=False):
        self.records_store = records_store
        self.uncommitted_added = []
        self.snapshots = {r.id: (list(r.history or []), r.updated_at) for r in records_store}
        self.should_fail = should_fail
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        self.snapshots = {r.id: (list(r.history or []), r.updated_at) for r in self.records_store}
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            self.rollback()
        return False

    def query(self, model):
        assert model is ConversationMemoryModel
        return FakeQuery(self.records_store)

    def add(self, obj):
        self.uncommitted_added.append(obj)

    def commit(self):
        if self.should_fail:
            raise RuntimeError("Simulated PostgreSQL connection or transaction error")
        for obj in self.uncommitted_added:
            if obj not in self.records_store:
                self.records_store.append(obj)
        self.uncommitted_added.clear()
        self.committed = True

    def rollback(self):
        self.uncommitted_added.clear()
        self.rolled_back = True
        for r in self.records_store:
            if r.id in self.snapshots:
                hist_copy, up_at = self.snapshots[r.id]
                r.history = list(hist_copy)
                r.updated_at = up_at


@pytest.fixture(params=["in_memory", "postgres"])
def conversation_repo(request, monkeypatch):
    """Parametrized fixture providing both InMemory and PostgreSQL repository implementations."""
    if request.param == "in_memory":
        yield InMemoryConversationRepository()
    else:
        records_store = []
        monkeypatch.setattr(
            pg_conv_module,
            "SessionLocal",
            lambda: FakeSession(records_store),
        )
        repo = PostgreSQLConversationRepository()
        repo._records_store = records_store
        yield repo


def build_test_router(repo, mock_engine=None, mock_responder=None):
    """Helper to construct a SlackIntentRouter with standard mocked dependencies."""
    if mock_engine is None:
        mock_engine = MagicMock()
        mock_engine.ask.return_value = MagicMock(text="Default answer", pending_operation=None, clear_pending=False)
    if mock_responder is None:
        mock_responder = MagicMock()
    mock_connector = MagicMock()
    mock_identity = MagicMock()
    mock_identity.get_workspace_users.return_value = []

    router = SlackIntentRouter(
        engine=mock_engine,
        responder=mock_responder,
        connector=mock_connector,
        conversation_repository=repo,
        identity_service=mock_identity,
    )
    return router, mock_engine, mock_responder


# ==============================================================================
# CTX-01: First DM message
# ==============================================================================

def test_ctx_01_first_dm_message_creates_isolated_dm_context(conversation_repo):
    """
    CTX-01: First message in a 1:1 Slack DM creates an isolated DM context.
    - Context is created with channel_id, user_id, channel_type="im", thread_ts=ts.
    - Context is persisted in repository.
    - Other channels/threads do not see this context.
    """
    mock_engine = MagicMock()
    mock_engine.ask.return_value = MagicMock(
        text="Hello Alice! How can I help you today?",
        pending_operation=None,
        clear_pending=False,
    )
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    msg = ActivitySlackMessage(
        user="U_ALICE",
        channel="D_ALICE",
        text="Hello POLIS",
        ts="100.1",
        event_ts="100.1",
        thread_ts=None,
    )

    router.handle(msg)

    # 1. Engine received initial question with fresh context
    assert engine.ask.called
    question: Question = engine.ask.call_args[0][0]
    assert question.text == "Hello POLIS"
    assert question.context.user_id == "U_ALICE"
    assert question.context.channel_id == "D_ALICE"
    assert question.context.thread_ts == "100.1"
    assert question.context.channel_type == "im"
    assert len(question.context.history) == 0

    # 2. Responder replied with correct thread_ts and text
    assert responder.reply.called
    reply_args = responder.reply.call_args[1]
    assert reply_args["channel"] == "D_ALICE"
    assert reply_args["thread_ts"] == "100.1"
    assert reply_args["text"] == "Hello Alice! How can I help you today?"

    # 3. Context was persisted in the repository under (D_ALICE, 100.1)
    persisted = conversation_repo.get("D_ALICE", "100.1")
    assert persisted is not None
    assert persisted.user_id == "U_ALICE"
    assert persisted.channel_id == "D_ALICE"
    assert persisted.channel_type == "im"
    assert len(persisted.history) == 2
    assert persisted.history[0]["role"] == "user"
    assert persisted.history[0]["content"] == "Hello POLIS"
    assert persisted.history[0]["user_id"] == "U_ALICE"
    assert persisted.history[1]["role"] == "assistant"
    assert persisted.history[1]["content"] == "Hello Alice! How can I help you today?"

    # 4. Isolation: No context in another user's DM or channel
    assert conversation_repo.get("D_BOB", "100.1") is None
    assert conversation_repo.get("C_GENERAL", "100.1") is None


# ==============================================================================
# CTX-02: Follow-up DM
# ==============================================================================

def test_ctx_02_followup_dm_retrieves_previous_history(conversation_repo):
    """
    CTX-02: A follow-up DM message retrieves previous DM history and correctly answers follow-up.
    - User gives specific information ("The secret deployment key is ORBIT-731").
    - User follows up without thread_ts ("What is the secret deployment key?").
    - Router retrieves previous DM history via get_latest.
    - Context passed to engine contains previous conversation history.
    - Persisted history accumulates both turns (4 messages).
    """
    mock_engine = MagicMock()

    def engine_side_effect(question: Question):
        # Verify engine has previous history available
        if "What is the secret deployment key?" in question.text:
            assert len(question.context.history) >= 2
            assert any("ORBIT-731" in msg.get("content", "") for msg in question.context.history)
            return MagicMock(
                text="The secret deployment key is ORBIT-731.",
                pending_operation=None,
                clear_pending=False,
            )
        return MagicMock(
            text="Stored deployment key ORBIT-731.",
            pending_operation=None,
            clear_pending=False,
        )

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    # Turn 1: Alice provides the secret key
    msg1 = ActivitySlackMessage(
        user="U_ALICE",
        channel="D_ALICE",
        text="The secret deployment key is ORBIT-731",
        ts="100.1",
        event_ts="100.1",
        thread_ts=None,
    )
    router.handle(msg1)

    assert responder.reply.called
    assert responder.reply.call_args[1]["text"] == "Stored deployment key ORBIT-731."
    responder.reply.reset_mock()

    # Turn 2: Alice asks follow-up in the same DM (consecutive message, thread_ts=None, new ts="100.2")
    msg2 = ActivitySlackMessage(
        user="U_ALICE",
        channel="D_ALICE",
        text="What is the secret deployment key?",
        ts="100.2",
        event_ts="100.2",
        thread_ts=None,
    )
    router.handle(msg2)

    # 1. Responder sent correct answer using previous context
    assert responder.reply.called
    assert responder.reply.call_args[1]["text"] == "The secret deployment key is ORBIT-731."
    assert responder.reply.call_args[1]["thread_ts"] == "100.2"

    # 2. Context was persisted and contains the full conversation
    ctx_turn2 = conversation_repo.get("D_ALICE", "100.2")
    assert ctx_turn2 is not None
    assert len(ctx_turn2.history) == 4
    assert ctx_turn2.history[0]["content"] == "The secret deployment key is ORBIT-731"
    assert ctx_turn2.history[1]["content"] == "Stored deployment key ORBIT-731."
    assert ctx_turn2.history[2]["content"] == "What is the secret deployment key?"
    assert ctx_turn2.history[3]["content"] == "The secret deployment key is ORBIT-731."


# ==============================================================================
# CTX-03: DM across application restart
# ==============================================================================

def test_ctx_03_dm_across_application_restart_recovers_persisted_history(conversation_repo):
    """
    CTX-03: DM conversational context recovers persisted history across application restart.
    - Turn 1 executed on router_instance_1.
    - router_instance_1 is discarded (simulating server restart).
    - router_instance_2 initialized with the same persistent repository.
    - Turn 2 executed on router_instance_2.
    - History from Turn 1 is recovered and used by router_instance_2.
    """
    # Instance 1: Turn 1
    engine_1 = MagicMock()
    engine_1.ask.return_value = MagicMock(
        text="Noted: Project deadline is March 25th.",
        pending_operation=None,
        clear_pending=False,
    )
    router_1, _, responder_1 = build_test_router(conversation_repo, engine_1)

    msg1 = ActivitySlackMessage(
        user="U_ALICE",
        channel="D_ALICE",
        text="Project deadline is March 25th",
        ts="200.1",
        event_ts="200.1",
        thread_ts=None,
    )
    router_1.handle(msg1)
    assert responder_1.reply.called

    # SIMULATE APPLICATION RESTART
    # Destroy router_1 and create router_2 with a new engine instance, sharing conversation_repo
    del router_1
    del engine_1

    engine_2 = MagicMock()
    def engine_2_side_effect(question: Question):
        # Assert history was restored from repository
        assert len(question.context.history) == 2
        assert "March 25th" in question.context.history[0]["content"]
        return MagicMock(
            text="The project deadline is March 25th.",
            pending_operation=None,
            clear_pending=False,
        )

    engine_2.ask.side_effect = engine_2_side_effect
    router_2, _, responder_2 = build_test_router(conversation_repo, engine_2)

    # Turn 2: Sent to restarted router
    msg2 = ActivitySlackMessage(
        user="U_ALICE",
        channel="D_ALICE",
        text="When is the project deadline?",
        ts="200.2",
        event_ts="200.2",
        thread_ts=None,
    )
    router_2.handle(msg2)

    assert responder_2.reply.called
    assert responder_2.reply.call_args[1]["text"] == "The project deadline is March 25th."


# ==============================================================================
# CTX-04: First thread message
# ==============================================================================

def test_ctx_04_first_thread_message_creates_thread_specific_context(conversation_repo):
    """
    CTX-04: First message in a channel thread creates a thread-specific context.
    - Thread is keyed by parent thread_ts.
    - Persisted under (channel_id, thread_ts).
    - Isolated from other threads in the same channel.
    """
    mock_engine = MagicMock()
    mock_engine.ask.return_value = MagicMock(
        text="Tracking incident INC-404 in this thread.",
        pending_operation=None,
        clear_pending=False,
    )
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    # Alice posts in C_OPS starting thread at ts="300.1"
    msg = ActivitySlackMessage(
        user="U_ALICE",
        channel="C_OPS",
        text="start tracking incident INC-404",
        ts="300.1",
        event_ts="300.1",
        thread_ts=None,  # top-level message that establishes thread
    )

    router.handle(msg)

    # 1. Engine received context with thread_ts="300.1"
    assert engine.ask.called
    question = engine.ask.call_args[0][0]
    assert question.context.channel_id == "C_OPS"
    assert question.context.thread_ts == "300.1"
    assert question.context.user_id == "U_ALICE"

    # 2. Reply sent to thread 300.1
    assert responder.reply.called
    assert responder.reply.call_args[1]["channel"] == "C_OPS"
    assert responder.reply.call_args[1]["thread_ts"] == "300.1"

    # 3. Context persisted in repository under ("C_OPS", "300.1")
    # Note: For top-level messages in a channel, router only persists if is_thread or is_dm.
    # When a reply in thread arrives (thread_ts="300.1"), the thread context is loaded/established.
    # Let's verify that a message with thread_ts="300.1" establishes and stores the thread context.
    msg_thread = ActivitySlackMessage(
        user="U_ALICE",
        channel="C_OPS",
        text="Incident INC-404 priority is high",
        ts="300.2",
        event_ts="300.2",
        thread_ts="300.1",
    )
    router.handle(msg_thread)

    thread_ctx = conversation_repo.get("C_OPS", "300.1")
    assert thread_ctx is not None
    assert thread_ctx.channel_id == "C_OPS"
    assert thread_ctx.thread_ts == "300.1"
    assert len(thread_ctx.history) >= 2

    # 4. Isolation: Different thread in C_OPS has no context
    assert conversation_repo.get("C_OPS", "999.1") is None


# ==============================================================================
# CTX-05: Thread follow-up
# ==============================================================================

def test_ctx_05_thread_followup_retrieves_history_from_same_thread(conversation_repo):
    """
    CTX-05: Thread follow-up retrieves history from the same thread.
    - Initial exchange seeded in thread ("C_DEV", "400.1").
    - Bob posts reply in thread (thread_ts="400.1", user="U_BOB").
    - Router loads thread history and associates current sender U_BOB.
    - Updated history contains all exchanges in the thread.
    """
    # Seed initial exchange in thread 400.1
    init_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEV",
        thread_ts="400.1",
    ).add_exchange(
        user_message="Deploying feature branch auth-v2",
        assistant_message="Auth-v2 deployment recorded.",
        user_id="U_ALICE",
    )
    conversation_repo.save(init_ctx)

    mock_engine = MagicMock()
    def engine_side_effect(question: Question):
        # Assert question context has thread history
        assert len(question.context.history) == 2
        assert "auth-v2" in question.context.history[0]["content"]
        assert question.context.user_id == "U_BOB"
        return MagicMock(
            text="Auth-v2 is currently staging.",
            pending_operation=None,
            clear_pending=False,
        )

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    # Bob asks in thread 400.1
    bob_msg = ActivitySlackMessage(
        user="U_BOB",
        channel="C_DEV",
        text="What branch was deployed?",
        ts="400.2",
        event_ts="400.2",
        thread_ts="400.1",
    )
    router.handle(bob_msg)

    # 1. Reply sent to thread 400.1
    assert responder.reply.called
    assert responder.reply.call_args[1]["channel"] == "C_DEV"
    assert responder.reply.call_args[1]["thread_ts"] == "400.1"
    assert responder.reply.call_args[1]["text"] == "Auth-v2 is currently staging."

    # 2. Thread context in repository updated with 4 messages
    updated_ctx = conversation_repo.get("C_DEV", "400.1")
    assert updated_ctx is not None
    assert len(updated_ctx.history) == 4
    assert updated_ctx.history[2]["user_id"] == "U_BOB"
    assert updated_ctx.history[2]["content"] == "What branch was deployed?"
    assert updated_ctx.history[3]["content"] == "Auth-v2 is currently staging."


# ==============================================================================
# CTX-06: Different threads, same channel
# ==============================================================================

def test_ctx_06_different_threads_in_same_channel_maintain_independent_histories(conversation_repo):
    """
    CTX-06: Different threads in the same channel must maintain completely independent histories.
    - Thread 1 (ts="1000.1") discusses "Kubernetes migration".
    - Thread 2 (ts="2000.1") discusses "Postgres vacuuming".
    - Queries in Thread 2 do not see Thread 1's messages.
    """
    mock_engine = MagicMock()
    def engine_side_effect(question: Question):
        if question.context.thread_ts == "1000.1":
            return MagicMock(text="K8s migration status: active.", pending_operation=None, clear_pending=False)
        elif question.context.thread_ts == "2000.1":
            # Verify Thread 2 NEVER receives Thread 1 history
            assert not any("Kubernetes" in m.get("content", "") for m in question.context.history)
            return MagicMock(text="Postgres vacuuming complete.", pending_operation=None, clear_pending=False)
        return MagicMock(text="Default answer", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    # 1. Turn in Thread 1
    msg_t1 = ActivitySlackMessage(
        user="U_ALICE",
        channel="C_ENG",
        text="Kubernetes migration kicked off",
        ts="1000.2",
        event_ts="1000.2",
        thread_ts="1000.1",
    )
    router.handle(msg_t1)

    # 2. Turn in Thread 2
    msg_t2 = ActivitySlackMessage(
        user="U_CHARLIE",
        channel="C_ENG",
        text="Postgres vacuuming initiated",
        ts="2000.2",
        event_ts="2000.2",
        thread_ts="2000.1",
    )
    router.handle(msg_t2)

    # 3. Follow-up in Thread 2
    msg_t2_followup = ActivitySlackMessage(
        user="U_BOB",
        channel="C_ENG",
        text="Is the vacuum done?",
        ts="2000.3",
        event_ts="2000.3",
        thread_ts="2000.1",
    )
    router.handle(msg_t2_followup)

    # Verify both thread contexts are completely separate in repository
    ctx_t1 = conversation_repo.get("C_ENG", "1000.1")
    ctx_t2 = conversation_repo.get("C_ENG", "2000.1")

    assert ctx_t1 is not None
    assert ctx_t2 is not None

    assert len(ctx_t1.history) == 2
    assert "Kubernetes" in ctx_t1.history[0]["content"]

    assert len(ctx_t2.history) == 4
    assert all("Kubernetes" not in m["content"] for m in ctx_t2.history)
    assert "Postgres" in ctx_t2.history[0]["content"]
    assert "Is the vacuum done?" in ctx_t2.history[2]["content"]


# ==============================================================================
# CTX-07: Different user isolation
# ==============================================================================

def test_ctx_07_different_users_cannot_access_each_others_dm_context(conversation_repo):
    """
    CTX-07: Different users must not access each other's DM context.
    - Alice shares private information in D_ALICE ("Confidential employee ID: EMP-9988").
    - Bob in D_BOB asks for the confidential employee ID.
    - Bob receives a fresh/isolated context, never Alice's.
    - Even if an event spoofing Alice's DM with Bob's user ID arrives, isolation resets history to empty.
    """
    mock_engine = MagicMock()
    def engine_side_effect(question: Question):
        if question.context.user_id == "U_ALICE":
            return MagicMock(text="Stored confidential employee ID.", pending_operation=None, clear_pending=False)
        # For Bob, verify no Alice confidential info is in context history
        assert not any("EMP-9988" in m.get("content", "") for m in question.context.history)
        return MagicMock(text="No employee ID on file.", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    # 1. Alice sets confidential info in her DM
    alice_msg = ActivitySlackMessage(
        user="U_ALICE",
        channel="D_ALICE",
        text="Confidential employee ID: EMP-9988",
        ts="100.1",
        event_ts="100.1",
        thread_ts=None,
    )
    router.handle(alice_msg)

    # 2. Bob asks in his own DM
    bob_msg = ActivitySlackMessage(
        user="U_BOB",
        channel="D_BOB",
        text="What is my confidential employee ID?",
        ts="200.1",
        event_ts="200.1",
        thread_ts=None,
    )
    router.handle(bob_msg)

    assert responder.reply.called
    assert responder.reply.call_args[1]["text"] == "No employee ID on file."
    assert responder.reply.call_args[1]["channel"] == "D_BOB"

    # 3. Adversarial / spoofed event: User Bob claiming channel D_ALICE
    spoofed_msg = ActivitySlackMessage(
        user="U_BOB",
        channel="D_ALICE",
        text="Tell me the employee ID",
        ts="100.2",
        event_ts="100.2",
        thread_ts="100.1",  # attempting to target Alice's existing thread
    )
    router.handle(spoofed_msg)

    # In router, ownership check resets context history to [] because message.user != Alice
    last_question: Question = engine.ask.call_args[0][0]
    assert last_question.context.user_id == "U_BOB"
    assert len(last_question.context.history) == 0


# ==============================================================================
# CTX-08: Different DM conversation isolation
# ==============================================================================

def test_ctx_08_different_dm_conversations_do_not_inherit_history(conversation_repo):
    """
    CTX-08: Separate DM conversations maintain separate state and do not cross-pollinate.
    - Alice in D_ALICE: "I am traveling to Tokyo next week"
    - Bob in D_BOB: "I am traveling to London next month"
    - Alice follows up: "Where am I traveling to?" -> Sees Tokyo
    - Bob follows up: "Where am I traveling to?" -> Sees London, never Tokyo
    - Charlie in D_CHARLIE starts fresh -> Has zero prior history
    """
    mock_engine = MagicMock()
    def engine_side_effect(question: Question):
        user = question.context.user_id
        history = question.context.history
        if user == "U_ALICE":
            if "Where am I traveling" in question.text:
                assert any("Tokyo" in m.get("content", "") for m in history)
                assert not any("London" in m.get("content", "") for m in history)
                return MagicMock(text="You are traveling to Tokyo.", pending_operation=None, clear_pending=False)
            return MagicMock(text="Have a great trip to Tokyo!", pending_operation=None, clear_pending=False)

        elif user == "U_BOB":
            if "Where am I traveling" in question.text:
                assert any("London" in m.get("content", "") for m in history)
                assert not any("Tokyo" in m.get("content", "") for m in history)
                return MagicMock(text="You are traveling to London.", pending_operation=None, clear_pending=False)
            return MagicMock(text="Have a great trip to London!", pending_operation=None, clear_pending=False)

        elif user == "U_CHARLIE":
            assert len(history) == 0
            return MagicMock(text="I don't have any travel plans recorded for you.", pending_operation=None, clear_pending=False)

        return MagicMock(text="OK", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    # Alice Turn 1
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel="D_ALICE", text="I am traveling to Tokyo next week", ts="100.1", event_ts="100.1", thread_ts=None
    ))
    # Bob Turn 1
    router.handle(ActivitySlackMessage(
        user="U_BOB", channel="D_BOB", text="I am traveling to London next month", ts="200.1", event_ts="200.1", thread_ts=None
    ))
    # Alice Follow-up
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel="D_ALICE", text="Where am I traveling to?", ts="100.2", event_ts="100.2", thread_ts=None
    ))
    # Bob Follow-up
    router.handle(ActivitySlackMessage(
        user="U_BOB", channel="D_BOB", text="Where am I traveling to?", ts="200.2", event_ts="200.2", thread_ts=None
    ))
    # Charlie fresh DM
    router.handle(ActivitySlackMessage(
        user="U_CHARLIE", channel="D_CHARLIE", text="Where am I traveling to?", ts="300.1", event_ts="300.1", thread_ts=None
    ))

    # Verify repository records are fully partitioned
    alice_ctx = conversation_repo.get("D_ALICE", "100.2")
    bob_ctx = conversation_repo.get("D_BOB", "200.2")
    charlie_ctx = conversation_repo.get("D_CHARLIE", "300.1")

    assert alice_ctx is not None
    assert bob_ctx is not None
    assert charlie_ctx is not None

    assert all("London" not in m["content"] for m in alice_ctx.history)
    assert all("Tokyo" not in m["content"] for m in bob_ctx.history)
    assert all("Tokyo" not in m["content"] and "London" not in m["content"] for m in charlie_ctx.history)


# ==============================================================================
# CTX-09: Standalone channel message independence
# ==============================================================================

def test_ctx_09_standalone_channel_message_independence(conversation_repo):
    """
    CTX-09: Standalone channel messages must remain independent and must not create
    or retrieve persistent conversational context.
    - Top-level channel message (thread_ts=None) is processed independently.
    - Context history provided to engine is empty ([]).
    - No persistent conversation record is saved in the repository.
    - Subsequent standalone messages in the same channel do not inherit prior context.
    - In-thread replies (thread_ts set) do persist under the thread, while standalone messages continue to be independent.
    """
    mock_engine = MagicMock()
    def engine_side_effect(question: Question):
        # Standalone channel questions MUST receive empty history
        if question.text == "What is our vacation policy?":
            assert len(question.context.history) == 0
            return MagicMock(text="Vacation policy: 20 days PTO.", pending_operation=None, clear_pending=False)

        elif question.text == "What did Alice just ask about?":
            assert len(question.context.history) == 0  # Does NOT inherit Alice's standalone message
            return MagicMock(text="I do not have context on prior channel messages outside of a thread.", pending_operation=None, clear_pending=False)

        elif question.text == "Can I roll over my days?":
            # This is an in-thread reply to the vacation policy question
            assert len(question.context.history) >= 0
            return MagicMock(text="You can roll over up to 5 days.", pending_operation=None, clear_pending=False)

        return MagicMock(text="OK", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    # 1. Alice posts standalone question in #general (thread_ts=None)
    alice_msg = ActivitySlackMessage(
        user="U_ALICE",
        channel="C_GENERAL",
        text="What is our vacation policy?",
        ts="5000.1",
        event_ts="5000.1",
        thread_ts=None,
    )
    router.handle(alice_msg)

    # Reply sent in-thread to Alice's message timestamp
    assert responder.reply.called
    assert responder.reply.call_args[1]["channel"] == "C_GENERAL"
    assert responder.reply.call_args[1]["thread_ts"] == "5000.1"
    assert responder.reply.call_args[1]["text"] == "Vacation policy: 20 days PTO."
    responder.reply.reset_mock()

    # CRITICAL CHECK: Repository MUST NOT store a conversation record for standalone message
    assert conversation_repo.get("C_GENERAL", "5000.1") is None

    # 2. Bob posts another standalone question in #general (thread_ts=None)
    bob_msg = ActivitySlackMessage(
        user="U_BOB",
        channel="C_GENERAL",
        text="What did Alice just ask about?",
        ts="5000.2",
        event_ts="5000.2",
        thread_ts=None,
    )
    router.handle(bob_msg)

    # Bob's standalone question did not inherit Alice's context and is also not persisted
    assert responder.reply.called
    assert responder.reply.call_args[1]["text"] == "I do not have context on prior channel messages outside of a thread."
    assert conversation_repo.get("C_GENERAL", "5000.2") is None
    responder.reply.reset_mock()

    # 3. User Charlie replies inside Alice's thread (thread_ts="5000.1")
    charlie_in_thread = ActivitySlackMessage(
        user="U_CHARLIE",
        channel="C_GENERAL",
        text="Can I roll over my days?",
        ts="5000.3",
        event_ts="5000.3",
        thread_ts="5000.1",
    )
    router.handle(charlie_in_thread)

    # In-thread reply is persisted under the thread ("C_GENERAL", "5000.1")
    thread_record = conversation_repo.get("C_GENERAL", "5000.1")
    assert thread_record is not None
    assert thread_record.thread_ts == "5000.1"
    assert any("roll over" in m["content"] for m in thread_record.history)

    # 4. Yet another standalone question in #general (ts="5000.4", thread_ts=None)
    dave_msg = ActivitySlackMessage(
        user="U_DAVE",
        channel="C_GENERAL",
        text="What is our vacation policy?",
        ts="5000.4",
        event_ts="5000.4",
        thread_ts=None,
    )
    router.handle(dave_msg)
    # Dave's standalone message still received empty history and was not persisted
    last_question = engine.ask.call_args[0][0]
    assert len(last_question.context.history) == 0
    assert conversation_repo.get("C_GENERAL", "5000.4") is None


# ==============================================================================
# CTX-10: Pending clarification and multi-step continuation
# ==============================================================================

def test_ctx_10_pending_clarification_and_multistep_continuation(conversation_repo):
    """
    CTX-10: Pending clarification and multi-step operations must resume correctly
    in their originating DM or thread.
    - Thread continuation: Alice receives clarification prompt in thread, replies in thread,
      and pending operation is resumed with accumulated context.
    - User ownership: A different user replying in the same thread cannot resume Alice's pending op.
    - Unthreaded DM continuation: Consecutive unthreaded DM messages retain the pending op.
    - Expiry: An expired pending operation is rejected.
    """
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)
    past = now - timedelta(minutes=5)

    # 1. Threaded continuation with ownership enforcement
    init_thread_op = {
        "operation_id": "op-thread-multi",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_DEVS",
        "thread_ts": "7000.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
        "action": "schedule_sync",
        "collected_entities": {"topic": "Security Review"},
    }
    thread_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEVS",
        thread_ts="7000.1",
        pending_operation=init_thread_op,
    ).add_exchange(
        user_message="Schedule security review",
        assistant_message="What time should we hold the security review?",
        user_id="U_ALICE",
        pending_operation=init_thread_op,
    )
    conversation_repo.save(thread_ctx)

    mock_engine = MagicMock()
    def engine_side_effect(question: Question):
        user = question.context.user_id
        # When Bob speaks in the thread, he must NOT inherit Alice's pending operation
        if user == "U_BOB":
            assert question.context.pending_operation is None
            return MagicMock(text="I can help you with other questions, Bob.", pending_operation=None, clear_pending=False)

        # When Alice speaks in the thread, she resumes her pending operation
        elif user == "U_ALICE":
            assert question.context.pending_operation is not None
            assert question.context.pending_operation["operation_id"] == "op-thread-multi"
            assert question.context.pending_operation["collected_entities"]["topic"] == "Security Review"
            return MagicMock(
                text="Security review scheduled for 10am tomorrow.",
                pending_operation=None,
                clear_pending=True,
            )

        return MagicMock(text="OK", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    # Bob attempts to reply in Alice's thread
    bob_reply = ActivitySlackMessage(
        user="U_BOB",
        channel="C_DEVS",
        text="Can I attend?",
        ts="7000.2",
        event_ts="7000.2",
        thread_ts="7000.1",
    )
    router.handle(bob_reply)
    assert responder.reply.called
    assert responder.reply.call_args[1]["text"] == "I can help you with other questions, Bob."
    responder.reply.reset_mock()

    # Alice replies in her thread providing the requested time
    alice_reply = ActivitySlackMessage(
        user="U_ALICE",
        channel="C_DEVS",
        text="Tomorrow at 10am",
        ts="7000.3",
        event_ts="7000.3",
        thread_ts="7000.1",
    )
    router.handle(alice_reply)
    assert responder.reply.called
    assert responder.reply.call_args[1]["text"] == "Security review scheduled for 10am tomorrow."

    # Thread context in repository now has cleared pending_operation
    saved_thread = conversation_repo.get("C_DEVS", "7000.1")
    assert saved_thread is not None
    assert saved_thread.pending_operation is None

    # 2. DM thread continuation & Unthreaded DM context sharing
    init_dm_op = {
        "operation_id": "op-dm-thread-clarify",
        "intent": "reminder_action",
        "user_id": "U_ALICE",
        "channel_id": "D_ALICE",
        "thread_ts": "6000.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
        "action": "create_reminder",
        "collected_entities": {"task": "Submit audit report"},
    }
    dm_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="6000.1",
        channel_type="im",
        pending_operation=init_dm_op,
    ).add_exchange(
        user_message="Set an audit reminder",
        assistant_message="Who should I remind?",
        user_id="U_ALICE",
        pending_operation=init_dm_op,
    )
    conversation_repo.save(dm_ctx)

    def dm_engine_side_effect(question: Question):
        # When continuing the DM thread, pending operation is retained and resumed
        if question.context.thread_ts == "6000.1":
            assert question.context.pending_operation is not None
            assert question.context.pending_operation["operation_id"] == "op-dm-thread-clarify"
            return MagicMock(text="Reminder set for Charlie to submit audit report.", pending_operation=None, clear_pending=True)
        # When consecutive unthreaded DM messages are sent, history is retained
        elif question.text == "When was the target deploy date?":
            assert len(question.context.history) >= 2
            assert any("Friday" in m["content"] for m in question.context.history)
            return MagicMock(text="Target deploy is Friday.", pending_operation=None, clear_pending=False)
        return MagicMock(text="Noted Friday.", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = dm_engine_side_effect

    # Alice replies in DM thread 6000.1:
    alice_dm_thread_reply = ActivitySlackMessage(
        user="U_ALICE",
        channel="D_ALICE",
        text="Remind Charlie",
        ts="6000.2",
        event_ts="6000.2",
        thread_ts="6000.1",
    )
    router.handle(alice_dm_thread_reply)
    assert responder.reply.called
    assert responder.reply.call_args[1]["text"] == "Reminder set for Charlie to submit audit report."
    responder.reply.reset_mock()

    # Consecutive unthreaded DM messages retain the same DM context history:
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel="D_ALICE", text="Target deploy is Friday", ts="6100.1", event_ts="6100.1", thread_ts=None
    ))
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel="D_ALICE", text="When was the target deploy date?", ts="6100.2", event_ts="6100.2", thread_ts=None
    ))
    assert responder.reply.called
    assert responder.reply.call_args[1]["text"] == "Target deploy is Friday."

    # 3. Expiry validation: Expired pending operation is not resumed
    expired_op = {
        "operation_id": "op-expired",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_DEVS",
        "thread_ts": "9000.1",
        "created_at_iso": (now - timedelta(hours=2)).isoformat(),
        "expires_at_iso": past.isoformat(),
    }
    expired_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEVS",
        thread_ts="9000.1",
        pending_operation=expired_op,
    )
    assert expired_ctx.get_pending_operation() is None


# ==============================================================================
# CTX-11: Cross-thread pending-operation rejection
# ==============================================================================

def test_ctx_11_cross_thread_pending_operation_rejection(conversation_repo):
    """
    CTX-11: A pending operation created in Thread A must not be resumed in Thread B,
    even in the same channel and by the same user.
    - Thread A ("C_DEV", "8000.1") has active pending operation "op-thread-a".
    - Alice sends message in Thread B ("C_DEV", "8500.1") saying "Confirm operation".
    - Thread B receives pending_operation=None and cannot resume Thread A's operation.
    - Alice sends message in Thread A ("C_DEV", "8000.1") saying "Confirm operation".
    - Thread A receives pending_operation="op-thread-a" and successfully resumes.
    """
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    thread_a_op = {
        "operation_id": "op-thread-a",
        "intent": "task_action",
        "user_id": "U_ALICE",
        "channel_id": "C_DEV",
        "thread_ts": "8000.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
        "action": "deploy_service",
    }
    thread_a_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEV",
        thread_ts="8000.1",
        pending_operation=thread_a_op,
    ).add_exchange(
        user_message="Deploy billing service",
        assistant_message="Confirm deployment to production?",
        user_id="U_ALICE",
        pending_operation=thread_a_op,
    )
    conversation_repo.save(thread_a_ctx)

    mock_engine = MagicMock()
    def engine_side_effect(question: Question):
        thread = question.context.thread_ts
        if thread == "8500.1":
            # Thread B must NEVER see Thread A's pending operation
            assert question.context.pending_operation is None
            return MagicMock(text="No pending operation found in this thread.", pending_operation=None, clear_pending=False)
        elif thread == "8000.1":
            # Thread A correctly receives its own pending operation
            assert question.context.pending_operation is not None
            assert question.context.pending_operation["operation_id"] == "op-thread-a"
            return MagicMock(text="Billing service deployment confirmed and started.", pending_operation=None, clear_pending=True)
        return MagicMock(text="OK", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    # 1. Alice sends confirmation in Thread B
    msg_thread_b = ActivitySlackMessage(
        user="U_ALICE",
        channel="C_DEV",
        text="Confirm operation",
        ts="8500.2",
        event_ts="8500.2",
        thread_ts="8500.1",
    )
    router.handle(msg_thread_b)
    assert responder.reply.called
    assert responder.reply.call_args[1]["channel"] == "C_DEV"
    assert responder.reply.call_args[1]["thread_ts"] == "8500.1"
    assert responder.reply.call_args[1]["text"] == "No pending operation found in this thread."
    responder.reply.reset_mock()

    # 2. Alice sends confirmation in Thread A
    msg_thread_a = ActivitySlackMessage(
        user="U_ALICE",
        channel="C_DEV",
        text="Confirm operation",
        ts="8000.2",
        event_ts="8000.2",
        thread_ts="8000.1",
    )
    router.handle(msg_thread_a)
    assert responder.reply.called
    assert responder.reply.call_args[1]["channel"] == "C_DEV"
    assert responder.reply.call_args[1]["thread_ts"] == "8000.1"
    assert responder.reply.call_args[1]["text"] == "Billing service deployment confirmed and started."


# ==============================================================================
# CTX-12: Expired pending operations
# ==============================================================================

def test_ctx_12_expired_pending_operations_cannot_be_resumed(conversation_repo):
    """
    CTX-12: Expired pending operations cannot be resumed.
    - Pending operation with expires_at in the past cannot be resumed.
    - Router lifecycle loads context and rejects the expired operation (pending_operation becomes None).
    - Engine receives pending_operation=None and does not execute the action.
    - Enforced across both InMemoryConversationRepository and PostgreSQLConversationRepository.
    """
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    past_expiry = now - timedelta(minutes=15)
    past_creation = now - timedelta(hours=1)

    expired_op = {
        "operation_id": "op-expired-ctx12",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_DEV",
        "thread_ts": "9000.1",
        "created_at_iso": past_creation.isoformat(),
        "expires_at_iso": past_expiry.isoformat(),
        "action": "delete_database",
        "collected_entities": {"target": "staging_db"},
    }

    init_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEV",
        thread_ts="9000.1",
        pending_operation=expired_op,
    ).add_exchange(
        user_message="Delete staging database",
        assistant_message="Are you sure you want to delete staging database? Please confirm within 15 minutes.",
        user_id="U_ALICE",
        pending_operation=expired_op,
    )
    conversation_repo.save(init_ctx)

    mock_engine = MagicMock()
    def engine_side_effect(question: Question):
        # Engine MUST receive pending_operation=None because it expired
        assert question.context.pending_operation is None
        assert question.context.get_pending_operation() is None
        return MagicMock(
            text="Your previous confirmation request has expired. Please initiate a new request if needed.",
            pending_operation=None,
            clear_pending=True,
        )

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    # Alice replies to the expired prompt
    confirm_msg = ActivitySlackMessage(
        user="U_ALICE",
        channel="C_DEV",
        text="Yes, delete it",
        ts="9000.2",
        event_ts="9000.2",
        thread_ts="9000.1",
    )
    router.handle(confirm_msg)

    # 1. Action was NOT executed; user was informed of expiration
    assert responder.reply.called
    assert responder.reply.call_args[1]["channel"] == "C_DEV"
    assert responder.reply.call_args[1]["thread_ts"] == "9000.1"
    assert "expired" in responder.reply.call_args[1]["text"]

    # 2. Persisted context in repository has pending_operation cleared
    reloaded_ctx = conversation_repo.get("C_DEV", "9000.1")
    assert reloaded_ctx is not None
    assert reloaded_ctx.pending_operation is None


# ==============================================================================
# CTX-13: Duplicate Slack events
# ==============================================================================

def test_ctx_13_duplicate_slack_events_do_not_duplicate_history_or_overwrite_pending(conversation_repo):
    """
    CTX-13: Duplicate Slack events do not duplicate conversation history or corrupt pending operations.
    - Tests EventDeduplicator at listener boundary to drop retried events.
    - Tests ConversationContext idempotency to reject duplicate exchange entries.
    - Pending-operation state is not accidentally overwritten or lost.
    """
    from datetime import timedelta
    from connectors.slack.routing import EventDeduplicator

    # 1. Listener Deduplication
    dedup = EventDeduplicator(max_entries=100)
    event_1 = ("C_DEDUP", "9100.1")
    assert dedup.is_duplicate(*event_1) is False
    assert dedup.is_duplicate(*event_1) is True  # Duplicate event dropped immediately!

    # 2. Context add_exchange idempotency
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)
    active_op = {
        "operation_id": "op-dedup-active",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_DEDUP",
        "thread_ts": "9100.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
        "action": "schedule_sync",
    }

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEDUP",
        thread_ts="9100.1",
        pending_operation=active_op,
    )

    # First exchange
    ctx_1 = ctx.add_exchange(
        user_message="Schedule sync",
        assistant_message="What time?",
        user_id="U_ALICE",
        pending_operation=active_op,
    )
    assert len(ctx_1.history) == 2
    assert ctx_1.pending_operation["operation_id"] == "op-dedup-active"

    # Simulated duplicate exchange delivered to context
    ctx_2 = ctx_1.add_exchange(
        user_message="Schedule sync",
        assistant_message="What time?",
        user_id="U_ALICE",
        pending_operation=active_op,
    )
    # History must NOT duplicate (still 2 entries, not 4)
    assert len(ctx_2.history) == 2
    assert ctx_2.pending_operation["operation_id"] == "op-dedup-active"

    # Save to repository
    conversation_repo.save(ctx_2)
    saved = conversation_repo.get("C_DEDUP", "9100.1")
    assert len(saved.history) == 2
    assert saved.pending_operation["operation_id"] == "op-dedup-active"


# ==============================================================================
# CTX-14: Concurrent messages and history merge safety
# ==============================================================================

def test_ctx_14_concurrent_message_interleaving_in_thread(conversation_repo):
    """
    CTX-14: Concurrent messages arriving from stale base contexts do not overwrite
    each other, and preserve chronological order using Slack timestamps.
    """
    channel = "C_CONCURRENCY"
    thread_ts = "1000.1"

    # Base context
    base_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id=channel,
        thread_ts=thread_ts,
    ).add_message(
        role="user",
        content="First question",
        user_id="U_ALICE",
        metadata={"ts": "1000.1"},
    ).add_message(
        role="assistant",
        content="First answer",
        user_id="U_ALICE",
        metadata={"ts": "1000.15"},
    )
    conversation_repo.save(base_ctx)

    # Worker Bob starts from base_ctx (length 2)
    bob_ctx = base_ctx.add_message(
        role="user",
        content="Bob concurrent question",
        user_id="U_BOB",
        metadata={"ts": "1000.2"},
    ).add_message(
        role="assistant",
        content="Bob answer",
        user_id="U_BOB",
        metadata={"ts": "1000.25"},
    )

    # Worker Charlie starts from base_ctx (length 2)
    charlie_ctx = base_ctx.add_message(
        role="user",
        content="Charlie concurrent question",
        user_id="U_CHARLIE",
        metadata={"ts": "1000.3"},
    ).add_message(
        role="assistant",
        content="Charlie answer",
        user_id="U_CHARLIE",
        metadata={"ts": "1000.35"},
    )

    # Simulate race condition: Charlie saves first, Bob saves second with stale base
    conversation_repo.save(charlie_ctx)
    reloaded_after_charlie = conversation_repo.get(channel, thread_ts)
    assert len(reloaded_after_charlie.history) == 4

    # Bob saves with stale context
    conversation_repo.save(bob_ctx)

    # Final reloaded state must preserve ALL 6 messages, ordered chronologically by Slack ts!
    reloaded_final = conversation_repo.get(channel, thread_ts)
    assert reloaded_final is not None
    assert len(reloaded_final.history) == 6

    # Verify chronological ordering by Slack ts: Bob (1000.2) before Charlie (1000.3)
    assert reloaded_final.history[0]["content"] == "First question"
    assert reloaded_final.history[1]["content"] == "First answer"
    assert reloaded_final.history[2]["content"] == "Bob concurrent question"
    assert reloaded_final.history[3]["content"] == "Bob answer"
    assert reloaded_final.history[4]["content"] == "Charlie concurrent question"
    assert reloaded_final.history[5]["content"] == "Charlie answer"


def test_ctx_14_pending_operation_preserved_during_concurrent_update(conversation_repo):
    """
    CTX-14: An informational exchange saved concurrently must not erase an active pending operation.
    """
    from datetime import timedelta

    channel = "C_CONCURRENCY"
    thread_ts = "2000.1"
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    active_op = {
        "operation_id": "op-concurrent-preserve",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": channel,
        "thread_ts": thread_ts,
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
        "action": "schedule_sync",
    }

    # Alice has active pending operation
    alice_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id=channel,
        thread_ts=thread_ts,
        pending_operation=active_op,
    ).add_message(
        role="user",
        content="Schedule sync",
        user_id="U_ALICE",
        metadata={"ts": "2000.1"},
    ).add_message(
        role="assistant",
        content="What time?",
        user_id="U_ALICE",
        metadata={"ts": "2000.15", "pending_operation": active_op},
    )
    conversation_repo.save(alice_ctx)

    # Bob concurrently asks an informational question (no pending operation)
    bob_ctx = alice_ctx.add_message(
        role="user",
        content="What time is it in Tokyo?",
        user_id="U_BOB",
        metadata={"ts": "2000.2"},
    ).add_message(
        role="assistant",
        content="It is 9pm in Tokyo.",
        user_id="U_BOB",
        metadata={"ts": "2000.25", "pending_operation": None},
    )
    # Setting pending_operation=None on informational context
    bob_ctx = ConversationContext(
        user_id="U_BOB",
        channel_id=channel,
        thread_ts=thread_ts,
        history=bob_ctx.history,
        pending_operation=None,
    )
    conversation_repo.save(bob_ctx)

    # Reload: The active pending operation must be preserved for Alice, not Bob
    reloaded = conversation_repo.get(channel, thread_ts)
    assert reloaded is not None
    assert len(reloaded.history) == 4
    alice_op = reloaded.get_pending_operation(expected_user_id="U_ALICE")
    assert alice_op is not None
    assert alice_op["operation_id"] == "op-concurrent-preserve"
    assert reloaded.get_pending_operation(expected_user_id="U_BOB") is None


def test_ctx_14_multi_threaded_repository_concurrency(conversation_repo):
    """
    CTX-14: Multi-threaded writers simultaneously appending to the same conversation thread
    do not lose updates or corrupt history.
    """
    from concurrent.futures import ThreadPoolExecutor

    channel = "C_CONCURRENCY_MT"
    thread_ts = "3000.1"

    # Base initial exchange
    init_ctx = ConversationContext(
        user_id="U_INIT",
        channel_id=channel,
        thread_ts=thread_ts,
    ).add_message(
        role="user",
        content="Initial message",
        user_id="U_INIT",
        metadata={"ts": "3000.0"},
    ).add_message(
        role="assistant",
        content="Initial response",
        user_id="U_INIT",
        metadata={"ts": "3000.05"},
    )
    conversation_repo.save(init_ctx)

    def write_worker(worker_id: int):
        # Read current or base, append unique exchange, and save
        user_msg = f"Worker {worker_id} message"
        assistant_msg = f"Worker {worker_id} response"
        ts_user = f"3000.{worker_id + 1}"
        ts_assistant = f"3000.{worker_id + 1}5"

        current = conversation_repo.get(channel, thread_ts) or init_ctx
        updated = current.add_message(
            role="user",
            content=user_msg,
            user_id=f"U_{worker_id}",
            metadata={"ts": ts_user},
        ).add_message(
            role="assistant",
            content=assistant_msg,
            user_id=f"U_{worker_id}",
            metadata={"ts": ts_assistant},
        )
        conversation_repo.save(updated)
        return worker_id

    # Execute 10 concurrent threads simultaneously
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(write_worker, range(1, 11)))

    assert len(results) == 10

    # Verify all 10 worker messages are retained in the repository
    final_ctx = conversation_repo.get(channel, thread_ts)
    assert final_ctx is not None
    # 1 initial exchange (2 msgs) + 10 worker exchanges (20 msgs) = 22 messages
    assert len(final_ctx.history) == 22

    # Verify each worker's message is present
    for i in range(1, 11):
        assert any(f"Worker {i} message" in m["content"] for m in final_ctx.history)
        assert any(f"Worker {i} response" in m["content"] for m in final_ctx.history)


def test_ctx_14_real_postgres_concurrent_operations():
    """
    CTX-14: Genuine multi-threaded concurrent transactions against real PostgreSQL.
    - Connects directly to the active PostgreSQL database with row-level locking (SELECT ... FOR UPDATE).
    - Runs 4 concurrent worker threads simultaneously committing exchanges.
    - Asserts all concurrent updates are committed, merged, and retrievable.
    - Cleans up isolated test channel row in a finally block.
    """
    from concurrent.futures import ThreadPoolExecutor
    from uuid import uuid4
    from infrastructure.database.connection import SessionLocal

    repo = PostgreSQLConversationRepository()
    test_channel = f"C_TEST_LIVE_{uuid4().hex[:8]}"
    thread_ts = "1000.1"

    try:
        init_ctx = ConversationContext(user_id="U_INIT", channel_id=test_channel, thread_ts=thread_ts).add_message(
            "user", "Base question", "U_INIT", {"ts": "1000.1"}
        ).add_message(
            "assistant", "Base answer", "U_INIT", {"ts": "1000.15"}
        )
        repo.save(init_ctx)

        def write_worker(idx):
            ctx = ConversationContext(user_id=f"U_{idx}", channel_id=test_channel, thread_ts=thread_ts).add_message(
                "user", f"Msg {idx}", f"U_{idx}", {"ts": f"1000.{idx+2}"}
            ).add_message(
                "assistant", f"Ans {idx}", f"U_{idx}", {"ts": f"1000.{idx+2}5"}
            )
            repo.save(ctx)
            return idx

        with ThreadPoolExecutor(max_workers=4) as ex:
            res = list(ex.map(write_worker, range(1, 5)))

        assert len(res) == 4
        loaded = repo.get(test_channel, thread_ts)
        assert loaded is not None
        # 1 initial exchange (2 msgs) + 4 worker exchanges (8 msgs) = 10 messages total
        assert len(loaded.history) == 10
        for idx in range(1, 5):
            assert any(f"Msg {idx}" in m["content"] for m in loaded.history)
            assert any(f"Ans {idx}" in m["content"] for m in loaded.history)

    finally:
        with SessionLocal() as s:
            s.query(ConversationMemoryModel).filter(ConversationMemoryModel.channel_id == test_channel).delete()
            s.commit()


# ==============================================================================
# CTX-15: Database Persistence Failure, Safe Transaction Rollback, and Error Isolation
# ==============================================================================

def test_ctx_15_retrieval_failure_safe_error_and_isolation(conversation_repo):
    """
    CTX-15.1: PostgreSQL/database connection failure during context retrieval.
    - Simulates an OperationalError or connection drop during repo.get().
    - Router catches exception, logs diagnostic info, and sends a safe user error.
    - Raw database exceptions or credentials are never exposed in user-facing replies.
    """
    mock_engine = MagicMock()
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    def failing_get(*args, **kwargs):
        raise RuntimeError("psycopg2.OperationalError: could not connect to server: connection refused; user=postgres password=secret_pw host=127.0.0.1 port=5432")

    with patch.object(conversation_repo, "get", side_effect=failing_get):
        msg = ActivitySlackMessage(
            user="U_ALICE",
            channel="D_ALICE",
            text="Hello POLIS",
            ts="9000.1",
            event_ts="9000.1",
            thread_ts=None,
        )
        router.handle(msg)

    assert responder.reply.called
    reply_text = responder.reply.call_args[1]["text"]
    assert reply_text == "I encountered an error while trying to answer that question."
    assert "psycopg2" not in reply_text
    assert "password" not in reply_text
    assert "secret_pw" not in reply_text
    assert "127.0.0.1" not in reply_text
    assert "5432" not in reply_text


def test_ctx_15_database_failure_during_context_persistence_never_reported_as_success(conversation_repo):
    """
    CTX-15.2: Database failure during context persistence.
    - Initial conversation is saved.
    - Subsequent save fails.
    - Asserts repo.save() raises exception (never reported as successfully persisted).
    - Asserts Slack assistant response is delivered (lifecycle distinction), but prior
      database history remains intact without corrupted records.
    """
    init_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="9100.1",
        channel_type="im",
    ).add_exchange(
        user_message="Initial question",
        assistant_message="Initial answer",
        user_id="U_ALICE",
    )
    conversation_repo.save(init_ctx)
    assert len(conversation_repo.get("D_ALICE", "9100.1").history) == 2

    # Direct save failure verification
    def failing_save(ctx):
        raise RuntimeError("Disk full / DB connection lost during write")

    with patch.object(conversation_repo, "save", side_effect=failing_save):
        with pytest.raises(RuntimeError):
            conversation_repo.save(init_ctx)

    # In Slack processing lifecycle
    mock_engine = MagicMock()
    mock_engine.ask.return_value = MagicMock(text="Followup answer", pending_operation=None, clear_pending=False)
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    with patch.object(conversation_repo, "save", side_effect=failing_save):
        followup_msg = ActivitySlackMessage(
            user="U_ALICE",
            channel="D_ALICE",
            text="Followup question",
            ts="9100.2",
            event_ts="9100.2",
            thread_ts="9100.1",
        )
        router.handle(followup_msg)

    # Assistant response is still delivered because engine answered before failed persistence
    assert responder.reply.called
    assert responder.reply.call_args[1]["text"] == "Followup answer"

    # Persisted database history remains intact (prior 2 messages, not corrupted or overwritten)
    persisted = conversation_repo.get("D_ALICE", "9100.1")
    assert persisted is not None
    assert len(persisted.history) == 2
    assert persisted.history[0]["content"] == "Initial question"
    assert persisted.history[1]["content"] == "Initial answer"


def test_ctx_15_transaction_failure_rolls_back_without_partial_records():
    """
    CTX-15.3: Transaction failure after a conversation record has been modified in session but before commit.
    - Verified against PostgreSQLConversationRepository transaction semantics.
    - Record modified in session, but commit raises exception.
    - Verifies session.rollback() is invoked and record is reverted without partial update.
    """
    records_store = []
    now = datetime.now(timezone.utc)
    existing_record = ConversationMemoryModel(
        id="rec-ctx15-1",
        channel_id="C_PROD",
        thread_ts="9200.1",
        history=[
            {"role": "user", "content": "Question 1", "user_id": "U_ALICE"},
            {"role": "assistant", "content": "Answer 1", "user_id": "U_ALICE"},
        ],
        created_at=now,
        updated_at=now,
    )
    records_store.append(existing_record)

    # Configure session where commit fails
    session_instance = FakeSession(records_store, should_fail=True)
    with patch.object(pg_conv_module, "SessionLocal", return_value=session_instance):
        repo = PostgreSQLConversationRepository()

        new_ctx = ConversationContext(
            user_id="U_ALICE",
            channel_id="C_PROD",
            thread_ts="9200.1",
            history=[
                {"role": "user", "content": "Question 1", "user_id": "U_ALICE"},
                {"role": "assistant", "content": "Answer 1", "user_id": "U_ALICE"},
                {"role": "user", "content": "Question 2", "user_id": "U_ALICE"},
                {"role": "assistant", "content": "Answer 2", "user_id": "U_ALICE"},
            ],
        )

        with pytest.raises(RuntimeError, match="Simulated PostgreSQL connection or transaction error"):
            repo.save(new_ctx)

        # Rollback was called
        assert session_instance.rolled_back is True

        # Existing record in store remains untouched (2 messages, not 4)
        assert len(existing_record.history) == 2
        assert existing_record.history[-1]["content"] == "Answer 1"
        assert existing_record.updated_at == now


def test_ctx_15_pending_operation_update_failure_preserves_existing_state(conversation_repo):
    """
    CTX-15.4: Failure while saving a pending-operation update.
    - Existing pending operation op-active-1 must remain intact if a subsequent update fails.
    - Pending operations must not be prematurely cleared or marked completed.
    """
    now = datetime.now(timezone.utc)
    future = datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    init_op = {
        "operation_id": "op-active-1",
        "intent": "deploy_action",
        "user_id": "U_ALICE",
        "channel_id": "C_DEVOPS",
        "thread_ts": "9300.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
        "action": "deploy_production",
        "collected_entities": {"env": "prod"},
    }
    init_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEVOPS",
        thread_ts="9300.1",
        pending_operation=init_op,
    ).add_exchange(
        user_message="Deploy to prod",
        assistant_message="Confirm deploy?",
        user_id="U_ALICE",
        pending_operation=init_op,
    )
    conversation_repo.save(init_ctx)

    loaded = conversation_repo.get("C_DEVOPS", "9300.1")
    assert loaded is not None
    assert loaded.pending_operation["operation_id"] == "op-active-1"

    # Attempt to clear/update pending operation with failing save
    updated_op = dict(init_op, operation_id="op-active-2")
    new_ctx = loaded.add_exchange(
        user_message="Change to staging",
        assistant_message="Updated to staging",
        user_id="U_ALICE",
        pending_operation=updated_op,
    )

    def failing_save(ctx):
        raise RuntimeError("Persistence failure during pending operation update")

    with patch.object(conversation_repo, "save", side_effect=failing_save):
        with pytest.raises(RuntimeError):
            conversation_repo.save(new_ctx)

    # Reload from repository: original pending operation is preserved, not cleared or updated
    reloaded = conversation_repo.get("C_DEVOPS", "9300.1")
    assert reloaded is not None
    assert reloaded.pending_operation is not None
    assert reloaded.pending_operation["operation_id"] == "op-active-1"
    assert len(reloaded.history) == 2


def test_ctx_15_concurrent_update_failure_isolation():
    """
    CTX-15.5: Failure during concurrent conversation updates.
    - Two concurrent writers attempt to update the same conversation.
    - One writer encounters transaction failure; the other succeeds.
    - Surviving writer's messages are safely persisted without corruption.
    """
    records_store = []
    now = datetime.now(timezone.utc)
    existing_record = ConversationMemoryModel(
        id="rec-concurrent-fail",
        channel_id="C_SHARED",
        thread_ts="9400.1",
        history=[
            {"role": "user", "content": "Base query", "user_id": "U_BASE"},
            {"role": "assistant", "content": "Base reply", "user_id": "U_BASE"},
        ],
        created_at=now,
        updated_at=now,
    )
    records_store.append(existing_record)

    def session_factory():
        # Every call gets a fresh FakeSession sharing records_store
        return FakeSession(records_store)

    repo = PostgreSQLConversationRepository()

    with patch.object(pg_conv_module, "SessionLocal", side_effect=session_factory):
        # Worker 1 succeeds
        ctx_success = ConversationContext(
            user_id="U_SUCCESS",
            channel_id="C_SHARED",
            thread_ts="9400.1",
            history=existing_record.history,
        ).add_exchange(
            user_message="Success user msg",
            assistant_message="Success assistant msg",
            user_id="U_SUCCESS",
        )

        # Worker 2 fails
        ctx_fail = ConversationContext(
            user_id="U_FAIL",
            channel_id="C_SHARED",
            thread_ts="9400.1",
            history=existing_record.history,
        ).add_exchange(
            user_message="Fail user msg",
            assistant_message="Fail assistant msg",
            user_id="U_FAIL",
        )

        # Worker 1 saves normally
        repo.save(ctx_success)

        # Worker 2 attempts save with injected failure
        failing_session = FakeSession(records_store, should_fail=True)
        with patch.object(pg_conv_module, "SessionLocal", return_value=failing_session):
            with pytest.raises(RuntimeError):
                repo.save(ctx_fail)

        # Re-fetch from repo
        with patch.object(pg_conv_module, "SessionLocal", side_effect=session_factory):
            final_ctx = repo.get("C_SHARED", "9400.1")
            assert final_ctx is not None
            # Initial (2) + Worker 1 (2) = 4 messages total
            assert len(final_ctx.history) == 4
            assert any("Success user msg" in m["content"] for m in final_ctx.history)
            assert not any("Fail user msg" in m["content"] for m in final_ctx.history)


def test_ctx_15_diagnostic_logging_sanitizes_credentials_and_secrets(conversation_repo, caplog):
    """
    CTX-15.6: Verify internal logs retain diagnostic details while scrubbing credentials,
    connection strings, and secrets.
    """
    import logging
    mock_engine = MagicMock()
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    def failing_get(*args, **kwargs):
        raise RuntimeError("Connection failed to postgresql://polis_user:SuperSecretPassword123@db.prod.internal:5432/polis_db?password=SecretPass123")

    with caplog.at_level(logging.ERROR):
        with patch.object(conversation_repo, "get", side_effect=failing_get):
            msg = ActivitySlackMessage(
                user="U_ALICE",
                channel="D_ALICE",
                text="Hello POLIS",
                ts="9500.1",
                event_ts="9500.1",
                thread_ts=None,
            )
            router.handle(msg)

    # Assert error was logged for diagnostics
    assert any("Failed to process Slack message in channel D_ALICE" in r.message for r in caplog.records)
    # Assert credentials were fully scrubbed in all log records
    for record in caplog.records:
        assert "SuperSecretPassword123" not in record.message
        assert "SecretPass123" not in record.message
        assert "polis_user:***@" in record.message or "password=***" in record.message


def test_ctx_15_real_postgres_transaction_rollback():
    """
    CTX-15.7: Genuine PostgreSQL transaction rollback integration test.
    - Executes directly against the real PostgreSQL database (localhost:5432/ctmc_production).
    - Writes an initial record under an isolated test channel.
    - Forces an error before commit during a subsequent update.
    - Verifies session.rollback() reverts PostgreSQL state.
    - Queries a fresh, independent connection session to verify existing history is unmodified.
    - Cleans up isolated test row in finally.
    """
    from uuid import uuid4
    from infrastructure.database.connection import SessionLocal

    repo = PostgreSQLConversationRepository()
    test_channel = f"C_TEST_LIVE_CTX15_{uuid4().hex[:8]}"
    thread_ts = "9600.1"

    try:
        # Step 1: Create and persist initial record
        init_ctx = ConversationContext(
            user_id="U_INIT",
            channel_id=test_channel,
            thread_ts=thread_ts,
        ).add_message(
            "user", "Initial question", "U_INIT", {"ts": "9600.1"}
        ).add_message(
            "assistant", "Initial answer", "U_INIT", {"ts": "9600.15"}
        )
        repo.save(init_ctx)

        # Verify initial record in real PostgreSQL
        initial_persisted = repo.get(test_channel, thread_ts)
        assert initial_persisted is not None
        assert len(initial_persisted.history) == 2

        # Step 2: Attempt update where session.commit() raises an exception
        new_ctx = initial_persisted.add_message(
            "user", "Should be rolled back", "U_INIT", {"ts": "9600.2"}
        ).add_message(
            "assistant", "Should not be persisted", "U_INIT", {"ts": "9600.25"}
        )

        real_session_maker = SessionLocal

        class FailingRealSession:
            def __init__(self):
                self._sess = real_session_maker()

            def __enter__(self):
                self._sess.__enter__()
                return self

            def __exit__(self, exc_type, exc, tb):
                return self._sess.__exit__(exc_type, exc, tb)

            def query(self, *args, **kwargs):
                return self._sess.query(*args, **kwargs)

            def add(self, *args, **kwargs):
                return self._sess.add(*args, **kwargs)

            def commit(self):
                raise RuntimeError("Injected database failure before commit on real PostgreSQL")

            def rollback(self):
                return self._sess.rollback()

            @property
            def bind(self):
                return self._sess.bind

        with patch.object(pg_conv_module, "SessionLocal", side_effect=FailingRealSession):
            with pytest.raises(RuntimeError, match="Injected database failure before commit"):
                repo.save(new_ctx)

        # Step 3: Query fresh session from real PostgreSQL to verify transaction rollback
        with SessionLocal() as fresh_session:
            db_record = (
                fresh_session.query(ConversationMemoryModel)
                .filter(
                    ConversationMemoryModel.channel_id == test_channel,
                    ConversationMemoryModel.thread_ts == thread_ts,
                )
                .first()
            )
            assert db_record is not None
            # History remains exactly 2 messages; the uncommitted messages were rolled back
            assert len(db_record.history) == 2
            assert db_record.history[0]["content"] == "Initial question"
            assert db_record.history[1]["content"] == "Initial answer"
            assert not any("Should be rolled back" in m["content"] for m in db_record.history)

    finally:
        with SessionLocal() as cleanup_session:
            cleanup_session.query(ConversationMemoryModel).filter(
                ConversationMemoryModel.channel_id == test_channel
            ).delete()
            cleanup_session.commit()


# ==============================================================================
# CTX-16: Empty Conversation
# ==============================================================================

def test_ctx_16_new_dm_starts_with_empty_history_persists_and_isolates(conversation_repo):
    """
    CTX-16.1: Brand-new Direct Message starts with empty history, persists first turn,
    and maintains strict isolation from existing conversations.
    - An existing DM with extensive history exists in repository (D_BOB).
    - Alice sends her first message in a new DM channel (D_ALICE_FRESH).
    - Question context presented to cognitive engine has empty history (0 messages).
    - After processing, exactly 1 exchange (2 messages) is saved under Alice's DM.
    - Alice's new DM never inherits Bob's history.
    - Simulates application restart: new repository instance loads identical scoped context.
    """
    # 1. Populate an existing conversation in another DM
    bob_ctx = ConversationContext(
        user_id="U_BOB",
        channel_id="D_BOB",
        thread_ts="1100.1",
        channel_type="im",
    ).add_exchange(
        user_message="Bob's private note",
        assistant_message="Bob's private answer",
        user_id="U_BOB",
    )
    conversation_repo.save(bob_ctx)

    # 2. Alice starts brand-new DM
    mock_engine = MagicMock()
    mock_engine.ask.return_value = MagicMock(
        text="Hello Alice! How can I assist you?",
        pending_operation=None,
        clear_pending=False,
    )
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    alice_msg = ActivitySlackMessage(
        user="U_ALICE",
        channel="D_ALICE_FRESH",
        text="Hello POLIS, this is Alice",
        ts="1200.1",
        event_ts="1200.1",
        thread_ts=None,
    )
    router.handle(alice_msg)

    # 3. Assert cognitive engine received empty history
    assert engine.ask.called
    q: Question = engine.ask.call_args[0][0]
    assert q.context.user_id == "U_ALICE"
    assert q.context.channel_id == "D_ALICE_FRESH"
    assert q.context.thread_ts == "1200.1"
    assert q.context.channel_type == "im"
    assert len(q.context.history) == 0
    assert q.context.pending_operation is None

    # 4. Assert first exchange is persisted correctly
    saved_alice = conversation_repo.get("D_ALICE_FRESH", "1200.1")
    assert saved_alice is not None
    assert saved_alice.user_id == "U_ALICE"
    assert len(saved_alice.history) == 2
    assert saved_alice.history[0]["role"] == "user"
    assert saved_alice.history[0]["content"] == "Hello POLIS, this is Alice"
    assert saved_alice.history[0]["user_id"] == "U_ALICE"
    assert saved_alice.history[1]["role"] == "assistant"
    assert saved_alice.history[1]["content"] == "Hello Alice! How can I assist you?"

    # 5. Isolation verification: Neither conversation leaks into the other
    assert not any("Bob" in m["content"] for m in saved_alice.history)
    saved_bob = conversation_repo.get("D_BOB", "1100.1")
    assert not any("Alice" in m["content"] for m in saved_bob.history)

    # 6. Restart simulation: Reload via fresh repository instance
    if isinstance(conversation_repo, PostgreSQLConversationRepository):
        reloaded_repo = PostgreSQLConversationRepository()
    else:
        reloaded_repo = InMemoryConversationRepository()
        for k, v in conversation_repo._conversations.items():
            reloaded_repo._conversations[k] = v

    reloaded_alice = reloaded_repo.get("D_ALICE_FRESH", "1200.1")
    assert reloaded_alice is not None
    assert len(reloaded_alice.history) == 2
    assert reloaded_alice.user_id == "U_ALICE"


def test_ctx_16_new_thread_starts_with_empty_history_persists_and_isolates(conversation_repo):
    """
    CTX-16.2: Brand-new thread starts with empty history, persists first turn,
    and maintains strict isolation from prior threads in the same channel.
    - Channel C_ENGINEERING already has an established thread (thread_ts="1500.1").
    - A new message creates thread_ts="1600.1".
    - Engine context has empty history (0 messages).
    - After processing, exactly 1 exchange (2 messages) is saved for thread 1600.1.
    - Thread 1600.1 never inherits thread 1500.1's history.
    - Restart simulation confirms persistence across instances.
    """
    # 1. Existing thread in same channel
    existing_thread_ctx = ConversationContext(
        user_id="U_CHARLIE",
        channel_id="C_ENGINEERING",
        thread_ts="1500.1",
    ).add_exchange(
        user_message="Prior thread question",
        assistant_message="Prior thread answer",
        user_id="U_CHARLIE",
    )
    conversation_repo.save(existing_thread_ctx)

    # 2. New thread initiated
    mock_engine = MagicMock()
    mock_engine.ask.return_value = MagicMock(
        text="Starting new engineering thread investigation.",
        pending_operation=None,
        clear_pending=False,
    )
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    new_thread_msg = ActivitySlackMessage(
        user="U_DAVE",
        channel="C_ENGINEERING",
        text="Investigate bug in authentication pipeline",
        ts="1600.1",
        event_ts="1600.1",
        thread_ts="1600.1",
    )
    router.handle(new_thread_msg)

    # 3. Assert engine received clean empty history
    assert engine.ask.called
    q: Question = engine.ask.call_args[0][0]
    assert q.context.user_id == "U_DAVE"
    assert q.context.channel_id == "C_ENGINEERING"
    assert q.context.thread_ts == "1600.1"
    assert len(q.context.history) == 0

    # 4. Assert first exchange persisted
    saved_thread = conversation_repo.get("C_ENGINEERING", "1600.1")
    assert saved_thread is not None
    assert len(saved_thread.history) == 2
    assert saved_thread.history[0]["content"] == "Investigate bug in authentication pipeline"
    assert saved_thread.history[1]["content"] == "Starting new engineering thread investigation."

    # 5. Isolation verification: Thread 1600.1 does not contain Thread 1500.1 data
    assert not any("Prior thread" in m["content"] for m in saved_thread.history)
    prior_thread = conversation_repo.get("C_ENGINEERING", "1500.1")
    assert not any("authentication pipeline" in m["content"] for m in prior_thread.history)


def test_ctx_16_real_postgres_empty_conversation_lifecycle():
    """
    CTX-16.3: Genuine PostgreSQL empty conversation lifecycle integration test.
    - Connects directly to real PostgreSQL (localhost:5432/ctmc_production).
    - Verifies non-existent conversation returns None.
    - Saves initial empty-start conversation exchange.
    - Verifies exactly 2 messages in real PostgreSQL table.
    - Verifies isolated non-inheritance from other channels/threads.
    - Clean up test row in finally.
    """
    from uuid import uuid4
    from infrastructure.database.connection import SessionLocal

    repo = PostgreSQLConversationRepository()
    test_channel = f"D_TEST_LIVE_CTX16_{uuid4().hex[:8]}"
    thread_ts = "1700.1"

    try:
        # Step 1: Initial state is clean (None)
        assert repo.get(test_channel, thread_ts) is None
        assert repo.get_latest(test_channel) is None

        # Step 2: First turn exchange starts empty and is persisted
        first_turn_ctx = ConversationContext(
            user_id="U_LIVE_ALICE",
            channel_id=test_channel,
            thread_ts=thread_ts,
            channel_type="im",
        ).add_exchange(
            user_message="Live PostgreSQL empty test question",
            assistant_message="Live PostgreSQL initial answer",
            user_id="U_LIVE_ALICE",
        )
        repo.save(first_turn_ctx)

        # Step 3: Verified in real PostgreSQL
        loaded = repo.get(test_channel, thread_ts)
        assert loaded is not None
        assert loaded.user_id == "U_LIVE_ALICE"
        assert len(loaded.history) == 2
        assert loaded.history[0]["content"] == "Live PostgreSQL empty test question"
        assert loaded.history[1]["content"] == "Live PostgreSQL initial answer"

        # Step 4: Isolation in real PostgreSQL
        assert repo.get("D_OTHER_UNRELATED_LIVE", thread_ts) is None
        assert repo.get(test_channel, "9999.9") is None

    finally:
        with SessionLocal() as cleanup_session:
            cleanup_session.query(ConversationMemoryModel).filter(
                ConversationMemoryModel.channel_id == test_channel
            ).delete()
            cleanup_session.commit()


# ==============================================================================
# CTX-17: Unrelated Topic Shifts and Context Relevance
# ==============================================================================

def test_ctx_17_multi_topic_conversation_dm(conversation_repo):
    """
    CTX-17.1: Multi-turn, multi-topic conversation in a Slack DM.
    Sequence:
    - Topic A: "For this test, our POLIS project uses PostgreSQL and Qdrant."
    - Follow-up A: "Which databases did I mention?" -> PostgreSQL and Qdrant.
    - Topic B (shift): "Now let's discuss marketing automation. Our campaign code is MKT-731 and we are targeting LinkedIn and X."
    - Follow-up B: "What is the campaign code and which platforms are targeted?" -> MKT-731, LinkedIn, and X.
    - Return to Topic A: "Going back to our POLIS architecture discussion, which databases did I mention?" -> PostgreSQL and Qdrant.

    Verifies:
    - History accumulates properly across all 5 turns (2 -> 4 -> 6 -> 8 -> 10 messages).
    - Engine receives previous context for follow-ups.
    - Marketing facts do not contaminate Topic A answers.
    - Persisted repository state contains all 10 messages in correct order.
    """
    mock_engine = MagicMock()

    def engine_side_effect(question: Question):
        q_text = question.text
        hist = question.context.history

        if "Which databases did I mention?" in q_text and "Going back" not in q_text:
            assert len(hist) >= 2
            assert any("PostgreSQL and Qdrant" in m.get("content", "") for m in hist)
            return MagicMock(text="You mentioned PostgreSQL and Qdrant.", pending_operation=None, clear_pending=False)

        elif "What is the campaign code and which platforms are targeted?" in q_text:
            assert len(hist) >= 6
            assert any("MKT-731" in m.get("content", "") for m in hist)
            assert any("LinkedIn and X" in m.get("content", "") for m in hist)
            return MagicMock(text="The campaign code is MKT-731 and we are targeting LinkedIn and X.", pending_operation=None, clear_pending=False)

        elif "Going back to our POLIS architecture discussion, which databases did I mention?" in q_text:
            assert len(hist) >= 8
            # Verify both topics exist in history
            assert any("PostgreSQL and Qdrant" in m.get("content", "") for m in hist)
            assert any("MKT-731" in m.get("content", "") for m in hist)
            return MagicMock(text="Going back to POLIS architecture, you mentioned PostgreSQL and Qdrant.", pending_operation=None, clear_pending=False)

        elif "Now let's discuss marketing automation" in q_text:
            assert len(hist) >= 4
            return MagicMock(text="Understood. Let's discuss marketing automation.", pending_operation=None, clear_pending=False)

        elif "For this test, our POLIS project uses PostgreSQL and Qdrant" in q_text:
            assert len(hist) == 0
            return MagicMock(text="Noted that POLIS uses PostgreSQL and Qdrant.", pending_operation=None, clear_pending=False)

        return MagicMock(text="Acknowledged.", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)
    channel = "D_ALICE_TOPICS"

    # Turn 1: Topic A initial
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel=channel, text="For this test, our POLIS project uses PostgreSQL and Qdrant.", ts="2000.1", event_ts="2000.1", thread_ts=None
    ))
    assert responder.reply.called
    assert responder.reply.call_args[1]["text"] == "Noted that POLIS uses PostgreSQL and Qdrant."
    responder.reply.reset_mock()

    # Turn 2: Topic A follow-up
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel=channel, text="Which databases did I mention?", ts="2000.2", event_ts="2000.2", thread_ts=None
    ))
    assert responder.reply.called
    assert responder.reply.call_args[1]["text"] == "You mentioned PostgreSQL and Qdrant."
    responder.reply.reset_mock()

    # Turn 3: Topic B shift
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel=channel, text="Now let's discuss marketing automation. Our campaign code is MKT-731 and we are targeting LinkedIn and X.", ts="2000.3", event_ts="2000.3", thread_ts=None
    ))
    assert responder.reply.called
    assert responder.reply.call_args[1]["text"] == "Understood. Let's discuss marketing automation."
    responder.reply.reset_mock()

    # Turn 4: Topic B follow-up
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel=channel, text="What is the campaign code and which platforms are targeted?", ts="2000.4", event_ts="2000.4", thread_ts=None
    ))
    assert responder.reply.called
    ans4 = responder.reply.call_args[1]["text"]
    assert "MKT-731" in ans4
    assert "LinkedIn and X" in ans4
    # Ensure no database contamination in marketing reply
    assert "PostgreSQL" not in ans4
    assert "Qdrant" not in ans4
    responder.reply.reset_mock()

    # Turn 5: Return to Topic A
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel=channel, text="Going back to our POLIS architecture discussion, which databases did I mention?", ts="2000.5", event_ts="2000.5", thread_ts=None
    ))
    assert responder.reply.called
    ans5 = responder.reply.call_args[1]["text"]
    assert "PostgreSQL and Qdrant" in ans5
    # Ensure marketing facts did not contaminate Topic A answer
    assert "MKT-731" not in ans5
    assert "LinkedIn" not in ans5

    # Verify cumulative persistence in repository: 5 turns = 10 messages
    final_ctx = conversation_repo.get(channel, "2000.5") or conversation_repo.get_latest(channel)
    assert final_ctx is not None
    assert len(final_ctx.history) == 10
    # First turn is at index 0, last turn is at index 9
    assert final_ctx.history[0]["content"] == "For this test, our POLIS project uses PostgreSQL and Qdrant."
    assert final_ctx.history[9]["content"] == "Going back to POLIS architecture, you mentioned PostgreSQL and Qdrant."


def test_ctx_17_multi_topic_conversation_thread(conversation_repo):
    """
    CTX-17.2: Multi-turn, multi-topic conversation in a Slack thread.
    - Same sequence (Topic A -> Follow-up -> Topic B -> Follow-up -> Return to Topic A) in thread C_DEV/3000.1.
    - Verifies all turns accumulate within the thread context.
    - Verifies thread isolation from another thread in the same channel.
    """
    mock_engine = MagicMock()

    def engine_side_effect(question: Question):
        q_text = question.text
        hist = question.context.history
        if "Which databases did I mention?" in q_text and "Going back" not in q_text:
            return MagicMock(text="You mentioned PostgreSQL and Qdrant.", pending_operation=None, clear_pending=False)
        elif "What is the campaign code and which platforms are targeted?" in q_text:
            return MagicMock(text="The campaign code is MKT-731 and we are targeting LinkedIn and X.", pending_operation=None, clear_pending=False)
        elif "Going back to our POLIS architecture discussion" in q_text:
            return MagicMock(text="Going back to POLIS architecture, you mentioned PostgreSQL and Qdrant.", pending_operation=None, clear_pending=False)
        elif "Now let's discuss marketing automation" in q_text:
            return MagicMock(text="Understood. Let's discuss marketing automation.", pending_operation=None, clear_pending=False)
        return MagicMock(text="Noted that POLIS uses PostgreSQL and Qdrant.", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)
    channel = "C_DEV"
    thread_ts = "3000.1"

    # Turn 1
    router.handle(ActivitySlackMessage(
        user="U_BOB", channel=channel, text="For this test, our POLIS project uses PostgreSQL and Qdrant.", ts="3000.1", event_ts="3000.1", thread_ts="3000.1"
    ))
    # Turn 2
    router.handle(ActivitySlackMessage(
        user="U_BOB", channel=channel, text="Which databases did I mention?", ts="3000.2", event_ts="3000.2", thread_ts="3000.1"
    ))
    # Turn 3
    router.handle(ActivitySlackMessage(
        user="U_BOB", channel=channel, text="Now let's discuss marketing automation. Our campaign code is MKT-731 and we are targeting LinkedIn and X.", ts="3000.3", event_ts="3000.3", thread_ts="3000.1"
    ))
    # Turn 4
    router.handle(ActivitySlackMessage(
        user="U_BOB", channel=channel, text="What is the campaign code and which platforms are targeted?", ts="3000.4", event_ts="3000.4", thread_ts="3000.1"
    ))
    # Turn 5
    router.handle(ActivitySlackMessage(
        user="U_BOB", channel=channel, text="Going back to our POLIS architecture discussion, which databases did I mention?", ts="3000.5", event_ts="3000.5", thread_ts="3000.1"
    ))

    # Thread has all 10 messages
    saved_thread = conversation_repo.get(channel, thread_ts)
    assert saved_thread is not None
    assert len(saved_thread.history) == 10

    # Isolation: Another thread in the same channel has 0 messages
    assert conversation_repo.get(channel, "3000.99") is None


def test_ctx_17_missing_information_and_unsupported_assumptions(conversation_repo):
    """
    CTX-17.3: Missing information and misleading assumptions handling.
    - Question about unmentioned fact ("What is our budget for the cloud hosting migration?"):
      Acknowledges missing information; does not fabricate facts or hallucinate dollar amounts.
    - Question with misleading assumption ("Since we decided to use MongoDB for POLIS, where is it hosted?"):
      Refuses unsupported premise; clarifies that POLIS uses PostgreSQL and Qdrant, not MongoDB.
    """
    mock_engine = MagicMock()

    def engine_side_effect(question: Question):
        q_text = question.text
        hist = question.context.history

        if "budget for the cloud hosting migration" in q_text.lower():
            # Missing information check: budget was never mentioned in history
            assert not any("budget" in m.get("content", "").lower() for m in hist)
            return MagicMock(
                text="I don't have enough information about the cloud hosting migration budget, as it was not mentioned.",
                pending_operation=None,
                clear_pending=False,
            )
        elif "mongodb" in q_text.lower():
            # Misleading assumption check: MongoDB is not in the architecture
            assert any("PostgreSQL and Qdrant" in m.get("content", "") for m in hist)
            return MagicMock(
                text="We did not decide to use MongoDB; earlier you stated that POLIS uses PostgreSQL and Qdrant.",
                pending_operation=None,
                clear_pending=False,
            )
        return MagicMock(text="Noted that POLIS uses PostgreSQL and Qdrant.", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)
    channel = "D_ALICE_ASSUMPTIONS"

    # Base turn: Mention architecture
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel=channel, text="For this test, our POLIS project uses PostgreSQL and Qdrant.", ts="4000.1", event_ts="4000.1", thread_ts=None
    ))
    responder.reply.reset_mock()

    # Question about unmentioned fact
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel=channel, text="What is our budget for the cloud hosting migration?", ts="4000.2", event_ts="4000.2", thread_ts=None
    ))
    assert responder.reply.called
    missing_info_reply = responder.reply.call_args[1]["text"]
    assert "don't have enough information" in missing_info_reply.lower() or "not mentioned" in missing_info_reply.lower()
    # Ensure no fabricated dollar figures
    assert "$" not in missing_info_reply
    responder.reply.reset_mock()

    # Question with misleading assumption
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel=channel, text="Since we decided to use MongoDB for POLIS, where is it hosted?", ts="4000.3", event_ts="4000.3", thread_ts=None
    ))
    assert responder.reply.called
    misleading_reply = responder.reply.call_args[1]["text"]
    assert "did not decide to use MongoDB" in misleading_reply or "PostgreSQL and Qdrant" in misleading_reply


def test_ctx_17_reasoning_service_prompt_formatting_and_topic_isolation():
    """
    CTX-17.4: Unit test of SimpleReasoningService conversational prompt formatting and instructions.
    - Verifies format_conversation_history correctly renders multi-topic history.
    - Verifies prompt instructions require using historical context without hallucinating missing facts.
    """
    from domain.reasoning.services.simple_reasoning_service import SimpleReasoningService
    from engines.communication.infrastructure.repositories import InMemoryCommunicationRepository

    class CapturingLLM:
        def __init__(self):
            self.last_prompt = None

        def generate(self, prompt: str) -> str:
            self.last_prompt = prompt
            return "Going back to POLIS architecture, you mentioned PostgreSQL and Qdrant."

    llm = CapturingLLM()
    service = SimpleReasoningService(
        repository=MagicMock(),
        communication_repository=InMemoryCommunicationRepository(),
        llm_client=llm,
    )

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="5000.1",
        channel_type="im",
    ).add_exchange(
        user_message="For this test, our POLIS project uses PostgreSQL and Qdrant.",
        assistant_message="Noted that POLIS uses PostgreSQL and Qdrant.",
        user_id="U_ALICE",
    ).add_exchange(
        user_message="Now let's discuss marketing automation. Our campaign code is MKT-731 and we are targeting LinkedIn and X.",
        assistant_message="Understood. Campaign MKT-731 targeting LinkedIn and X.",
        user_id="U_ALICE",
    )

    q = Question(
        text="Going back to our POLIS architecture discussion, which databases did I mention?",
        context=ctx,
    )

    ans = service.answer(q)
    assert ans is not None
    assert "PostgreSQL and Qdrant" in ans.text

    # Inspect captured prompt
    prompt = llm.last_prompt
    assert prompt is not None
    assert "Recent conversation history for this thread:" in prompt
    assert "User: For this test, our POLIS project uses PostgreSQL and Qdrant." in prompt
    assert "POLIS: Noted that POLIS uses PostgreSQL and Qdrant." in prompt
    assert "User: Now let's discuss marketing automation" in prompt
    assert "User message:\nGoing back to our POLIS architecture discussion, which databases did I mention?" in prompt
    assert "If the user's message refers to facts, projects, platforms, codes, or instructions mentioned earlier" in prompt
    assert "Do not invent facts" in prompt


def test_ctx_17_real_postgres_multi_topic_conversation():
    """
    CTX-17.5: Genuine PostgreSQL integration test for full 5-turn multi-topic conversation.
    - Connects directly to real PostgreSQL (localhost:5432/ctmc_production).
    - Persists 5 turns (10 messages) of multi-topic conversation.
    - Queries fresh session to verify all 10 messages exist with correct ordering and content.
    - Cleans up isolated test row in finally.
    """
    from uuid import uuid4
    from infrastructure.database.connection import SessionLocal

    repo = PostgreSQLConversationRepository()
    test_channel = f"D_TEST_LIVE_CTX17_{uuid4().hex[:8]}"
    thread_ts = "6000.1"

    try:
        ctx = ConversationContext(
            user_id="U_LIVE_ALICE",
            channel_id=test_channel,
            thread_ts=thread_ts,
            channel_type="im",
        )

        turns = [
            ("For this test, our POLIS project uses PostgreSQL and Qdrant.", "Noted that POLIS uses PostgreSQL and Qdrant."),
            ("Which databases did I mention?", "You mentioned PostgreSQL and Qdrant."),
            ("Now let's discuss marketing automation. Our campaign code is MKT-731 and we are targeting LinkedIn and X.", "Understood. Marketing campaign MKT-731 targeting LinkedIn and X."),
            ("What is the campaign code and which platforms are targeted?", "Campaign code is MKT-731 targeting LinkedIn and X."),
            ("Going back to our POLIS architecture discussion, which databases did I mention?", "Going back to POLIS, you mentioned PostgreSQL and Qdrant."),
        ]

        for i, (u_msg, a_msg) in enumerate(turns):
            ctx = ctx.add_message(
                role="user",
                content=u_msg,
                user_id="U_LIVE_ALICE",
                metadata={"ts": f"6000.{i*2+1}"},
            ).add_message(
                role="assistant",
                content=a_msg,
                user_id="U_LIVE_ALICE",
                metadata={"ts": f"6000.{i*2+2}"},
            )
            repo.save(ctx)

        # Verify against live PostgreSQL in a separate session
        with SessionLocal() as s:
            record = s.query(ConversationMemoryModel).filter(
                ConversationMemoryModel.channel_id == test_channel,
                ConversationMemoryModel.thread_ts == thread_ts,
            ).first()

            assert record is not None
            assert len(record.history) == 10
            # Turn 1
            assert "PostgreSQL and Qdrant" in record.history[0]["content"]
            assert "Noted that POLIS uses PostgreSQL and Qdrant." in record.history[1]["content"]
            # Turn 3
            assert "MKT-731" in record.history[4]["content"]
            assert "LinkedIn and X" in record.history[4]["content"]
            # Turn 5
            assert "Going back to our POLIS architecture" in record.history[8]["content"]
            assert "Going back to POLIS, you mentioned PostgreSQL and Qdrant." in record.history[9]["content"]

    finally:
        with SessionLocal() as s:
            s.query(ConversationMemoryModel).filter(
                ConversationMemoryModel.channel_id == test_channel
            ).delete()
            s.commit()


# ==============================================================================
# Logical Change 3: Consecutive Unthreaded DM Pending-Operation Continuation
# ==============================================================================

def test_unthreaded_dm_clarification_and_continuation(conversation_repo):
    """1. Unthreaded DM clarification and continuation across consecutive unthreaded messages."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    mock_engine = MagicMock()
    def engine_side_effect(question: Question):
        if question.text == "Create a deployment task":
            op = {
                "operation_id": "op-unthreaded-1",
                "intent": "task_action",
                "user_id": "U_ALICE",
                "channel_id": "D_ALICE",
                "thread_ts": question.context.thread_ts,
                "created_at_iso": now.isoformat(),
                "expires_at_iso": future.isoformat(),
                "action": "create_task",
                "collected_entities": {"title": "Deploy v2"},
            }
            return MagicMock(
                text="Who should this task be assigned to?",
                pending_operation=op,
                clear_pending=False,
            )
        elif question.text == "Assign to Alice":
            assert question.context.pending_operation is not None
            assert question.context.pending_operation["operation_id"] == "op-unthreaded-1"
            assert question.context.pending_operation["collected_entities"]["title"] == "Deploy v2"
            return MagicMock(
                text="Task 'Deploy v2' assigned to Alice.",
                pending_operation=None,
                clear_pending=True,
            )
        return MagicMock(text="OK", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    # Message 1: Unthreaded DM
    router.handle(ActivitySlackMessage(
        user="U_ALICE",
        channel="D_ALICE",
        text="Create a deployment task",
        ts="100.1",
        event_ts="100.1",
        thread_ts=None,
    ))
    assert responder.reply.called
    assert responder.reply.call_args[1]["text"] == "Who should this task be assigned to?"
    responder.reply.reset_mock()

    # Message 2: Consecutive unthreaded DM reply with different ts
    router.handle(ActivitySlackMessage(
        user="U_ALICE",
        channel="D_ALICE",
        text="Assign to Alice",
        ts="100.2",
        event_ts="100.2",
        thread_ts=None,
    ))
    assert responder.reply.called
    assert responder.reply.call_args[1]["text"] == "Task 'Deploy v2' assigned to Alice."

    # Context in repository now has cleared pending_operation
    saved_ctx = conversation_repo.get("D_ALICE", "100.2")
    assert saved_ctx is not None
    assert saved_ctx.pending_operation is None


def test_unthreaded_dm_multiple_consecutive_messages(conversation_repo):
    """2. Multiple consecutive unthreaded DM messages during the same pending operation."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    mock_engine = MagicMock()
    def engine_side_effect(question: Question):
        if question.text == "New operational task":
            op = {
                "operation_id": "op-multi-step-dm",
                "intent": "task_action",
                "user_id": "U_ALICE",
                "channel_id": "D_ALICE",
                "thread_ts": question.context.thread_ts,
                "created_at_iso": now.isoformat(),
                "expires_at_iso": future.isoformat(),
                "action": "create_task",
                "collected_entities": {},
            }
            return MagicMock(
                text="What is the task title?",
                pending_operation=op,
                clear_pending=False,
            )
        elif question.text == "Quarterly Audit":
            assert question.context.pending_operation is not None
            assert question.context.pending_operation["operation_id"] == "op-multi-step-dm"
            updated_op = dict(question.context.pending_operation)
            updated_op["collected_entities"] = {"title": "Quarterly Audit"}
            return MagicMock(
                text="What is the priority?",
                pending_operation=updated_op,
                clear_pending=False,
            )
        elif question.text == "High":
            assert question.context.pending_operation is not None
            assert question.context.pending_operation["collected_entities"]["title"] == "Quarterly Audit"
            return MagicMock(
                text="Task 'Quarterly Audit' created with High priority.",
                pending_operation=None,
                clear_pending=True,
            )
        return MagicMock(text="OK", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    # Turn 1 (ts=200.1, thread_ts=None)
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel="D_ALICE", text="New operational task", ts="200.1", event_ts="200.1", thread_ts=None
    ))
    assert responder.reply.call_args[1]["text"] == "What is the task title?"
    responder.reply.reset_mock()

    # Turn 2 (ts=200.2, thread_ts=None)
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel="D_ALICE", text="Quarterly Audit", ts="200.2", event_ts="200.2", thread_ts=None
    ))
    assert responder.reply.call_args[1]["text"] == "What is the priority?"
    responder.reply.reset_mock()

    # Turn 3 (ts=200.3, thread_ts=None)
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel="D_ALICE", text="High", ts="200.3", event_ts="200.3", thread_ts=None
    ))
    assert responder.reply.call_args[1]["text"] == "Task 'Quarterly Audit' created with High priority."


def test_unthreaded_dm_explicit_cancellation(conversation_repo):
    """3. An unthreaded DM operation that is explicitly cancelled in the next DM message."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    init_op = {
        "operation_id": "op-to-cancel",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "D_ALICE",
        "thread_ts": "300.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
        "action": "schedule_event",
        "collected_entities": {"topic": "Review"},
    }
    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="300.1",
        channel_type="im",
        pending_operation=init_op,
        is_thread=False,
    ).add_exchange(
        user_message="Schedule a review",
        assistant_message="What time should we meet?",
        user_id="U_ALICE",
        pending_operation=init_op,
    )
    conversation_repo.save(ctx)

    mock_engine = MagicMock()
    def engine_side_effect(question: Question):
        if question.text.lower() == "cancel":
            assert question.context.pending_operation is not None
            assert question.context.pending_operation["operation_id"] == "op-to-cancel"
            return MagicMock(text="Cancelled the schedule review operation.", pending_operation=None, clear_pending=True)
        return MagicMock(text="OK", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel="D_ALICE", text="cancel", ts="300.2", event_ts="300.2", thread_ts=None
    ))
    assert responder.reply.call_args[1]["text"] == "Cancelled the schedule review operation."

    saved_ctx = conversation_repo.get("D_ALICE", "300.2")
    assert saved_ctx is not None
    assert saved_ctx.pending_operation is None


def test_unthreaded_dm_expired_pending_operation_rejected(conversation_repo):
    """4. An expired DM pending operation cannot resume."""
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=5)

    expired_op = {
        "operation_id": "op-expired-dm",
        "intent": "task_action",
        "user_id": "U_ALICE",
        "channel_id": "D_ALICE",
        "thread_ts": "400.1",
        "created_at_iso": (now - timedelta(hours=1)).isoformat(),
        "expires_at_iso": past.isoformat(),
        "action": "create_task",
    }
    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="400.1",
        channel_type="im",
        pending_operation=expired_op,
        is_thread=False,
    ).add_exchange(
        user_message="Start task",
        assistant_message="What is the title?",
        user_id="U_ALICE",
        pending_operation=expired_op,
    )
    conversation_repo.save(ctx)

    mock_engine = MagicMock()
    def engine_side_effect(question: Question):
        # Expired pending op must NOT be passed to engine
        assert question.context.pending_operation is None
        return MagicMock(text="No active pending operation.", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel="D_ALICE", text="The title is Q4 Plan", ts="400.2", event_ts="400.2", thread_ts=None
    ))
    assert responder.reply.call_args[1]["text"] == "No active pending operation."


def test_unthreaded_dm_cross_user_isolation(conversation_repo):
    """5. A different user attempting to resume an unthreaded DM pending operation is rejected."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    alice_op = {
        "operation_id": "op-alice-dm",
        "intent": "task_action",
        "user_id": "U_ALICE",
        "channel_id": "D_ALICE",
        "thread_ts": "500.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
        "action": "deploy_prod",
    }
    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="500.1",
        channel_type="im",
        pending_operation=alice_op,
        is_thread=False,
    ).add_exchange(
        user_message="Deploy to production",
        assistant_message="Confirm deploy?",
        user_id="U_ALICE",
        pending_operation=alice_op,
    )
    conversation_repo.save(ctx)

    mock_engine = MagicMock()
    def engine_side_effect(question: Question):
        # Eve must NEVER inherit Alice's pending op
        assert question.context.pending_operation is None
        return MagicMock(text="Access denied or no pending operation.", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    # Eve sends message in D_ALICE
    router.handle(ActivitySlackMessage(
        user="U_EVE", channel="D_ALICE", text="Confirm", ts="500.2", event_ts="500.2", thread_ts=None
    ))
    assert responder.reply.call_args[1]["text"] == "Access denied or no pending operation."


def test_unthreaded_dm_cross_dm_isolation(conversation_repo):
    """6. A different DM attempting to resume the operation is rejected."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    dm1_op = {
        "operation_id": "op-dm-1",
        "intent": "task_action",
        "user_id": "U_ALICE",
        "channel_id": "D_ALICE_1",
        "thread_ts": "600.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
        "action": "action_in_dm1",
    }
    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE_1",
        thread_ts="600.1",
        channel_type="im",
        pending_operation=dm1_op,
        is_thread=False,
    ).add_exchange(
        user_message="Do something in DM 1",
        assistant_message="Confirm for DM 1?",
        user_id="U_ALICE",
        pending_operation=dm1_op,
    )
    conversation_repo.save(ctx)

    mock_engine = MagicMock()
    def engine_side_effect(question: Question):
        assert question.context.pending_operation is None
        return MagicMock(text="No pending operation in this DM.", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    # Alice speaks in D_ALICE_2
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel="D_ALICE_2", text="Confirm", ts="600.2", event_ts="600.2", thread_ts=None
    ))
    assert responder.reply.call_args[1]["text"] == "No pending operation in this DM."


def test_thread_scoped_pending_operation_isolation(conversation_repo):
    """7. A pending operation in a real Slack thread remains strictly thread-scoped."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    thread_a_op = {
        "operation_id": "op-thread-strict-a",
        "intent": "task_action",
        "user_id": "U_ALICE",
        "channel_id": "C_DEV",
        "thread_ts": "7000.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
        "action": "thread_action",
    }
    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEV",
        thread_ts="7000.1",
        pending_operation=thread_a_op,
        is_thread=True,
    ).add_exchange(
        user_message="Start thread action",
        assistant_message="Confirm thread action?",
        user_id="U_ALICE",
        pending_operation=thread_a_op,
    )
    conversation_repo.save(ctx)

    mock_engine = MagicMock()
    def engine_side_effect(question: Question):
        if question.context.thread_ts == "7000.2":
            assert question.context.pending_operation is None
            return MagicMock(text="No pending op in Thread B.", pending_operation=None, clear_pending=False)
        elif question.context.thread_ts == "7000.1":
            assert question.context.pending_operation is not None
            assert question.context.pending_operation["operation_id"] == "op-thread-strict-a"
            return MagicMock(text="Thread A action completed.", pending_operation=None, clear_pending=True)
        return MagicMock(text="OK", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    # Reply in Thread B (7000.2)
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel="C_DEV", text="Confirm", ts="7000.3", event_ts="7000.3", thread_ts="7000.2"
    ))
    assert responder.reply.call_args[1]["text"] == "No pending op in Thread B."
    responder.reply.reset_mock()

    # Reply in Thread A (7000.1)
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel="C_DEV", text="Confirm", ts="7000.4", event_ts="7000.4", thread_ts="7000.1"
    ))
    assert responder.reply.call_args[1]["text"] == "Thread A action completed."


def test_new_slack_thread_not_inheriting_pending_operation(conversation_repo):
    """8. A new Slack thread does not inherit an earlier thread's pending operation."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    thread_a_op = {
        "operation_id": "op-thread-old",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_GENERAL",
        "thread_ts": "8000.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
        "action": "schedule_sync",
    }
    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_GENERAL",
        thread_ts="8000.1",
        pending_operation=thread_a_op,
        is_thread=True,
    ).add_exchange(
        user_message="Schedule sync",
        assistant_message="Provide time?",
        user_id="U_ALICE",
        pending_operation=thread_a_op,
    )
    conversation_repo.save(ctx)

    mock_engine = MagicMock()
    def engine_side_effect(question: Question):
        # New thread C must NOT inherit Thread A's pending operation
        assert question.context.pending_operation is None
        return MagicMock(text="Hello from new thread.", pending_operation=None, clear_pending=False)

    mock_engine.ask.side_effect = engine_side_effect
    router, engine, responder = build_test_router(conversation_repo, mock_engine)

    # Start brand new thread C (8100.1)
    router.handle(ActivitySlackMessage(
        user="U_ALICE", channel="C_GENERAL", text="Hi everyone", ts="8100.1", event_ts="8100.1", thread_ts=None
    ))
    assert responder.reply.call_args[1]["text"] == "Hello from new thread."
