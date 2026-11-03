"""
Unit tests for Centralized NLU and Cognitive Planning domain contracts & pending operation context.
"""

from datetime import datetime, timedelta, timezone
import pytest

from domain.reasoning.value_objects import (
    ActionType,
    CognitivePlan,
    ConversationContext,
    ExecutionStep,
    ExtractedEntities,
    IntentCategory,
    PendingOperation,
    TargetAgent,
)


def test_request_plan_domain_models():
    """Verify serialization and validation of CognitivePlan and its components."""
    entities = ExtractedEntities(
        employee_names=["Rahul Sharma"],
        target_user_id="U_RAHUL",
        target_user_name="Rahul",
        dates=["2026-10-31"],
        times=["14:00"],
        duration_minutes=30,
        event_title="Sprint Sync",
        audience_type="individual",
        audience_id="U_RAHUL",
    )

    step = ExecutionStep(
        step_id="step_1",
        agent=TargetAgent.CALENDAR_AGENT,
        action="schedule_entry",
        action_type=ActionType.CREATE,
        parameters={
            "title": "Sprint Sync",
            "start_time": "2026-10-31T14:00:00+05:30",
            "audience_type": "individual",
            "audience_id": "U_RAHUL",
        },
    )

    plan = CognitivePlan(
        request_id="req-123",
        original_message="Schedule sprint sync with Rahul tomorrow at 2pm",
        intent=IntentCategory.CALENDAR_ACTION,
        intent_confidence=0.98,
        requested_outcome="Schedule meeting with Rahul",
        entities=entities,
        required_agents=[TargetAgent.CALENDAR_AGENT],
        execution_steps=[step],
        missing_information=[],
        requires_clarification=False,
        action_required=True,
        risk_level="low",
    )

    data = plan.model_dump()
    assert data["request_id"] == "req-123"
    assert data["intent"] == "calendar_action"
    assert data["entities"]["target_user_id"] == "U_RAHUL"
    assert len(data["execution_steps"]) == 1

    restored = CognitivePlan.model_validate(data)
    assert restored.request_id == plan.request_id
    assert restored.intent == IntentCategory.CALENDAR_ACTION
    assert restored.entities.employee_names == ["Rahul Sharma"]


def test_pending_operation_model():
    """Verify PendingOperation structure and serialization."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)

    pending = PendingOperation(
        operation_id="op-1",
        intent=IntentCategory.CALENDAR_ACTION,
        target_agent=TargetAgent.CALENDAR_AGENT,
        action="create_entry",
        collected_entities={"title": "Sprint Sync", "participant": "Rahul"},
        missing_fields=["start_time"],
        clarification_question="What time should the sprint sync take place?",
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="100.1",
        created_at_iso=now.isoformat(),
        expires_at_iso=expires.isoformat(),
    )

    dumped = pending.model_dump()
    assert dumped["operation_id"] == "op-1"
    assert dumped["intent"] == "calendar_action"
    assert dumped["missing_fields"] == ["start_time"]


def test_conversation_context_pending_operation_lifecycle():
    """Verify ConversationContext handles pending operations cleanly across exchanges."""
    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="100.1",
    )

    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=10)

    pending = PendingOperation(
        operation_id="op-123",
        intent=IntentCategory.CALENDAR_ACTION,
        target_agent=TargetAgent.CALENDAR_AGENT,
        action="create_entry",
        collected_entities={"title": "Sync with Rahul"},
        missing_fields=["start_time"],
        clarification_question="What time would you like to meet?",
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="100.1",
        created_at_iso=now.isoformat(),
        expires_at_iso=expires.isoformat(),
    )

    # 1. Initial exchange that asks for clarification and stores pending operation
    ctx1 = ctx.add_exchange(
        user_message="Schedule a meeting with Rahul",
        assistant_message="What time would you like to meet?",
        user_id="U_ALICE",
        pending_operation=pending,
    )

    assert ctx1.pending_operation is not None
    assert ctx1.pending_operation["operation_id"] == "op-123"
    assert ctx1.get_pending_operation() is not None
    assert ctx1.get_pending_operation()["collected_entities"]["title"] == "Sync with Rahul"

    # 2. History contains metadata in assistant message for database compatibility
    assert ctx1.history[-1]["role"] == "assistant"
    assert ctx1.history[-1]["pending_operation"]["operation_id"] == "op-123"

    # 3. Follow-up exchange that completes the action clears the pending operation
    ctx2 = ctx1.add_exchange(
        user_message="Tomorrow at 3pm",
        assistant_message="Meeting scheduled for tomorrow at 3:00 PM.",
        user_id="U_ALICE",
        clear_pending=True,
    )

    assert ctx2.pending_operation is None
    assert ctx2.get_pending_operation() is None


def test_conversation_context_pending_operation_expiration():
    """Verify expired pending operations are safely rejected."""
    now = datetime.now(timezone.utc)
    past = now - timedelta(seconds=1)

    expired_pending = {
        "operation_id": "op-expired",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "expires_at_iso": past.isoformat(),
    }

    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="100.1",
        pending_operation=expired_pending,
    )

    assert ctx.get_pending_operation(now=now) is None


def test_conversation_context_pending_operation_ownership_isolation():
    """Verify one user cannot hijack another user's pending operation in shared channels."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=5)

    alice_pending = {
        "operation_id": "op-alice",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_GENERAL",
        "thread_ts": "200.1",
        "expires_at_iso": future.isoformat(),
    }

    # Context accessed by Bob in the same shared channel & thread
    bob_ctx = ConversationContext(
        user_id="U_BOB",
        channel_id="C_GENERAL",
        thread_ts="200.1",
        pending_operation=alice_pending,
    )

    assert bob_ctx.get_pending_operation(now=now) is None

    # Context accessed by Alice
    alice_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_GENERAL",
        thread_ts="200.1",
        pending_operation=alice_pending,
    )

    assert alice_ctx.get_pending_operation(now=now) is not None


