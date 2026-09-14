"""
Repository interface for Microsoft Teams Graph subscriptions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..entities import TeamsSubscription


class TeamsSubscriptionRepository(ABC):
    """
    Repository interface for Teams Graph subscription state.
    """

    @abstractmethod
    def save(
        self,
        subscription: TeamsSubscription,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def find_active(self) -> TeamsSubscription | None:
        raise NotImplementedError

    @abstractmethod
    def delete(
        self,
        subscription_id: str,
    ) -> None:
        raise NotImplementedError