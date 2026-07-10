from dataclasses import FrozenInstanceError

import pytest

from engines.communication.domain.value_objects.channel import Channel
from engines.communication.domain.value_objects.communication_identity import (
    CommunicationIdentity,
)


def test_create_channel():

    channel = Channel(
        identity=CommunicationIdentity(
            internal_id="CHANNEL-001",
        ),
        name="general",
        channel_type="public",
    )

    assert channel.name == "general"


def test_channel_type():

    channel = Channel(
        identity=CommunicationIdentity(
            internal_id="CHANNEL-001",
        ),
        name="engineering",
        channel_type="private",
    )

    assert channel.channel_type == "private"


def test_empty_name():

    with pytest.raises(ValueError):
        Channel(
            identity=CommunicationIdentity(
                internal_id="CHANNEL-001",
            ),
            name="",
            channel_type="public",
        )


def test_immutable():

    channel = Channel(
        identity=CommunicationIdentity(
            internal_id="CHANNEL-001",
        ),
        name="general",
        channel_type="public",
    )

    with pytest.raises(FrozenInstanceError):
        channel.name = "sales"