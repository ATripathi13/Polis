"""
Domain event raised when a communication
has been created.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.common.event import DomainEvent

from domain.common.identifier import Identifier


@dataclass(frozen=True, slots=True)
class CommunicationCreatedEvent(DomainEvent):
    """
    Raised after a CommunicationEvent
    has been created.
    """

    communication_id: Identifier