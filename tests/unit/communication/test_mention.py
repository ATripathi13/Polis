from engines.communication.domain.value_objects import (
    Mention,
    CommunicationIdentity,
)


def test_create_mention():

    mention = Mention(
        identity=CommunicationIdentity(
            internal_id="BOT001",
        ),
        display_name="Polis",
    )

    assert mention.display_name == "Polis"