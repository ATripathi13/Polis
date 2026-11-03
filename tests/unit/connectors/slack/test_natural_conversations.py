"""
Comprehensive tests for natural conversations in Slack DMs and threads.

Covers:
1. Normal DM message without @POLIS is processed.
2. DM follow-up without @POLIS is processed.
3. Channel message with explicit POLIS mention is processed.
4. Follow-up in established POLIS thread is processed without mention.
5. Unrelated channel message without mention is ignored.
6. Reply in unrelated thread is ignored.
7. POLIS's own messages are ignored (self-reply loop prevention).
8. Other bot messages are ignored.
9. Thread replies use the correct thread_ts.
10. ConversationContext preserves the correct sender and channel.
11. Duplicate Slack events do not create duplicate replies.
12. Existing reminder and calendar routing in DMs/threads works.
13. Established thread association survives listener restart.
14. Empty DM message generates no reply.
"""

from unittest.mock import MagicMock, patch
import pytest

from connectors.slack.routing import (
    EventDeduplicator,
    clean_slack_text,
    is_bot_mentioned,
    is_direct_message,
)
from domain.reasoning.value_objects import ConversationContext
from infrastructure.database.conversation_repository import (
    InMemoryConversationRepository,
)
from engines.slack.dto import SlackMessage as ActivitySlackMessage


# ==============================================================================
# 1. Routing Utility Tests
# ==============================================================================


def test_clean_slack_text_strips_bot_mentions_and_polis():
    bot_id = "U0BOT12345"
    assert clean_slack_text(f"<@{bot_id}> what is the policy?", bot_id) == "what is the policy?"
    assert clean_slack_text(f"<@{bot_id}|polis> schedule sync", bot_id) == "schedule sync"
    assert clean_slack_text("@polis how do I submit expenses?", bot_id) == "how do I submit expenses?"
    assert clean_slack_text("@POLIS remind @bob to call", bot_id) == "remind @bob to call"
    assert clean_slack_text("Can you elaborate on that?", bot_id) == "Can you elaborate on that?"
    assert clean_slack_text(f"<@{bot_id}>", bot_id) == ""
    assert clean_slack_text("   ", bot_id) == ""
    assert clean_slack_text("", bot_id) == ""


def test_is_bot_mentioned_detects_mention_tokens():
    bot_id = "U0BOT12345"
    assert is_bot_mentioned(f"<@{bot_id}> hello", bot_id) is True
    assert is_bot_mentioned(f"<@{bot_id}|polis> hello", bot_id) is True
    assert is_bot_mentioned("@polis hello", bot_id) is True
    assert is_bot_mentioned("@POLIS hello", bot_id) is True
    assert is_bot_mentioned("hello @polis", bot_id) is True
    assert is_bot_mentioned("hello", bot_id) is False
    assert is_bot_mentioned("<@UOTHER> hello", bot_id) is False
    assert is_bot_mentioned("polishing the floor", bot_id) is False


def test_is_direct_message_detects_dms():
    assert is_direct_message({"channel_type": "im"}, "D0123") is True
    assert is_direct_message({"channel_type": "channel"}, "D0123") is True
    assert is_direct_message({"channel_type": "im"}, "C0123") is True
    assert is_direct_message({"channel_type": "channel"}, "C0123") is False
    assert is_direct_message({}, "G0123") is False


def test_event_deduplicator():
    dedup = EventDeduplicator(max_entries=3)
    assert dedup.is_duplicate("C1", "100.1") is False
    assert dedup.is_duplicate("C1", "100.1") is True  # Duplicate
    assert dedup.is_duplicate("C1", "100.2") is False
    assert dedup.is_duplicate("C2", "100.3") is False
    # Max entries reached (3), adding one more evicts oldest ("C1", "100.1")
    assert dedup.is_duplicate("C3", "100.4") is False
    assert dedup.is_duplicate("C1", "100.1") is False  # Evicted, so seen as new


# ==============================================================================
# 2. SlackSocketListener Tests
# ==============================================================================


@pytest.fixture
def mock_listener_components():
    """Build mock listener dependencies with an in-memory conversation repository."""
    mock_slack_service = MagicMock()
    mock_activity_processor = MagicMock()
    mock_reminder_service = MagicMock()
    mock_calendar_agent = MagicMock()
    mock_calendar_agent.handle_message.return_value = None
    mock_intent_router = MagicMock()
    conv_repo = InMemoryConversationRepository()

    with patch("connectors.slack.socket.listener.AsyncApp"), \
         patch("connectors.slack.socket.listener.AsyncSocketModeHandler"), \
         patch("connectors.slack.socket.listener.SlackConnector"), \
         patch("connectors.slack.socket.listener.SlackClient"), \
         patch("connectors.slack.socket.listener.SlackResponder"):

        from connectors.slack.socket.listener import SlackSocketListener

        listener = SlackSocketListener(
            bot_token="xoxb-test",
            app_token="xapp-test",
            slack_service=mock_slack_service,
            activity_processor=mock_activity_processor,
            reminder_service=mock_reminder_service,
            calendar_agent=mock_calendar_agent,
            conversation_repository=conv_repo,
            intent_router=mock_intent_router,
        )

        mock_identity = MagicMock()
        mock_identity.get_display_name.return_value = "Alice"
        listener._identity_service = mock_identity

        mock_settings = MagicMock()
        mock_settings.slack_bot_user_id = "U_BOT"
        mock_settings.reminder_timezone = "UTC"
        mock_settings.reminder_time_1 = "09:00"
        mock_settings.reminder_time_2 = "17:00"

        with patch("connectors.slack.socket.listener.get_settings", return_value=mock_settings):
            handler = listener._app.event.return_value.call_args[0][0]
            yield listener, handler, conv_repo, mock_intent_router, mock_reminder_service, mock_calendar_agent, mock_settings


