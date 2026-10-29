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

    assert calendar.handle_message.called
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

    router = SlackIntentRouter(
        engine=mock_engine,
        responder=mock_responder,
        connector=mock_connector,
        conversation_repository=repo,
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