def test_repository_save_load_and_cleared_lifecycle():
    """Verify pending operation save, load, and explicit clearing in InMemoryConversationRepository."""
    from infrastructure.database.conversation_repository import InMemoryConversationRepository

    repo = InMemoryConversationRepository()
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_1", thread_ts="100.1")

    # 1. Save with pending operation
    pending = {
        "operation_id": "op-save-load",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_1",
        "thread_ts": "100.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
        "missing_fields": ["time"],
    }

    ctx_with_op = ctx.add_exchange(
        user_message="Schedule sync",
        assistant_message="What time?",
        user_id="U_ALICE",
        pending_operation=pending,
    )
    repo.save(ctx_with_op)

    # Load back
    loaded = repo.get("C_1", "100.1")
    assert loaded is not None
    assert loaded.pending_operation is not None
    assert loaded.get_pending_operation()["operation_id"] == "op-save-load"

    # 2. Complete exchange and clear pending operation
    cleared_ctx = loaded.add_exchange(
        user_message="3 PM",
        assistant_message="Done",
        user_id="U_ALICE",
        clear_pending=True,
    )
    repo.save(cleared_ctx)

    # Load back after clearing
    loaded_cleared = repo.get("C_1", "100.1")
    assert loaded_cleared is not None
    assert loaded_cleared.pending_operation is None
    assert loaded_cleared.get_pending_operation() is None


def test_backward_compatibility_with_legacy_records():
    """Verify older history records without pending_operation metadata remain readable."""
    from infrastructure.database.conversation_repository import InMemoryConversationRepository

    repo = InMemoryConversationRepository()
    legacy_history = [
        {"role": "user", "content": "Hello", "user_id": "U_ALICE"},
        {"role": "assistant", "content": "Hi there!"},
    ]

    legacy_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_LEGACY",
        thread_ts="50.1",
        history=legacy_history,
    )
    repo.save(legacy_ctx)

    loaded = repo.get("C_LEGACY", "50.1")
    assert loaded is not None
    assert len(loaded.history) == 2
    assert loaded.pending_operation is None
    assert loaded.get_pending_operation() is None