@pytest.mark.asyncio
async def test_normal_dm_message_without_polis_is_processed(mock_listener_components):
    """Case 1: POLIS responds to ordinary user messages in a 1:1 Slack DM without @POLIS."""
    listener, handler, repo, router, reminders, calendar, settings = mock_listener_components

    event = {
        "user": "U_ALICE",
        "channel": "D_ALICE",
        "channel_type": "im",
        "text": "What is POLIS?",
        "ts": "100.1",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=settings):
        await handler(event, MagicMock())

    assert router.handle.called
    activity_msg: ActivitySlackMessage = router.handle.call_args[0][0]
    assert activity_msg.user == "U_ALICE"
    assert activity_msg.channel == "D_ALICE"
    assert activity_msg.text == "What is POLIS?"


@pytest.mark.asyncio
async def test_dm_followup_without_polis_is_processed(mock_listener_components):
    """Case 2: A DM follow-up without @POLIS is processed."""
    listener, handler, repo, router, reminders, calendar, settings = mock_listener_components

    # Seed an established DM thread
    ctx = ConversationContext(user_id="U_ALICE", channel_id="D_ALICE", thread_ts="100.1")
    ctx = ctx.add_exchange("What is POLIS?", "POLIS is an AI operating system.")
    repo.save(ctx)

    event = {
        "user": "U_ALICE",
        "channel": "D_ALICE",
        "channel_type": "im",
        "text": "Can you tell me more?",
        "ts": "100.2",
        "thread_ts": "100.1",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=settings):
        await handler(event, MagicMock())

    assert router.handle.called
    activity_msg = router.handle.call_args[0][0]
    assert activity_msg.text == "Can you tell me more?"
    assert activity_msg.thread_ts == "100.1"


@pytest.mark.asyncio
async def test_channel_message_with_explicit_mention_is_processed(mock_listener_components):
    """Case 3: A channel message with explicit POLIS mention is processed."""
    listener, handler, repo, router, reminders, calendar, settings = mock_listener_components

    event = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "<@U_BOT> How do I submit an expense report?",
        "ts": "200.1",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=settings):
        await handler(event, MagicMock())

    assert router.handle.called
    activity_msg = router.handle.call_args[0][0]
    assert activity_msg.channel == "C_GENERAL"
    assert activity_msg.text == "How do I submit an expense report?"


@pytest.mark.asyncio
async def test_followup_in_established_polis_thread_processed_without_mention(mock_listener_components):
    """Case 4: Follow-up in established POLIS thread is processed without mention."""
    listener, handler, repo, router, reminders, calendar, settings = mock_listener_components

    # Establish thread 200.1 in C_GENERAL
    ctx = ConversationContext(user_id="U_ALICE", channel_id="C_GENERAL", thread_ts="200.1")
    ctx = ctx.add_exchange("How do I submit an expense report?", "Go to the portal and upload receipts.")
    repo.save(ctx)

    # Bob asks follow-up in the same thread WITHOUT mentioning POLIS
    event = {
        "user": "U_BOB",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "Where is the portal link?",
        "ts": "200.2",
        "thread_ts": "200.1",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=settings):
        await handler(event, MagicMock())

    assert router.handle.called
    activity_msg = router.handle.call_args[0][0]
    assert activity_msg.user == "U_BOB"
    assert activity_msg.channel == "C_GENERAL"
    assert activity_msg.thread_ts == "200.1"
    assert activity_msg.text == "Where is the portal link?"


@pytest.mark.asyncio
async def test_unrelated_channel_message_without_mention_is_ignored(mock_listener_components):
    """Case 5: An unrelated channel message without mention is ignored."""
    listener, handler, repo, router, reminders, calendar, settings = mock_listener_components

    event = {
        "user": "U_ALICE",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "Anyone free for coffee?",
        "ts": "300.1",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=settings):
        await handler(event, MagicMock())

    # router.handle should NOT be called
    assert not router.handle.called


@pytest.mark.asyncio
async def test_reply_in_unrelated_thread_is_ignored(mock_listener_components):
    """Case 6: A reply in an unrelated thread (POLIS never participated) is ignored."""
    listener, handler, repo, router, reminders, calendar, settings = mock_listener_components

    # Thread 400.1 is an unrelated conversation between Alice and Bob
    event = {
        "user": "U_BOB",
        "channel": "C_GENERAL",
        "channel_type": "channel",
        "text": "Sounds good to me!",
        "ts": "400.2",
        "thread_ts": "400.1",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=settings):
        await handler(event, MagicMock())

    assert not router.handle.called


@pytest.mark.asyncio
async def test_polis_own_messages_are_ignored(mock_listener_components):
    """Case 7: POLIS's own messages are ignored to prevent self-reply loops."""
    listener, handler, repo, router, reminders, calendar, settings = mock_listener_components

    event = {
        "user": "U_BOT",  # Same as slack_bot_user_id
        "channel": "D_ALICE",
        "channel_type": "im",
        "text": "Here is the response you asked for.",
        "ts": "500.1",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=settings):
        await handler(event, MagicMock())

    assert not router.handle.called


@pytest.mark.asyncio
async def test_other_bot_messages_are_ignored(mock_listener_components):
    """Case 8: Other bot messages (bot_id or bot_message subtype) are ignored."""
    listener, handler, repo, router, reminders, calendar, settings = mock_listener_components

    event = {
        "user": "U_SOME_BOT",
        "bot_id": "B_GITHUB_APP",
        "channel": "C_GENERAL",
        "text": "New PR opened",
        "ts": "600.1",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=settings):
        await handler(event, MagicMock())

    assert not router.handle.called


@pytest.mark.asyncio
async def test_duplicate_slack_events_do_not_create_duplicate_replies(mock_listener_components):
    """Case 11: Duplicate Slack events (same channel and ts) are only processed once."""
    listener, handler, repo, router, reminders, calendar, settings = mock_listener_components

    event = {
        "user": "U_ALICE",
        "channel": "D_ALICE",
        "channel_type": "im",
        "text": "First delivery",
        "ts": "700.1",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=settings):
        await handler(event, MagicMock())
        # Simulate retry of the exact same event
        await handler(event, MagicMock())

    # Handled exactly once
    assert router.handle.call_count == 1


