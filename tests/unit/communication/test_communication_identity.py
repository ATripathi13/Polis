from dataclasses import FrozenInstanceError

import pytest

from engines.communication.domain.value_objects.communication_identity import (
    CommunicationIdentity,
)


def test_create_identity():

    identity = CommunicationIdentity(
        internal_id="POLIS-000001",
    )

    assert identity.internal_id == "POLIS-000001"


def test_external_ids():

    identity = CommunicationIdentity(
        internal_id="POLIS-000001",
        external_ids={
            "slack": "U12345",
            "github": "octocat",
        },
    )

    assert identity.external_ids["slack"] == "U12345"


def test_metadata():

    identity = CommunicationIdentity(
        internal_id="POLIS-000001",
        metadata={
            "verified": True,
        },
    )

    assert identity.metadata["verified"] is True


def test_empty_internal_id():

    with pytest.raises(ValueError):
        CommunicationIdentity(
            internal_id="",
        )


def test_immutable():

    identity = CommunicationIdentity(
        internal_id="POLIS-000001",
    )

    with pytest.raises(FrozenInstanceError):
        identity.internal_id = "NEW"