def test_harden_expiry_and_malformed_timestamps():
    """Verify malformed timestamps and expired operations are never treated as active."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=10)

    # 1. Malformed timestamp string
    malformed_op = {
        "operation_id": "op-malformed",
        "user_id": "U_ALICE",
        "expires_at_iso": "not-a-timestamp",
    }
    ctx = ConversationContext(
        user_id="U_ALICE", channel_id="C_1", thread_ts="1.1", pending_operation=malformed_op
    )
    assert ctx.get_pending_operation(now=now) is None

    # 2. Missing expiry
    missing_expiry = {
        "operation_id": "op-no-expiry",
        "user_id": "U_ALICE",
    }
    ctx2 = ConversationContext(
        user_id="U_ALICE", channel_id="C_1", thread_ts="1.1", pending_operation=missing_expiry
    )
    assert ctx2.get_pending_operation(now=now) is None

    # 3. Naive ISO timestamp handled cleanly as UTC
    naive_future = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
    naive_op = {
        "operation_id": "op-naive",
        "user_id": "U_ALICE",
        "channel_id": "C_1",
        "thread_ts": "1.1",
        "expires_at_iso": naive_future,
    }
    ctx3 = ConversationContext(
        user_id="U_ALICE", channel_id="C_1", thread_ts="1.1", pending_operation=naive_op
    )
    assert ctx3.get_pending_operation(now=now) is not None


def test_validation_domain_contracts_bounds_and_cycles():
    """Verify validation of confidence bounds, risk level, and execution dependencies."""
    # 1. Invalid confidence > 1.0 or < 0.0
    with pytest.raises(Exception):
        CognitivePlan(
            request_id="r1",
            original_message="test",
            intent=IntentCategory.KNOWLEDGE_QUERY,
            intent_confidence=1.5,
        )

    with pytest.raises(Exception):
        CognitivePlan(
            request_id="r1",
            original_message="test",
            intent=IntentCategory.KNOWLEDGE_QUERY,
            intent_confidence=-0.1,
        )

    # 2. Invalid risk level
    with pytest.raises(Exception):
        CognitivePlan(
            request_id="r1",
            original_message="test",
            intent=IntentCategory.KNOWLEDGE_QUERY,
            risk_level="extreme",  # Not in ("low", "medium", "high", "critical")
        )

    # 3. Self-dependency rejected
    with pytest.raises(ValueError, match="cannot depend on itself"):
        CognitivePlan(
            request_id="r1",
            original_message="test",
            intent=IntentCategory.TASK_ACTION,
            execution_steps=[
                ExecutionStep(
                    step_id="step_a",
                    agent=TargetAgent.OPERATIONS_AGENT,
                    action="create_task",
                    dependencies=["step_a"],
                )
            ],
        )

    # 4. Unknown dependency rejected
    with pytest.raises(ValueError, match="references unknown dependency"):
        CognitivePlan(
            request_id="r1",
            original_message="test",
            intent=IntentCategory.TASK_ACTION,
            execution_steps=[
                ExecutionStep(
                    step_id="step_a",
                    agent=TargetAgent.OPERATIONS_AGENT,
                    action="create_task",
                    dependencies=["non_existent_step"],
                )
            ],
        )

    # 5. Dependency cycle rejected
    with pytest.raises(ValueError, match="Dependency cycle detected"):
        CognitivePlan(
            request_id="r1",
            original_message="test",
            intent=IntentCategory.TASK_ACTION,
            execution_steps=[
                ExecutionStep(
                    step_id="step_1",
                    agent=TargetAgent.OPERATIONS_AGENT,
                    action="action_1",
                    dependencies=["step_2"],
                ),
                ExecutionStep(
                    step_id="step_2",
                    agent=TargetAgent.OPERATIONS_AGENT,
                    action="action_2",
                    dependencies=["step_1"],
                ),
            ],
        )


def test_slack_intent_router_preserves_pending_operation_securely():
    """Verify SlackIntentRouter preserves user's pending operation while isolating other users."""
    from unittest.mock import MagicMock
    from engines.slack.router.slack_intent_router import SlackIntentRouter
    from engines.slack.dto import SlackMessage as ActivitySlackMessage
    from infrastructure.database.conversation_repository import InMemoryConversationRepository

    repo = InMemoryConversationRepository()
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=10)

    alice_pending = {
        "operation_id": "op-alice-schedule",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_DEVS",
        "thread_ts": "5000.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
        "missing_fields": ["time"],
    }

    # Initial context started by Alice with pending operation
    init_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEVS",
        thread_ts="5000.1",
        pending_operation=alice_pending,
    ).add_exchange("Schedule meeting", "What time?", "U_ALICE", pending_operation=alice_pending)
    repo.save(init_ctx)

    mock_engine = MagicMock()
    mock_engine.ask.return_value = MagicMock(text="Engine reply")
    mock_responder = MagicMock()
    mock_identity = MagicMock()
    mock_identity.get_workspace_users.return_value = []

    router = SlackIntentRouter(
        engine=mock_engine,
        responder=mock_responder,
        connector=MagicMock(),
        conversation_repository=repo,
        identity_service=mock_identity,
    )

    # 1. Bob responds in Alice's thread: Bob must NOT inherit Alice's pending operation
    bob_msg = ActivitySlackMessage(
        user="U_BOB",
        channel="C_DEVS",
        text="Can I join too?",
        ts="5000.2",
        event_ts="5000.2",
        thread_ts="5000.1",
    )
    router.handle(bob_msg)

    asked_q_bob = mock_engine.ask.call_args[0][0]
    assert asked_q_bob.context.user_id == "U_BOB"
    assert asked_q_bob.context.pending_operation is None
    assert asked_q_bob.context.get_pending_operation() is None

    # 2. Alice responds in her own thread: Alice DOES preserve her pending operation
    alice_msg = ActivitySlackMessage(
        user="U_ALICE",
        channel="C_DEVS",
        text="Tomorrow at 3 PM",
        ts="5000.3",
        event_ts="5000.3",
        thread_ts="5000.1",
    )
    router.handle(alice_msg)

    asked_q_alice = mock_engine.ask.call_args[0][0]
    assert asked_q_alice.context.user_id == "U_ALICE"
    assert asked_q_alice.context.pending_operation is not None
    assert asked_q_alice.context.pending_operation["operation_id"] == "op-alice-schedule"