@pytest.mark.asyncio
async def test_empty_dm_message_generates_no_reply(mock_listener_components):
    """Empty DM message or whitespace only must not generate unnecessary replies."""
    listener, handler, repo, router, reminders, calendar, settings = mock_listener_components

    event = {
        "user": "U_ALICE",
        "channel": "D_ALICE",
        "channel_type": "im",
        "text": "    ",
        "ts": "800.1",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=settings):
        await handler(event, MagicMock())

    assert not router.handle.called


@pytest.mark.asyncio
async def test_reminder_and_calendar_commands_work_in_dm_without_mention(mock_listener_components):
    """Case 12: Reminder and calendar commands work in DMs without @POLIS."""
    listener, handler, repo, router, reminders, calendar, settings = mock_listener_components

    calendar.handle_message.return_value = "Meeting scheduled for 3 PM."

    event = {
        "user": "U_ALICE",
        "channel": "D_ALICE",
        "channel_type": "im",
        "text": "schedule sync at 3pm",
        "ts": "900.1",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=settings):
        await handler(event, MagicMock())

    calendar.handle_message.assert_called_once_with(
        "schedule sync at 3pm",
        user_id="U_ALICE",
        channel_id="D_ALICE",
    )
    assert listener._responder.reply.called
    assert listener._responder.reply.call_args[1]["text"] == "Meeting scheduled for 3 PM."

    # Verify that the exchange was recorded in the repository to establish thread state
    recorded = repo.get("D_ALICE", "900.1")
    assert recorded is not None
    assert len(recorded.history) == 2
    assert recorded.history[0]["content"] == "schedule sync at 3pm"
    assert recorded.history[1]["content"] == "Meeting scheduled for 3 PM."


@pytest.mark.asyncio
async def test_thread_association_survives_listener_restart(mock_listener_components):
    """Case 13: Thread association survives listener restart when using persistent/shared repository."""
    listener_1, handler_1, shared_repo, _, _, calendar_1, settings = mock_listener_components

    calendar_1.handle_message.return_value = "Standup scheduled."

    # Turn 1: User mentions POLIS in a channel
    event_1 = {
        "user": "U_ALICE",
        "channel": "C_DEVS",
        "channel_type": "channel",
        "text": "<@U_BOT> schedule standup tomorrow",
        "ts": "1000.1",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=settings):
        await handler_1(event_1, MagicMock())

    # Verify thread 1000.1 was established in shared_repo
    assert shared_repo.get("C_DEVS", "1000.1") is not None

    # Simulate Listener Restart: Create a brand new listener instance with the same shared_repo
    with patch("connectors.slack.socket.listener.AsyncApp"), \
         patch("connectors.slack.socket.listener.AsyncSocketModeHandler"), \
         patch("connectors.slack.socket.listener.SlackConnector"), \
         patch("connectors.slack.socket.listener.SlackClient"), \
         patch("connectors.slack.socket.listener.SlackResponder"):

        from connectors.slack.socket.listener import SlackSocketListener

        mock_router_2 = MagicMock()
        listener_2 = SlackSocketListener(
            bot_token="xoxb-test",
            app_token="xapp-test",
            slack_service=MagicMock(),
            activity_processor=MagicMock(),
            conversation_repository=shared_repo,
            intent_router=mock_router_2,
        )
        listener_2._identity_service = MagicMock()
        handler_2 = listener_2._app.event.return_value.call_args[0][0]

    # Turn 2: Follow-up in the same thread WITHOUT @POLIS arriving at the new listener instance
    event_2 = {
        "user": "U_BOB",
        "channel": "C_DEVS",
        "channel_type": "channel",
        "text": "What time is it set for?",
        "ts": "1000.2",
        "thread_ts": "1000.1",
    }

    with patch("connectors.slack.socket.listener.get_settings", return_value=settings):
        await handler_2(event_2, MagicMock())

    # Listener 2 recognized the established thread from shared_repo and processed the message!
    assert mock_router_2.handle.called
    msg = mock_router_2.handle.call_args[0][0]
    assert msg.text == "What time is it set for?"
    assert msg.thread_ts == "1000.1"


# ==============================================================================
# 3. Intent Router Context & Identity Tests
# ==============================================================================


def test_intent_router_preserves_sender_identity_and_thread_ts():
    """Case 9 & 10: Router preserves correct thread_ts and actual sender's user_id in ConversationContext."""
    from engines.slack.router.slack_intent_router import SlackIntentRouter

    mock_engine = MagicMock()
    mock_engine.ask.return_value = MagicMock(text="Here is your answer")
    mock_responder = MagicMock()
    mock_connector = MagicMock()
    repo = InMemoryConversationRepository()

    # Pre-populate thread 2000.1 started by ALICE
    alice_ctx = ConversationContext(user_id="U_ALICE", channel_id="C_TEAM", thread_ts="2000.1")
    alice_ctx = alice_ctx.add_exchange("First question", "First answer")
    repo.save(alice_ctx)

    mock_identity_service = MagicMock()
    mock_identity_service.get_workspace_users.return_value = []

    router = SlackIntentRouter(
        engine=mock_engine,
        responder=mock_responder,
        connector=mock_connector,
        conversation_repository=repo,
        identity_service=mock_identity_service,
    )

    # Bob sends a follow-up in the thread
    bob_msg = ActivitySlackMessage(
        user="U_BOB",
        channel="C_TEAM",
        text="What about my open tasks?",
        ts="2000.2",
        event_ts="2000.2",
        thread_ts="2000.1",
    )

    router.handle(bob_msg)

    # Verify question passed to engine
    assert mock_engine.ask.called
    asked_question = mock_engine.ask.call_args[0][0]
    # Sender user_id in ConversationContext MUST be Bob (actual sender), not Alice
    assert asked_question.context.user_id == "U_BOB"
    assert asked_question.context.channel_id == "C_TEAM"
    assert asked_question.context.thread_ts == "2000.1"

    # Verify reply sent with correct thread_ts
    assert mock_responder.reply.called
    reply_args = mock_responder.reply.call_args[1]
    assert reply_args["channel"] == "C_TEAM"
    assert reply_args["thread_ts"] == "2000.1"
    assert reply_args["text"] == "Here is your answer"

    # Verify updated history contains Bob's message
    updated_ctx = repo.get("C_TEAM", "2000.1")
    assert len(updated_ctx.history) == 4
    assert updated_ctx.history[2]["user_id"] == "U_BOB"
    assert updated_ctx.history[2]["content"] == "What about my open tasks?"


