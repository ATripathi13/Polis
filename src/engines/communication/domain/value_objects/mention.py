"""
Represents a user or bot mentioned in a communication.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.common.value_object import ValueObject

from .communication_identity import CommunicationIdentity


@dataclass(frozen=True, slots=True)
class Mention(ValueObject):
    """
    A normalized mention.
    """

    identity: CommunicationIdentity

    display_name: str