def test_active_pending_operation_survives_ordinary_exchange_and_reload():
    """Verify an active pending operation survives an ordinary exchange and repository reload."""
    from infrastructure.database.conversation_repository import InMemoryConversationRepository

    repo = InMemoryConversationRepository()
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_1", thread_ts="100.1")
    pending = {
        "operation_id": "op-survive",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_1",
        "thread_ts": "100.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
    }
    # Initial exchange establishing pending operation
    ctx1 = ctx.add_exchange(
        user_message="Book room",
        assistant_message="Which room?",
        user_id="U_ALICE",
        pending_operation=pending,
    )
    repo.save(ctx1)

    # Reload and verify pending operation is present
    loaded1 = repo.get("C_1", "100.1")
    assert loaded1 is not None
    assert loaded1.get_pending_operation() is not None
    assert loaded1.get_pending_operation()["operation_id"] == "op-survive"

    # Ordinary exchange without clear_pending and without pending_operation argument
    ctx2 = loaded1.add_exchange(
        user_message="Room 3B please",
        assistant_message="Checking Room 3B availability...",
        user_id="U_ALICE",
    )
    assert ctx2.pending_operation is not None
    assert ctx2.pending_operation["operation_id"] == "op-survive"
    repo.save(ctx2)

    # Reload after ordinary exchange: pending operation MUST survive
    loaded2 = repo.get("C_1", "100.1")
    assert loaded2 is not None
    assert loaded2.pending_operation is not None
    assert loaded2.get_pending_operation() is not None
    assert loaded2.get_pending_operation()["operation_id"] == "op-survive"


def test_explicit_clearing_survives_repository_reload():
    """Verify explicitly clearing a pending operation survives repository reload."""
    from infrastructure.database.conversation_repository import InMemoryConversationRepository

    repo = InMemoryConversationRepository()
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_1", thread_ts="100.1")
    pending = {
        "operation_id": "op-clear",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_1",
        "thread_ts": "100.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
    }
    ctx1 = ctx.add_exchange("Book room", "Which room?", user_id="U_ALICE", pending_operation=pending)
    repo.save(ctx1)

    # Explicitly clear pending operation
    ctx2 = ctx1.add_exchange("Nevermind, cancel", "Cancelled the request.", user_id="U_ALICE", clear_pending=True)
    assert ctx2.pending_operation is None
    repo.save(ctx2)

    # Reload after explicit clearing
    loaded = repo.get("C_1", "100.1")
    assert loaded is not None
    assert loaded.pending_operation is None
    assert loaded.get_pending_operation() is None

    # Another normal exchange after clearing must keep it cleared
    ctx3 = loaded.add_exchange("What's the weather?", "It's sunny.", user_id="U_ALICE")
    repo.save(ctx3)
    loaded3 = repo.get("C_1", "100.1")
    assert loaded3 is not None
    assert loaded3.pending_operation is None
    assert loaded3.get_pending_operation() is None