# ==============================================================================
# 4. SlackSocketMode Tests
# ==============================================================================


def test_socket_mode_handles_dm_and_thread_continuation():
    """Verify SlackSocketMode responds to DMs and thread continuations without mention."""
    from connectors.slack.socket_mode import SlackSocketMode

    mock_slack_service = MagicMock()
    mock_slack_service.ask.return_value = MagicMock(text="Cognitive answer", confidence=0.95)
    mock_reminder_service = MagicMock()
    mock_slack_client = MagicMock()
    repo = InMemoryConversationRepository()

    with patch("connectors.slack.socket_mode.App"):
        socket_mode = SlackSocketMode(
            slack_service=mock_slack_service,
            reminder_service=mock_reminder_service,
            slack_client=mock_slack_client,
            conversation_repository=repo,
        )

    handler = socket_mode._app.event.return_value.call_args[0][0]
    mock_say = MagicMock()

    # 1. Normal DM without mention
    dm_event = {
        "user": "U_ALICE",
        "channel": "D_TEST",
        "channel_type": "im",
        "text": "Hello POLIS",
        "ts": "3000.1",
    }
    handler(dm_event, mock_say, MagicMock())
    assert mock_say.called
    assert mock_say.call_args[1]["text"] == "Cognitive answer"
    assert mock_say.call_args[1]["thread_ts"] == "3000.1"

    # Verify context saved
    assert repo.get("D_TEST", "3000.1") is not None

    mock_say.reset_mock()
    mock_slack_service.ask.reset_mock()

    # 2. Channel message without mention and not in thread -> ignored
    channel_event = {
        "user": "U_ALICE",
        "channel": "C_TEST",
        "channel_type": "channel",
        "text": "Hello channel",
        "ts": "3000.2",
    }
    handler(channel_event, mock_say, MagicMock())
    assert not mock_say.called
    assert not mock_slack_service.ask.called

    # 3. Follow-up in established thread in C_TEST
    # Pre-seed thread 4000.1
    repo.save(ConversationContext(user_id="U_ALICE", channel_id="C_TEST", thread_ts="4000.1").add_exchange("Q", "A"))

    followup_event = {
        "user": "U_BOB",
        "channel": "C_TEST",
        "channel_type": "channel",
        "text": "Follow up question",
        "ts": "4000.2",
        "thread_ts": "4000.1",
    }
    handler(followup_event, mock_say, MagicMock())
    assert mock_say.called
    assert mock_say.call_args[1]["thread_ts"] == "4000.1"
    assert mock_say.call_args[1]["text"] == "Cognitive answer"

def test_get_latest_filters_conversation_history_by_sender():
    """A DM history lookup must not return another sender's conversation."""
    repo = InMemoryConversationRepository()

    alice_context = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_SHARED",
        thread_ts="100.1",
    ).add_exchange("Alice's question", "Alice's answer")

    bob_context = ConversationContext(
        user_id="U_BOB",
        channel_id="D_SHARED",
        thread_ts="200.1",
    ).add_exchange("Bob's question", "Bob's answer")

    repo.save(alice_context)
    repo.save(bob_context)

    alice_latest = repo.get_latest("D_SHARED", user_id="U_ALICE")
    bob_latest = repo.get_latest("D_SHARED", user_id="U_BOB")

    assert alice_latest is not None
    assert alice_latest.thread_ts == "100.1"
    assert alice_latest.history[0]["content"] == "Alice's question"

    assert bob_latest is not None
    assert bob_latest.thread_ts == "200.1"
    assert bob_latest.history[0]["content"] == "Bob's question"

    assert repo.get_latest("D_SHARED", user_id="U_CHARLIE") is None


# ==============================================================================
# 5. DM Thread Isolation and Pending Operation Tests
# ==============================================================================


def test_slack_intent_router_dm_thread_continuation_and_new_thread_isolation():
    """
    Verify:
    1. A user's pending operation remains available when continuing the same DM thread.
    2. A new DM thread restores previous history but does not inherit the previous thread's pending operation.
    """
    from datetime import datetime, timedelta, timezone
    from engines.slack.router.slack_intent_router import SlackIntentRouter

    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    repo = InMemoryConversationRepository()
    alice_op = {
        "operation_id": "op-alice-dm-1",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "D_ALICE",
        "thread_ts": "100.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
    }

    # Pre-seed DM thread 100.1 with Alice's pending operation
    init_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="100.1",
        channel_type="im",
        pending_operation=alice_op,
    ).add_exchange("Schedule sync", "What time?", user_id="U_ALICE", pending_operation=alice_op)
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

    # 1. Alice continues the SAME DM thread (thread_ts="100.1")
    same_thread_msg = ActivitySlackMessage(
        user="U_ALICE",
        channel="D_ALICE",
        text="2 PM please",
        ts="100.2",
        event_ts="100.2",
        thread_ts="100.1",
    )
    router.handle(same_thread_msg)

    assert mock_engine.ask.called
    ctx_same = mock_engine.ask.call_args[0][0].context
    assert ctx_same.thread_ts == "100.1"
    assert ctx_same.pending_operation is not None
    assert ctx_same.pending_operation["operation_id"] == "op-alice-dm-1"

    mock_engine.reset_mock()

    # 2. Alice starts a NEW DM thread (ts="200.1", thread_ts=None)
    new_thread_msg = ActivitySlackMessage(
        user="U_ALICE",
        channel="D_ALICE",
        text="New conversation starting now",
        ts="200.1",
        event_ts="200.1",
        thread_ts=None,
    )
    router.handle(new_thread_msg)

    assert mock_engine.ask.called
    ctx_new = mock_engine.ask.call_args[0][0].context
    assert ctx_new.thread_ts == "200.1"
    # Previous history is restored
    assert len(ctx_new.history) >= 2
    assert ctx_new.history[0]["content"] == "Schedule sync"
    # But previous thread's pending operation is NOT inherited!
    assert ctx_new.pending_operation is None
    assert ctx_new.get_pending_operation() is None


