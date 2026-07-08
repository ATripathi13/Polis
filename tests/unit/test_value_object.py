from dataclasses import FrozenInstanceError

import pytest

from domain.common.value_object import ValueObject


from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class DummyValue(ValueObject):
    value: str = "hello"


def test_value_object_equality() -> None:
    a = DummyValue()
    b = DummyValue()

    assert a == b


def test_value_object_is_immutable() -> None:
    value = DummyValue()

    with pytest.raises(FrozenInstanceError):
        value.value = "changed"