def test_non_dm_slack_routing_safe_from_uninitialized_latest_context():
    """Verify non-DM Slack routing does not raise UnboundLocalError when latest_context is accessed."""
    from unittest.mock import MagicMock
    from engines.slack.router.slack_intent_router import SlackIntentRouter
    from engines.slack.dto import SlackMessage as ActivitySlackMessage
    from infrastructure.database.conversation_repository import InMemoryConversationRepository

    repo = InMemoryConversationRepository()
    mock_engine = MagicMock()
    mock_engine.ask.return_value = MagicMock(text="Engine response")
    mock_responder = MagicMock()
    mock_identity = MagicMock()
    mock_identity.get_workspace_users.return_value = []

    router = SlackIntentRouter(
        engine=mock_engine,
        responder=mock_responder,
        connector=MagicMock(),
        conversation_repository=repo,
        identity_service=mock_identity,
    )

    # Send a message to a non-DM channel (starts with 'C', not 'D') with empty repo (conversation_context is None)
    channel_msg = ActivitySlackMessage(
        user="U_CAROL",
        channel="C_PUBLIC_CHANNEL",
        text="Hello team",
        ts="7000.1",
        event_ts="7000.1",
        thread_ts=None,
    )
    # Must NOT raise UnboundLocalError
    router.handle(channel_msg)

    assert mock_engine.ask.called
    asked = mock_engine.ask.call_args[0][0]
    assert asked.context.channel_id == "C_PUBLIC_CHANNEL"
    assert asked.context.user_id == "U_CAROL"
    assert asked.context.pending_operation is None


def test_dm_history_restored_from_previous_context():
    """Verify Slack DM history is restored from the previous DM context when starting a new thread."""
    from unittest.mock import MagicMock
    from engines.slack.router.slack_intent_router import SlackIntentRouter
    from engines.slack.dto import SlackMessage as ActivitySlackMessage
    from infrastructure.database.conversation_repository import InMemoryConversationRepository

    repo = InMemoryConversationRepository()

    # Previous DM context in thread 100.1
    prev_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="100.1",
        channel_type="im",
    ).add_exchange("First message", "First reply", user_id="U_ALICE")
    repo.save(prev_ctx)

    mock_engine = MagicMock()
    mock_engine.ask.return_value = MagicMock(text="Engine reply")
    mock_responder = MagicMock()
    mock_identity = MagicMock()
    mock_identity.get_workspace_users.return_value = []

    router = SlackIntentRouter(
        engine=mock_engine,
        responder=mock_responder,
        connector=MagicMock(),
        conversation_repository=repo,
        identity_service=mock_identity,
    )

    # New DM message without thread_ts (initiates a new thread ts="200.1")
    new_dm_msg = ActivitySlackMessage(
        user="U_ALICE",
        channel="D_ALICE",
        text="Second message",
        ts="200.1",
        event_ts="200.1",
        thread_ts=None,
    )
    router.handle(new_dm_msg)

    asked = mock_engine.ask.call_args[0][0]
    # Check that previous history was restored!
    assert len(asked.context.history) >= 2
    assert asked.context.history[0]["content"] == "First message"
    assert asked.context.history[1]["content"] == "First reply"


