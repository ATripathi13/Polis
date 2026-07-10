from dataclasses import FrozenInstanceError

import pytest

from engines.communication.domain.value_objects.actor import Actor
from engines.communication.domain.value_objects.communication_identity import (
    CommunicationIdentity,
)


def test_create_actor():

    actor = Actor(
        identity=CommunicationIdentity(
            internal_id="POLIS-001",
        ),
        display_name="John Doe",
    )

    assert actor.display_name == "John Doe"


def test_email():

    actor = Actor(
        identity=CommunicationIdentity(
            internal_id="POLIS-001",
        ),
        display_name="John Doe",
        email="john@example.com",
    )

    assert actor.email == "john@example.com"


def test_empty_display_name():

    with pytest.raises(ValueError):
        Actor(
            identity=CommunicationIdentity(
                internal_id="POLIS-001",
            ),
            display_name="",
        )


def test_immutable():

    actor = Actor(
        identity=CommunicationIdentity(
            internal_id="POLIS-001",
        ),
        display_name="John",
    )

    with pytest.raises(FrozenInstanceError):
        actor.display_name = "Jane"