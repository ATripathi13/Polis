from dataclasses import FrozenInstanceError

import pytest

from engines.communication.domain.value_objects.content import Content


def test_create_content():

    content = Content(
        body="Hello Polis",
    )

    assert content.body == "Hello Polis"


def test_title():

    content = Content(
        title="Sprint Planning",
        body="Let's begin.",
    )

    assert content.title == "Sprint Planning"


def test_summary():

    content = Content(
        body="Meeting Transcript",
        summary="Planning Meeting",
    )

    assert content.summary == "Planning Meeting"


def test_empty_body():

    with pytest.raises(ValueError):
        Content(
            body="",
        )


def test_immutable():

    content = Content(
        body="Hello",
    )

    with pytest.raises(FrozenInstanceError):
        content.body = "Changed"