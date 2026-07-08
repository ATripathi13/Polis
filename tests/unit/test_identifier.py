from dataclasses import FrozenInstanceError

import pytest

from domain.common.identifier import Identifier


def test_identifier_is_immutable() -> None:
    identifier = Identifier()

    with pytest.raises(FrozenInstanceError):
        identifier.business_id = "TASK-001"