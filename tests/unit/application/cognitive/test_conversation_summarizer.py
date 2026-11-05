"""
Unit tests for ConversationSummarizerService:
- Decision vs suggestion vs action item separation
- Explicit ownership detection
- Unresolved questions extraction
- Authoritative membership verification & fail-closed security
- Secure private DM delivery workflow
"""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from application.cognitive.conversation_summarizer_service import (
    ConversationSummarizerService,
    ConversationSummaryResult,
)


def test_summarize_messages_distinguishes_decisions_suggestions_actions_questions():
    service = ConversationSummarizerService()

    messages = [
        {
            "user": "U_AKSHAT",
            "text": "Can we finalize the database migration strategy for VPS?",
            "ts": "1600000001.000",
        },
        {
            "user": "U_HEMANT",
            "text": "Maybe we should run the migrations in dry-run mode first.",
            "ts": "1600000002.000",
        },
        {
            "user": "U_NAV",
            "text": "We decided to proceed with dry-run verification before deploying.",
            "ts": "1600000003.000",
        },
        {
            "user": "U_VIJAY",
            "text": "I will handle the webhook endpoint changes and test with Twilio.",
            "ts": "1600000004.000",
        },
        {
            "user": "U_AKSHAT",
            "text": "What about the rate limit retries?",
            "ts": "1600000005.000",
        },
    ]

    summary = service.summarize_messages(
        messages=messages,
        channel_name="#agentic-army",
        topic="database migration",
        time_window="today",
    )

    # 1. Decisions
    assert len(summary.confirmed_decisions) >= 1
    assert any("We decided to proceed" in d for d in summary.confirmed_decisions)

    # 2. Suggestions
    assert len(summary.suggestions) >= 1
    assert any("Maybe we should" in s for s in summary.suggestions)

    # 3. Action items & explicit owners
    assert len(summary.action_items) >= 1
    action = summary.action_items[0]
    assert "webhook endpoint" in action["task"]
    assert action["owner"] in ("U_VIJAY", "Vijay", "Vijay Sharma")

    # 4. Unresolved questions
    assert len(summary.unresolved_questions) >= 1
    assert any("rate limit retries" in q for q in summary.unresolved_questions)

    # 5. Formatted presentation check
    text = summary.formatted_text
    assert "Confirmed Decisions" in text
    assert "Suggestions & Ideas Considered" in text
    assert "Action Items & Owners" in text
    assert "Unresolved Questions" in text
    assert "#agentic-army" in text


def test_verify_channel_access_public_vs_private():
    mock_identity = MagicMock()
    mock_identity.get_conversation_members.return_value = {"U_AUTHORIZED"}

    service = ConversationSummarizerService(slack_identity_service=mock_identity)

    # Public channel allowed
    assert service.verify_channel_access(channel_id="C0BG7NWMD6D", user_id="U_ANY", channel_type="public") is True

    # Private channel allows member
    assert service.verify_channel_access(channel_id="G0123456", user_id="U_AUTHORIZED", channel_type="private") is True

    # Private channel rejects non-member (fails closed)
    assert service.verify_channel_access(channel_id="G0123456", user_id="U_UNAUTHORIZED", channel_type="private") is False

    # DM channel allows member
    assert service.verify_channel_access(channel_id="D0123456", user_id="U_AUTHORIZED", channel_type="im") is True

    # Missing user id fails closed
    assert service.verify_channel_access(channel_id="C0BG7NWMD6D", user_id="", channel_type="public") is False


def test_execute_private_summary_workflow_delivers_dm():
    mock_slack = MagicMock()
    mock_slack.get_all_channel_messages.return_value = [
        {"user": "U1", "text": "We decided on Python 3.11", "ts": "100.0"},
    ]
    mock_slack.send_dm.return_value = "D_DM_CHANNEL"

    mock_identity = MagicMock()
    mock_identity.get_conversation_members.return_value = {"U_REQ"}

    service = ConversationSummarizerService(
        slack_client=mock_slack,
        slack_identity_service=mock_identity,
    )

    result = service.execute_private_summary_workflow(
        channel_id="C_PUBLIC",
        requesting_user_id="U_REQ",
        channel_name="#general",
        send_private_dm=True,
    )

    assert result.delivered_privately is True
    assert result.delivery_channel_id == "D_DM_CHANNEL"
    mock_slack.send_dm.assert_called_once_with(
        user_id="U_REQ",
        text=result.formatted_text,
    )


def test_execute_private_summary_unauthorized_fails_closed():
    mock_identity = MagicMock()
    mock_identity.get_conversation_members.return_value = {"U_OTHER"}

    service = ConversationSummarizerService(slack_identity_service=mock_identity)

    with pytest.raises(PermissionError):
        service.execute_private_summary_workflow(
            channel_id="G_PRIVATE",
            requesting_user_id="U_ATTACKER",
            send_private_dm=True,
        )
