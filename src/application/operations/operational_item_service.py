"""
Application service for operational intelligence.
"""

from __future__ import annotations

from datetime import datetime, timezone

from domain.organization import (
    OrganizationEvent,
    OrganizationEventType,
)
from domain.operations import (
    OperationalItem,
    OperationalItemPriority,
    OperationalItemStatus,
    OperationalItemType,
    OperationalItemRepository,
)


class OperationalItemService:
    """
    Converts operational organization events into
    persistent operational items.
    """

    _EVENT_TYPE_MAPPING = {
        OrganizationEventType.TASK_CREATED: OperationalItemType.TASK,
        OrganizationEventType.DECISION_MADE: OperationalItemType.DECISION,
        OrganizationEventType.RISK_IDENTIFIED: OperationalItemType.RISK,
    }

    def __init__(
        self,
        repository: OperationalItemRepository,
    ) -> None:
        self._repository = repository

    def process_event(
        self,
        event: OrganizationEvent,
        *,
        source_type: str = "",
    ) -> OperationalItem | None:
        item_type = self._EVENT_TYPE_MAPPING.get(
            event.event_type
        )

        if item_type is None:
            return None

        source_event_id = ""
        if event.observations:
            evidence = event.observations[0].evidence
            if evidence:
                source_event_id = evidence[0]

        if source_event_id:
            existing = self._repository.find_by_source_event(
                source_type,
                source_event_id,
                item_type,
            )
            if existing is not None:
                return existing

        item = OperationalItem.create(
            item_type=item_type,
            summary=event.summary,
            status=OperationalItemStatus.OPEN,
            priority=OperationalItemPriority.MEDIUM,
            source_event_id=source_event_id,
            source_type=source_type,
            confidence=event.confidence,
            evidence=[
                evidence
                for observation in event.observations
                for evidence in observation.evidence
            ],
        )

        return self._repository.save(item)


    def retrieve_evidence(self, question) -> list[str]:
        """
        Retrieve operational evidence relevant to a user question.
        """

        normalized = " ".join(
            question.text.lower().strip().split()
        )

        if any(
            phrase in normalized
            for phrase in (
                "overdue",
                "past due",
                "late task",
                "late tasks",
            )
        ):
            items = self._repository.find_overdue(
                datetime.now(timezone.utc)
            )

        elif any(
            word in normalized
            for word in (
                "decision",
                "decisions",
                "decided",
                "approved",
                "approval",
            )
        ):
            items = self._repository.find_open(
                item_type=OperationalItemType.DECISION,
            )

        elif any(
            word in normalized
            for word in (
                "risk",
                "risks",
                "blocker",
                "blockers",
                "issue",
                "issues",
                "threat",
            )
        ):
            items = self._repository.find_open(
                item_type=OperationalItemType.RISK,
            )

        elif any(
            word in normalized
            for word in (
                "task",
                "tasks",
                "todo",
                "to-do",
                "action",
                "actions",
                "work to do",
                "what needs to be done",
            )
        ):
            items = self._repository.find_open(
                item_type=OperationalItemType.TASK,
            )

        else:
            return []

        evidence = []

        for item in items:
            evidence.append(
                (
                    f"Operational item: {item.item_type.value}\n"
                    f"Summary: {item.summary}\n"
                    f"Status: {item.status.value}\n"
                    f"Priority: {item.priority.value}"
                )
            )

        return evidence