def test_slack_intent_router_shared_channel_different_user_isolation():
    """Verify a different user's pending operation in a shared channel cannot be inherited."""
    from datetime import datetime, timedelta, timezone
    from engines.slack.router.slack_intent_router import SlackIntentRouter

    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    repo = InMemoryConversationRepository()
    alice_op = {
        "operation_id": "op-alice-shared",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_DEV",
        "thread_ts": "300.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
    }

    # Pre-seed shared thread 300.1 with Alice's pending operation
    init_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEV",
        thread_ts="300.1",
        pending_operation=alice_op,
    ).add_exchange("Book room", "Which room?", user_id="U_ALICE", pending_operation=alice_op)
    repo.save(init_ctx)

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

    # Bob speaks in Alice's thread
    bob_msg = ActivitySlackMessage(
        user="U_BOB",
        channel="C_DEV",
        text="Is this room free?",
        ts="300.2",
        event_ts="300.2",
        thread_ts="300.1",
    )
    router.handle(bob_msg)

    ctx_bob = mock_engine.ask.call_args[0][0].context
    assert ctx_bob.user_id == "U_BOB"
    assert ctx_bob.pending_operation is None
    assert ctx_bob.get_pending_operation() is None


def test_socket_mode_dm_thread_continuation_and_new_thread_isolation():
    """
    Verify SlackSocketMode:
    1. A user's pending operation remains available when continuing the same DM thread.
    2. A new DM thread restores previous history but does not inherit the previous thread's pending operation.
    """
    from datetime import datetime, timedelta, timezone
    from connectors.slack.socket_mode import SlackSocketMode

    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    repo = InMemoryConversationRepository()
    alice_op = {
        "operation_id": "op-alice-sm-dm",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "D_ALICE",
        "thread_ts": "500.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
    }

    init_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_ALICE",
        thread_ts="500.1",
        channel_type="im",
        pending_operation=alice_op,
    ).add_exchange("Schedule sync", "What time?", user_id="U_ALICE", pending_operation=alice_op)
    repo.save(init_ctx)

    mock_slack_service = MagicMock()
    mock_slack_service.ask.return_value = MagicMock(text="Cognitive answer", confidence=0.95)
    mock_say = MagicMock()

    with patch("connectors.slack.socket_mode.App"):
        socket_mode = SlackSocketMode(
            slack_service=mock_slack_service,
            reminder_service=MagicMock(),
            slack_client=MagicMock(),
            conversation_repository=repo,
        )

    handler = socket_mode._app.event.return_value.call_args[0][0]

    # 1. Alice continues the SAME DM thread (thread_ts="500.1")
    same_thread_event = {
        "user": "U_ALICE",
        "channel": "D_ALICE",
        "channel_type": "im",
        "text": "Tomorrow at 4 PM",
        "ts": "500.2",
        "thread_ts": "500.1",
    }
    handler(same_thread_event, mock_say, MagicMock())

    assert mock_slack_service.ask.called
    ctx_same = mock_slack_service.ask.call_args[0][0].context
    assert ctx_same.thread_ts == "500.1"
    assert ctx_same.pending_operation is not None
    assert ctx_same.pending_operation["operation_id"] == "op-alice-sm-dm"

    mock_slack_service.ask.reset_mock()

    # 2. Alice starts a NEW DM thread (ts="600.1", thread_ts=None)
    new_thread_event = {
        "user": "U_ALICE",
        "channel": "D_ALICE",
        "channel_type": "im",
        "text": "Brand new question in new thread",
        "ts": "600.1",
    }
    handler(new_thread_event, mock_say, MagicMock())

    assert mock_slack_service.ask.called
    ctx_new = mock_slack_service.ask.call_args[0][0].context
    assert ctx_new.thread_ts == "600.1"
    # History is restored from previous DM context
    assert len(ctx_new.history) >= 2
    # Pending operation is NOT inherited
    assert ctx_new.pending_operation is None
    assert ctx_new.get_pending_operation() is None


def test_socket_mode_shared_channel_different_user_isolation():
    """Verify SlackSocketMode prevents a different user in a shared channel from inheriting pending operations."""
    from datetime import datetime, timedelta, timezone
    from connectors.slack.socket_mode import SlackSocketMode

    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    repo = InMemoryConversationRepository()
    alice_op = {
        "operation_id": "op-alice-sm-shared",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_TEST",
        "thread_ts": "800.1",
        "expires_at_iso": future.isoformat(),
    }

    init_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_TEST",
        thread_ts="800.1",
        pending_operation=alice_op,
    ).add_exchange("Book flight", "Which date?", user_id="U_ALICE", pending_operation=alice_op)
    repo.save(init_ctx)

    mock_slack_service = MagicMock()
    mock_slack_service.ask.return_value = MagicMock(text="Cognitive answer", confidence=0.95)
    mock_say = MagicMock()

    with patch("connectors.slack.socket_mode.App"):
        socket_mode = SlackSocketMode(
            slack_service=mock_slack_service,
            reminder_service=MagicMock(),
            slack_client=MagicMock(),
            conversation_repository=repo,
        )

    handler = socket_mode._app.event.return_value.call_args[0][0]

    # Bob speaks in Alice's thread in C_TEST
    bob_event = {
        "user": "U_BOB",
        "channel": "C_TEST",
        "channel_type": "channel",
        "text": "Can I also book a ticket?",
        "ts": "800.2",
        "thread_ts": "800.1",
    }
    handler(bob_event, mock_say, MagicMock())

    assert mock_slack_service.ask.called
    ctx_bob = mock_slack_service.ask.call_args[0][0].context
    assert ctx_bob.user_id == "U_BOB"
    assert ctx_bob.pending_operation is None
    assert ctx_bob.get_pending_operation() is None


# ==============================================================================
# Milestone 4: Logging Compliance & Sensitive Data Sanitization Tests
# ==============================================================================