def test_pending_operation_remains_user_scoped():
    """Verify pending operation remains user-scoped and cannot be retrieved across users or channels."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=10)

    alice_op = {
        "operation_id": "op-alice-isolated",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_DEV",
        "thread_ts": "300.1",
        "expires_at_iso": future.isoformat(),
    }

    # Context with Alice's pending operation
    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEV",
        thread_ts="300.1",
        pending_operation=alice_op,
    )

    # Alice can retrieve it
    assert ctx.get_pending_operation(expected_user_id="U_ALICE") is not None
    assert ctx.get_pending_operation(expected_user_id="U_ALICE")["operation_id"] == "op-alice-isolated"

    # Bob querying the same context cannot retrieve it
    assert ctx.get_pending_operation(expected_user_id="U_BOB") is None

    # Another channel cannot retrieve it
    assert ctx.get_pending_operation(expected_user_id="U_ALICE", expected_channel_id="C_OTHER") is None


def test_duplicate_execution_step_ids_rejected():
    """Verify CognitivePlan rejects duplicate execution step IDs before dependency checks."""
    step1 = ExecutionStep(
        step_id="step_alpha",
        agent=TargetAgent.CALENDAR_AGENT,
        action="schedule",
    )
    step2 = ExecutionStep(
        step_id="step_alpha",  # Duplicate step_id
        agent=TargetAgent.OPERATIONS_AGENT,
        action="notify",
    )

    with pytest.raises(ValueError, match="Duplicate step_id 'step_alpha'"):
        CognitivePlan(
            request_id="req-dup",
            original_message="Test duplicate step ids",
            intent=IntentCategory.CALENDAR_ACTION,
            execution_steps=[step1, step2],
        )


def test_duplicate_exchange_does_not_suppress_pending_state_transition():
    """Verify duplicate exchange detection does not suppress legitimate pending state transitions."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=10)

    pending = {
        "operation_id": "op-dup-test",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_1",
        "thread_ts": "100.1",
        "expires_at_iso": future.isoformat(),
    }

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_1", thread_ts="100.1")
    # Turn 1: normal exchange with no pending op
    ctx1 = ctx.add_exchange(
        user_message="Cancel please",
        assistant_message="Are you sure?",
        user_id="U_ALICE",
        pending_operation=pending,
    )
    assert ctx1.pending_operation is not None
    assert len(ctx1.history) == 2

    # Turn 2: same user and assistant message, but with clear_pending=True
    ctx2 = ctx1.add_exchange(
        user_message="Cancel please",
        assistant_message="Are you sure?",
        user_id="U_ALICE",
        clear_pending=True,
    )
    # Must NOT be suppressed by duplicate check because pending state changed!
    assert ctx2.pending_operation is None
    assert ctx2.get_pending_operation() is None
    assert len(ctx2.history) == 4
    assert ctx2.history[-1]["pending_operation"] is None


def test_direct_clear_pending_operation_cannot_be_resurrected_from_history():
    """Verify clear_pending_operation() explicitly clears pending state and history search cannot resurrect it."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=10)

    pending = {
        "operation_id": "op-resurrect-check",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_1",
        "thread_ts": "100.1",
        "expires_at_iso": future.isoformat(),
    }

    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_1", thread_ts="100.1")
    ctx1 = ctx.add_exchange("Schedule sync", "What time?", user_id="U_ALICE", pending_operation=pending)
    assert ctx1.get_pending_operation() is not None

    # Directly clear pending operation on the context instance
    ctx_cleared = ctx1.clear_pending_operation()
    assert ctx_cleared.pending_operation is None
    # Must remain None and NOT resurrect the active operation from ctx1.history
    assert ctx_cleared.get_pending_operation(expected_user_id="U_ALICE") is None
    assert ctx_cleared.get_typed_pending_operation(expected_user_id="U_ALICE") is None


def test_get_typed_pending_operation_and_malformed_scope_fail_closed():
    """Verify typed PendingOperation model retrieval and fail-closed scope validation."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=10)

    # 1. Valid pending operation retrieves typed PendingOperation
    valid_op = {
        "operation_id": "op-typed-1",
        "intent": "calendar_action",
        "target_agent": "calendar_agent",
        "action": "create_entry",
        "user_id": "U_ALICE",
        "channel_id": "C_1",
        "thread_ts": "100.1",
        "expires_at_iso": future.isoformat(),
    }
    ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_1",
        thread_ts="100.1",
        pending_operation=valid_op,
    )
    typed = ctx.get_typed_pending_operation()
    assert typed is not None
    assert isinstance(typed, PendingOperation)
    assert typed.operation_id == "op-typed-1"
    assert typed.target_agent == TargetAgent.CALENDAR_AGENT
    assert typed.intent == IntentCategory.CALENDAR_ACTION

    # 2. Missing user_id fails closed
    no_user = dict(valid_op)
    no_user["user_id"] = ""
    ctx_no_user = ConversationContext(user_id="U_ALICE", channel_id="C_1", thread_ts="100.1", pending_operation=no_user)
    assert ctx_no_user.get_pending_operation() is None
    assert ctx_no_user.get_typed_pending_operation() is None

    # 3. Missing channel_id when expected_channel_id supplied fails closed
    no_chan = dict(valid_op)
    no_chan["channel_id"] = ""
    ctx_no_chan = ConversationContext(user_id="U_ALICE", channel_id="C_1", thread_ts="100.1", pending_operation=no_chan)
    assert ctx_no_chan.get_pending_operation(expected_channel_id="C_1") is None


