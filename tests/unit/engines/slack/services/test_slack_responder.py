from unittest.mock import MagicMock

from engines.slack.services.slack_responder import SlackResponder


def test_markdown_bold_converts_to_slack_bold():
    assert SlackResponder._format_for_slack(
        "**Employee:** Hemant Kumar Sah"
    ) == "*Employee:* Hemant Kumar Sah"


def test_markdown_strikethrough_converts_to_slack_format():
    assert SlackResponder._format_for_slack("~~old value~~") == "~old value~"


def test_markdown_links_convert_to_slack_links():
    assert SlackResponder._format_for_slack(
        "[POLIS](https://example.com)"
    ) == "<https://example.com|POLIS>"


def test_code_blocks_and_inline_code_are_preserved():
    message = "Use `**bold**`\\n```python\\nvalue = '**text**'\\n```"
    assert SlackResponder._format_for_slack(message) == message


def test_reply_sends_formatted_text_to_slack():
    client = MagicMock()
    responder = SlackResponder(client)

    responder.reply(
        channel="C123",
        thread_ts="123.456",
        text="**Employee:** Hemant Kumar Sah",
    )

    client.post_message.assert_called_once_with(
        channel="C123",
        text="*Employee:* Hemant Kumar Sah",
        thread_ts="123.456",
    )