def test_sanitize_error_message_masks_uris_and_passwords():
    """Verify _sanitize_error_message scrubs database URIs and DSN password arguments."""
    from engines.slack.router.slack_intent_router import _sanitize_error_message

    raw_uri_err = "Failed connection to postgresql://admin_user:SuperSecretPassword123@10.0.1.5:5432/ctmc_db"
    sanitized = _sanitize_error_message(raw_uri_err)
    assert "SuperSecretPassword123" not in sanitized
    assert "admin_user:***@" in sanitized

    raw_dsn_err = "FATAL: password authentication failed for user 'polis' password='TopSecretPassword456' host=localhost"
    sanitized_dsn = _sanitize_error_message(raw_dsn_err)
    assert "TopSecretPassword456" not in sanitized_dsn
    assert "password='***'" in sanitized_dsn


def test_socket_mode_record_conversation_exchange_sanitizes_credentials(caplog):
    """Verify socket_mode._record_conversation_exchange sanitizes database credentials on failure."""
    import logging
    from connectors.slack.socket_mode import SlackSocketMode

    repo = MagicMock()
    repo.get.return_value = None
    repo.save.side_effect = RuntimeError("DB connection failure postgresql://user:SecretDbPassword@localhost:5432/polis")

    with patch("connectors.slack.socket_mode.App"):
        socket_mode = SlackSocketMode(
            slack_service=MagicMock(),
            reminder_service=MagicMock(),
            slack_client=MagicMock(),
            conversation_repository=repo,
        )

    with caplog.at_level(logging.ERROR):
        socket_mode._record_conversation_exchange(
            channel_id="D_TEST",
            thread_ts="100.1",
            user_id="U_TEST",
            user_message="Hello",
            assistant_message="Hi",
        )

    assert any("Failed to record conversation exchange for thread 100.1" in r.message for r in caplog.records)
    for r in caplog.records:
        assert "SecretDbPassword" not in r.message
        assert "user:***@" in r.message


def test_socket_mode_answer_slack_question_sanitizes_credentials():
    """Verify socket_mode handles unhandled question exceptions with credential sanitization."""
    from connectors.slack.socket_mode import SlackSocketMode

    mock_slack_service = MagicMock()
    mock_slack_service.ask.side_effect = RuntimeError("Connection error to postgresql://admin:SecretDbPassword@localhost:5432/db")
    mock_say = MagicMock()
    mock_bolt_logger = MagicMock()

    with patch("connectors.slack.socket_mode.App"):
        socket_mode = SlackSocketMode(
            slack_service=mock_slack_service,
            reminder_service=MagicMock(),
            slack_client=MagicMock(),
            conversation_repository=MagicMock(),
        )

    handler = socket_mode._app.event.return_value.call_args[0][0]
    event = {
        "user": "U_TEST",
        "channel": "D_TEST",
        "channel_type": "im",
        "text": "Help",
        "ts": "200.1",
    }

    handler(event, mock_say, mock_bolt_logger)

    assert mock_bolt_logger.error.called
    err_msg = mock_bolt_logger.error.call_args[0][0] % tuple(mock_bolt_logger.error.call_args[0][1:])
    assert "SecretDbPassword" not in err_msg
    assert "admin:***@" in err_msg
    assert mock_say.called
    assert "error" in mock_say.call_args[1]["text"].lower()


def test_listener_record_conversation_exchange_sanitizes_credentials(caplog):
    """Verify listener._record_conversation_exchange sanitizes database credentials on failure."""
    import logging
    from connectors.slack.socket.listener import SlackSocketListener

    repo = MagicMock()
    repo.get.return_value = None
    repo.save.side_effect = RuntimeError("DB write timeout postgresql://dbuser:SuperSecretPass@127.0.0.1:5432/ctmc")

    listener = object.__new__(SlackSocketListener)
    listener._conversation_repository = repo

    with caplog.at_level(logging.ERROR):
        listener._record_conversation_exchange(
            channel_id="D_TEST",
            thread_ts="300.1",
            user_id="U_TEST",
            user_message="Hello",
            assistant_message="Hi",
            is_thread=False,
        )

    assert any("Failed to record conversation exchange for thread 300.1" in r.message for r in caplog.records)
    for r in caplog.records:
        assert "SuperSecretPass" not in r.message
        assert "dbuser:***@" in r.message


# ==============================================================================
# 5. Milestone 6 Focused Regression Tests (Defects 1 - 4)
# ==============================================================================


@pytest.mark.asyncio
async def test_established_thread_db_failure_does_not_crash_or_broaden_public_routing(mock_listener_components, caplog):
    """Defect 1: Repository failure during thread check in public channels must not crash or route."""
    import logging
    listener, handler, repo, router, reminders, calendar, settings = mock_listener_components
    repo.get = MagicMock(side_effect=RuntimeError("DB query timeout to postgresql://user:Secret@localhost/db"))

    event = {
        "user": "U_ALICE",
        "channel": "C_PUBLIC",
        "channel_type": "channel",
        "text": "Unrelated reply in thread",
        "ts": "100.2",
        "thread_ts": "100.1",
    }

    with caplog.at_level(logging.WARNING):
        await handler(event, MagicMock())

    assert not router.handle.called
    assert any("Failed to check established thread state" in r.message for r in caplog.records)
    for r in caplog.records:
        assert "Secret" not in r.message


@pytest.mark.asyncio
async def test_established_thread_db_failure_allows_dm_and_mention_routing(mock_listener_components, caplog):
    """Defect 1: Repository failure during thread check must not block DMs or explicit mentions."""
    import logging
    listener, handler, repo, router, reminders, calendar, settings = mock_listener_components
    repo.get = MagicMock(side_effect=RuntimeError("DB connection refused"))

    event = {
        "user": "U_ALICE",
        "channel": "D_ALICE",
        "channel_type": "im",
        "text": "Follow-up question in DM",
        "ts": "100.2",
        "thread_ts": "100.1",
    }

    with caplog.at_level(logging.WARNING):
        await handler(event, MagicMock())

    assert router.handle.called