def test_conversation_context_is_thread_preservation_and_dm_validation():
    """Verify is_thread propagation and unthreaded DM validation rules."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    op_data = {
        "operation_id": "op-dm-test",
        "intent": "task_action",
        "target_agent": "general_reasoner",
        "action": "create_task",
        "user_id": "U_ALICE",
        "channel_id": "D_ALICE",
        "thread_ts": "100.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
    }

    # 1. Verify is_thread defaults to False and propagates across transformations
    ctx_unthreaded = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="100.2",
        channel_type="im",
        pending_operation=op_data,
        is_thread=False,
    )
    assert ctx_unthreaded.is_thread is False

    added_msg = ctx_unthreaded.add_message("user", "Hello")
    assert added_msg.is_thread is False

    with_op = ctx_unthreaded.with_pending_operation(op_data)
    assert with_op.is_thread is False

    cleared = ctx_unthreaded.clear_pending_operation()
    assert cleared.is_thread is False

    exchanged = ctx_unthreaded.add_exchange("ping", "pong")
    assert exchanged.is_thread is False

    # Also verify is_thread=True propagates
    ctx_threaded = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="100.1",
        channel_type="im",
        pending_operation=op_data,
        is_thread=True,
    )
    assert ctx_threaded.is_thread is True
    assert ctx_threaded.add_message("user", "Hello").is_thread is True
    assert ctx_threaded.add_exchange("ping", "pong").is_thread is True

    # 2. Genuine unthreaded DM validates with expected_thread_ts=None without message ts mismatch
    # Even though ctx_unthreaded.thread_ts is "100.2" and op_data["thread_ts"] is "100.1":
    assert ctx_unthreaded.get_pending_operation(expected_user_id="U_ALICE", expected_channel_id="D_ALICE", expected_thread_ts=None) is not None
    assert ctx_unthreaded.get_typed_pending_operation(expected_user_id="U_ALICE", expected_channel_id="D_ALICE", expected_thread_ts=None) is not None

    # Passing the current message's thread_ts on an unthreaded DM does not reject
    assert ctx_unthreaded.get_pending_operation(expected_user_id="U_ALICE", expected_channel_id="D_ALICE", expected_thread_ts="100.2") is not None

    # 3. In an actual thread, thread mismatch is strictly enforced
    # Mismatched thread expectation on threaded context fails
    assert ctx_threaded.get_pending_operation(expected_user_id="U_ALICE", expected_channel_id="D_ALICE", expected_thread_ts="999.9") is None

    # 4. In a channel conversation (non-DM), thread mismatch is strictly enforced
    chan_op_data = dict(op_data)
    chan_op_data["channel_id"] = "C_GENERAL"
    channel_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_GENERAL",
        thread_ts="100.2",
        pending_operation=chan_op_data,
    )
    assert channel_ctx.get_pending_operation(expected_user_id="U_ALICE", expected_channel_id="C_GENERAL", expected_thread_ts=None) is None
    assert channel_ctx.get_pending_operation(expected_user_id="U_ALICE", expected_channel_id="C_GENERAL", expected_thread_ts="100.2") is None
    # Matching thread_ts succeeds
    assert channel_ctx.get_pending_operation(expected_user_id="U_ALICE", expected_channel_id="C_GENERAL", expected_thread_ts="100.1") is not None
