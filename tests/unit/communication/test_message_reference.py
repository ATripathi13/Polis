from dataclasses import FrozenInstanceError

import pytest

from engines.communication.domain.value_objects.message_reference import (
    MessageReference,
)


def test_create_reference():

    reference = MessageReference(
        reference_id="MSG-001",
        relationship_type="THREAD",
        source="slack",
    )

    assert reference.reference_id == "MSG-001"


def test_relationship():

    reference = MessageReference(
        reference_id="MSG-001",
        relationship_type="REPLY_TO",
        source="gmail",
    )

    assert reference.relationship_type == "REPLY_TO"


def test_empty_reference():

    with pytest.raises(ValueError):
        MessageReference(
            reference_id="",
            relationship_type="THREAD",
            source="slack",
        )


def test_immutable():

    reference = MessageReference(
        reference_id="MSG-001",
        relationship_type="THREAD",
        source="slack",
    )

    with pytest.raises(FrozenInstanceError):
        reference.reference_id = "MSG-002"