def test_socket_mode_sync_established_thread_db_failure_isolation():
    """Defect 1 (Sync): Repository failure during thread check in SlackSocketMode must not crash."""
    from connectors.slack.socket_mode import SlackSocketMode

    repo = MagicMock()
    repo.get.side_effect = RuntimeError("PostgreSQL failure")
    mock_say = MagicMock()
    mock_logger = MagicMock()
    mock_slack_service = MagicMock()

    with patch("connectors.slack.socket_mode.App"):
        socket_mode = SlackSocketMode(
            slack_service=mock_slack_service,
            reminder_service=MagicMock(),
            slack_client=MagicMock(),
            conversation_repository=repo,
        )

    handler = socket_mode._app.event.return_value.call_args[0][0]

    # 1. Public channel message with thread_ts should be ignored safely without crashing
    public_event = {
        "user": "U_ALICE",
        "channel": "C_PUBLIC",
        "text": "Unrelated comment",
        "ts": "100.2",
        "thread_ts": "100.1",
    }
    handler(public_event, mock_say, mock_logger)
    assert not mock_slack_service.ask.called

    # 2. Direct message with thread_ts should continue to question handling despite thread lookup failure
    dm_event = {
        "user": "U_ALICE",
        "channel": "D_ALICE",
        "channel_type": "im",
        "text": "DM question",
        "ts": "100.3",
        "thread_ts": "100.1",
    }
    repo.get.side_effect = [RuntimeError("PostgreSQL failure"), None]
    handler(dm_event, mock_say, mock_logger)
    assert mock_slack_service.ask.called


@pytest.mark.asyncio
async def test_listener_reminder_stop_and_create_db_failure_isolation(mock_listener_components, caplog):
    """Defect 2: Reminder create and stop DB failures must be isolated and return safe errors."""
    import logging
    listener, handler, repo, router, reminders, calendar, settings = mock_listener_components

    # 1. Test reminder stop failure
    reminders.stop_for_target.side_effect = RuntimeError("DB drop postgresql://user:SecretPass@host:5432/db")
    stop_event = {
        "user": "U_ALICE",
        "channel": "D_ALICE",
        "channel_type": "im",
        "text": "stop",
        "ts": "100.1",
    }

    with caplog.at_level(logging.ERROR):
        await handler(stop_event, MagicMock())

    assert listener._responder.reply.called
    reply_call = listener._responder.reply.call_args
    assert "error while trying to stop reminders" in reply_call[1]["text"].lower()
    for r in caplog.records:
        assert "SecretPass" not in r.message

    # 2. Test reminder create failure
    listener._responder.reply.reset_mock()
    reminders.create.side_effect = RuntimeError("DB insert timeout")
    create_event = {
        "user": "U_ALICE",
        "channel": "D_ALICE",
        "channel_type": "im",
        "text": "remind <@U01BOB> to review PR",
        "ts": "100.2",
    }

    await handler(create_event, MagicMock())

    assert listener._responder.reply.called
    reply_call = listener._responder.reply.call_args
    assert "error while trying to set that reminder" in reply_call[1]["text"].lower()


def test_socket_mode_reminder_stop_and_create_db_failure_isolation():
    """Defect 2 (Sync): SlackSocketMode reminder DB failures must return safe error text."""
    from connectors.slack.socket_mode import SlackSocketMode

    mock_reminders = MagicMock()
    mock_reminders.stop_for_target.side_effect = RuntimeError("DB connection timeout")
    mock_reminders.create.side_effect = RuntimeError("DB connection timeout")
    mock_say = MagicMock()
    mock_logger = MagicMock()

    with patch("connectors.slack.socket_mode.App"):
        socket_mode = SlackSocketMode(
            slack_service=MagicMock(),
            reminder_service=mock_reminders,
            slack_client=MagicMock(),
        )

    handler = socket_mode._app.event.return_value.call_args[0][0]

    # 1. Stop command
    handler(
        {"user": "U_TEST", "channel": "D_TEST", "channel_type": "im", "text": "stop", "ts": "100.1"},
        mock_say,
        mock_logger,
    )
    assert mock_say.called
    assert "error while trying to stop reminders" in mock_say.call_args[1]["text"].lower()

    # 2. Remind command
    mock_say.reset_mock()
    handler(
        {"user": "U_TEST", "channel": "D_TEST", "channel_type": "im", "text": "remind <@U01TARGET> to test", "ts": "100.2"},
        mock_say,
        mock_logger,
    )
    assert mock_say.called
    assert "error while trying to set that reminder" in mock_say.call_args[1]["text"].lower()


@pytest.mark.asyncio
async def test_slack_socket_listener_graceful_idempotent_shutdown():
    """Defect 3: SlackSocketListener stop() must be idempotent and safely interrupt worker."""
    from unittest.mock import AsyncMock
    from connectors.slack.socket.listener import SlackSocketListener

    with patch("connectors.slack.socket.listener.AsyncApp"), \
         patch("connectors.slack.socket.listener.AsyncSocketModeHandler") as mock_handler_cls:
        mock_handler = MagicMock()
        mock_handler.close_async = AsyncMock()
        mock_handler_cls.return_value = mock_handler

        listener = SlackSocketListener(
            bot_token="xoxb-test",
            app_token="xapp-test",
            slack_service=MagicMock(),
            activity_processor=MagicMock(),
        )

        assert listener._lifecycle_state == "initialized"
        assert not listener._stop_event.is_set()

        # Call stop() once
        await listener.stop()
        assert listener._lifecycle_state == "stopped"
        assert listener._stop_event.is_set()
        assert mock_handler.close_async.called

        # Call stop() second time: must be idempotent and not error
        mock_handler.close_async.reset_mock()
        await listener.stop()
        assert listener._lifecycle_state == "stopped"
        assert not mock_handler.close_async.called


