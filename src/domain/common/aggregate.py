"""
Aggregate Root for the Polis Domain.
"""

from __future__ import annotations

from abc import ABC

from domain.common.entity import Entity


class AggregateRoot(Entity, ABC):
    """
    Base class for aggregate roots.

    Aggregate roots are the only entry points
    for modifying an aggregate.
    """

    pass