def test_slack_socket_mode_sync_graceful_idempotent_shutdown():
    """Defect 3 (Sync): SlackSocketMode stop() must be idempotent and safely interrupt worker."""
    from connectors.slack.socket_mode import SlackSocketMode

    with patch("connectors.slack.socket_mode.App"):
        socket_mode = SlackSocketMode(
            slack_service=MagicMock(),
            reminder_service=MagicMock(),
            slack_client=MagicMock(),
        )

        socket_mode._handler = MagicMock()
        assert socket_mode._lifecycle_state == "initialized"
        assert not socket_mode._stop_event.is_set()

        # Call stop() once
        socket_mode.stop()
        assert socket_mode._lifecycle_state == "stopped"
        assert socket_mode._stop_event.is_set()
        assert socket_mode._handler.close.called

        # Call stop() second time: must be idempotent
        socket_mode._handler.close.reset_mock()
        socket_mode.stop()
        assert socket_mode._lifecycle_state == "stopped"
        assert not socket_mode._handler.close.called


def test_sanitize_error_message_masks_all_slack_token_prefixes():
    """Defect 4: Verify _sanitize_error_message scrubs all specified Slack token prefixes."""
    from engines.slack.router.slack_intent_router import _sanitize_error_message

    test_tokens = [
        ("xoxb-1234567890-abcdef123456", "xoxb-***"),
        ("xapp-1-A1B2C3D4-567890abcdef", "xapp-***"),
        ("xoxp-9876543210-fedcba654321", "xoxp-***"),
        ("xoxa-2-abcdef01-234567890123", "xoxa-***"),
        ("xoxr-1-abcdef01-234567890123", "xoxr-***"),
        ("xoxs-1-abcdef01-234567890123", "xoxs-***"),
    ]

    for raw_token, expected_masked in test_tokens:
        err_msg = f"Slack client auth error with token {raw_token} for request"
        sanitized = _sanitize_error_message(err_msg)
        assert raw_token not in sanitized, f"Token secret leaked for {raw_token}"
        assert expected_masked in sanitized, f"Expected masked format {expected_masked} in {sanitized}"


@pytest.mark.asyncio
async def test_slack_socket_listener_shutdown_handler_close_failure_path():
    """Verify SlackSocketListener gracefully isolates handler.close_async() failure and sets state to stopped."""
    from unittest.mock import AsyncMock
    from connectors.slack.socket.listener import SlackSocketListener

    with patch("connectors.slack.socket.listener.AsyncApp"), \
         patch("connectors.slack.socket.listener.AsyncSocketModeHandler") as mock_handler_cls:
        mock_handler = MagicMock()
        mock_handler.close_async = AsyncMock(side_effect=RuntimeError("WebSocket close failed abruptly"))
        mock_handler_cls.return_value = mock_handler

        listener = SlackSocketListener(
            bot_token="xoxb-test",
            app_token="xapp-test",
            slack_service=MagicMock(),
            activity_processor=MagicMock(),
        )

        # stop() should catch the exception and finish transition
        await listener.stop()
        assert listener._lifecycle_state == "stopped"

        # Subsequent stop should be a clean no-op
        mock_handler.close_async.reset_mock()
        await listener.stop()
        assert not mock_handler.close_async.called


def test_slack_socket_mode_sync_shutdown_handler_close_failure_path():
    """Verify SlackSocketMode gracefully isolates handler.close() failure and sets state to stopped."""
    from connectors.slack.socket_mode import SlackSocketMode

    with patch("connectors.slack.socket_mode.App"):
        socket_mode = SlackSocketMode(
            slack_service=MagicMock(),
            reminder_service=MagicMock(),
            slack_client=MagicMock(),
        )

        mock_handler = MagicMock()
        mock_handler.close.side_effect = RuntimeError("Sync close socket error")
        socket_mode._handler = mock_handler

        # stop() should catch the exception and finish transition
        socket_mode.stop()
        assert socket_mode._lifecycle_state == "stopped"

        # Subsequent stop should be a clean no-op
        mock_handler.close.reset_mock()
        socket_mode.stop()
        assert not mock_handler.close.called


@pytest.mark.asyncio
async def test_slack_socket_listener_stop_terminates_active_reminder_worker():
    """Verify SlackSocketListener.stop() sets _stop_event and safely joins the reminder worker thread."""
    import threading
    from unittest.mock import AsyncMock
    from connectors.slack.socket.listener import SlackSocketListener

    with patch("connectors.slack.socket.listener.AsyncApp"), \
         patch("connectors.slack.socket.listener.AsyncSocketModeHandler") as mock_handler_cls:
        mock_handler = MagicMock()
        mock_handler.close_async = AsyncMock()
        mock_handler_cls.return_value = mock_handler

        listener = SlackSocketListener(
            bot_token="xoxb-test",
            app_token="xapp-test",
            slack_service=MagicMock(),
            activity_processor=MagicMock(),
            reminder_service=MagicMock(),
        )

        listener._reminder_service.find_due.return_value = []
        listener._reminder_worker_thread = threading.Thread(
            target=listener._run_reminder_worker,
            name="test-async-worker",
            daemon=True,
        )
        listener._reminder_worker_thread.start()
        assert listener._reminder_worker_thread.is_alive()

        await listener.stop()
        assert not listener._reminder_worker_thread.is_alive()
        assert listener._lifecycle_state == "stopped"


def test_slack_socket_mode_sync_stop_terminates_active_reminder_worker():
    """Verify SlackSocketMode.stop() sets _stop_event and safely joins the reminder worker thread."""
    import threading
    from connectors.slack.socket_mode import SlackSocketMode

    with patch("connectors.slack.socket_mode.App"):
        socket_mode = SlackSocketMode(
            slack_service=MagicMock(),
            reminder_service=MagicMock(),
            slack_client=MagicMock(),
        )

        socket_mode._reminder_service.find_due.return_value = []
        socket_mode._reminder_worker_thread = threading.Thread(
            target=socket_mode._run_reminder_worker,
            name="test-sync-worker",
            daemon=True,
        )
        socket_mode._reminder_worker_thread.start()
        assert socket_mode._reminder_worker_thread.is_alive()

        socket_mode.stop()
        assert not socket_mode._reminder_worker_thread.is_alive()
        assert socket_mode._lifecycle_state == "stopped"
