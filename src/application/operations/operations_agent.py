"""
Operations Agent specialist intelligence implementation for POLIS.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from domain.common.identifier import Identifier
from domain.operations import (
    OperationalItem,
    OperationalItemPriority,
    OperationalItemRepository,
    OperationalItemStatus,
    OperationalItemType,
    OperationsResult,
    InvalidLifecycleTransitionError,
    OperationalItemNotFoundError,
    UnsupportedOperationalEventError,
)
from domain.organization import (
    OrganizationEvent,
    OrganizationEventType,
)
from domain.reasoning import Question
from application.operations.operational_item_service import OperationalItemService

logger = logging.getLogger(__name__)


class OperationsAgent:
    """
    Specialist agent responsible for organizational operational intelligence.
    
    Coordinates TASK, DECISION, and RISK lifecycles, state transitions,
    idempotency, source event provenance, correlation, overdue tracking,
    and reminder integration behind POLIS.
    """

    # Domain state transition tables
    _TASK_TRANSITIONS: dict[OperationalItemStatus, set[OperationalItemStatus]] = {
        OperationalItemStatus.OPEN: {
            OperationalItemStatus.IN_PROGRESS,
            OperationalItemStatus.COMPLETED,
            OperationalItemStatus.CANCELLED,
            OperationalItemStatus.CLOSED,
        },
        OperationalItemStatus.IN_PROGRESS: {
            OperationalItemStatus.OPEN,
            OperationalItemStatus.COMPLETED,
            OperationalItemStatus.CANCELLED,
            OperationalItemStatus.CLOSED,
        },
        OperationalItemStatus.COMPLETED: {
            OperationalItemStatus.OPEN,  # Reopening
            OperationalItemStatus.CLOSED,
        },
        OperationalItemStatus.CANCELLED: {
            OperationalItemStatus.OPEN,  # Reopening
            OperationalItemStatus.CLOSED,
        },
        OperationalItemStatus.CLOSED: {
            OperationalItemStatus.OPEN,  # Reopening
        },
    }

    _DECISION_TRANSITIONS: dict[OperationalItemStatus, set[OperationalItemStatus]] = {
        OperationalItemStatus.OPEN: {
            OperationalItemStatus.ACCEPTED,
            OperationalItemStatus.COMPLETED,
            OperationalItemStatus.SUPERSEDED,
            OperationalItemStatus.CLOSED,
            OperationalItemStatus.CANCELLED,
        },
        OperationalItemStatus.ACCEPTED: {
            OperationalItemStatus.SUPERSEDED,
            OperationalItemStatus.CLOSED,
            OperationalItemStatus.COMPLETED,
        },
        OperationalItemStatus.COMPLETED: {
            OperationalItemStatus.SUPERSEDED,
            OperationalItemStatus.CLOSED,
        },
        OperationalItemStatus.SUPERSEDED: {
            OperationalItemStatus.CLOSED,
        },
        OperationalItemStatus.CLOSED: set(),
    }

    _RISK_TRANSITIONS: dict[OperationalItemStatus, set[OperationalItemStatus]] = {
        OperationalItemStatus.OPEN: {
            OperationalItemStatus.IN_PROGRESS,
            OperationalItemStatus.MITIGATED,
            OperationalItemStatus.ACCEPTED,
            OperationalItemStatus.CLOSED,
        },
        OperationalItemStatus.IN_PROGRESS: {
            OperationalItemStatus.MITIGATED,
            OperationalItemStatus.ACCEPTED,
            OperationalItemStatus.CLOSED,
            OperationalItemStatus.OPEN,
        },
        OperationalItemStatus.MITIGATED: {
            OperationalItemStatus.CLOSED,
            OperationalItemStatus.OPEN,  # Re-emergence of risk
        },
        OperationalItemStatus.ACCEPTED: {
            OperationalItemStatus.CLOSED,
            OperationalItemStatus.OPEN,
        },
        OperationalItemStatus.CLOSED: {
            OperationalItemStatus.OPEN,  # Reopening
        },
    }

    def __init__(
        self,
        repository: OperationalItemRepository,
        operational_item_service: OperationalItemService | None = None,
        reminder_service: Any | None = None,
    ) -> None:
        self._repository = repository
        self._service = (
            operational_item_service
            if operational_item_service is not None
            else OperationalItemService(repository)
        )
        self._reminder_service = reminder_service

    # =========================================================================
    # EVENT DISPATCH & LIFECYCLE MANAGEMENT
    # =========================================================================

    def process_event(
        self,
        event: OrganizationEvent,
        *,
        source_type: str = "",
        source_event_id: str = "",
        correlation_id: str | None = None,
        raise_on_unsupported: bool = False,
    ) -> OperationsResult:
        """
        Process an organizational event and produce a structured OperationsResult.
        """
        if not self._is_operational_event(event.event_type):
            if raise_on_unsupported:
                raise UnsupportedOperationalEventError(
                    f"Event type '{event.event_type.value}' is not an operational event."
                )
            return OperationsResult(
                event_type=event.event_type,
                operation="ignored",
                item=None,
                idempotent=True,
                warnings=[f"Event type '{event.event_type.value}' is not an operational event."],
            )

        # 1. Resolve source and correlation identity
        canonical_source_id = source_event_id
        if not canonical_source_id:
            for obs in event.observations:
                for ev in obs.evidence:
                    if ev and ev.strip():
                        canonical_source_id = ev.strip()
                        break
                if canonical_source_id:
                    break

        canonical_source = source_type
        if not canonical_source and event.observations:
            for obs in event.observations:
                meta = getattr(obs, "metadata", {}) or {}
                if "source_type" in meta:
                    canonical_source = str(meta["source_type"]).strip()
                    break

        correlation_id_str = correlation_id
        if not correlation_id_str and event.correlation_id is not None:
            if hasattr(event.correlation_id, "business_id") and event.correlation_id.business_id:
                correlation_id_str = event.correlation_id.business_id
            elif hasattr(event.correlation_id, "graph_id") and event.correlation_id.graph_id:
                correlation_id_str = str(event.correlation_id.graph_id)
            else:
                correlation_id_str = str(event.correlation_id)

        item_id_hint = None
        for obs in event.observations:
            meta = getattr(obs, "metadata", {}) or {}
            for key in ("item_id", "target_item_id", "task_id", "risk_id", "decision_id"):
                if key in meta and meta[key]:
                    item_id_hint = str(meta[key]).strip()
                    break
            if item_id_hint:
                break

        # 2. Dispatch to specific operational handlers
        if event.event_type == OrganizationEventType.TASK_CREATED:
            return self._handle_task_created(
                event,
                source_type=canonical_source,
                source_event_id=canonical_source_id,
                correlation_id=correlation_id_str,
                item_id_hint=item_id_hint,
            )

        if event.event_type == OrganizationEventType.TASK_UPDATED:
            return self._handle_task_updated(
                event,
                source_type=canonical_source,
                source_event_id=canonical_source_id,
                correlation_id=correlation_id_str,
                item_id_hint=item_id_hint,
            )

        if event.event_type == OrganizationEventType.TASK_COMPLETED:
            return self._handle_task_completed(
                event,
                source_type=canonical_source,
                source_event_id=canonical_source_id,
                correlation_id=correlation_id_str,
                item_id_hint=item_id_hint,
            )

        if event.event_type == OrganizationEventType.DECISION_MADE:
            return self._handle_decision_made(
                event,
                source_type=canonical_source,
                source_event_id=canonical_source_id,
                correlation_id=correlation_id_str,
                item_id_hint=item_id_hint,
            )

        if event.event_type == OrganizationEventType.RISK_IDENTIFIED:
            return self._handle_risk_identified(
                event,
                source_type=canonical_source,
                source_event_id=canonical_source_id,
                correlation_id=correlation_id_str,
                item_id_hint=item_id_hint,
            )

        return OperationsResult(
            event_type=event.event_type,
            operation="ignored",
            warnings=[f"Unhandled operational event: {event.event_type}"],
        )

    # =========================================================================
    # TASK LIFECYCLE
    # =========================================================================

    def _handle_task_created(
        self,
        event: OrganizationEvent,
        *,
        source_type: str,
        source_event_id: str,
        correlation_id: str | None,
        item_id_hint: str | None,
    ) -> OperationsResult:
        # Idempotency check: see if task with same source_event or hint exists
        existing = self._find_existing_item(
            item_id=item_id_hint,
            source_type=source_type,
            source_event_id=source_event_id,
            item_type=OperationalItemType.TASK,
            correlation_id=correlation_id,
        )

        if existing is not None:
            return OperationsResult(
                event_type=event.event_type,
                operation="no_op",
                item=existing,
                status=existing.status,
                idempotent=True,
                affected_item_id=str(existing.identifier.graph_id),
                is_overdue=self._is_overdue(existing),
                correlation_id=correlation_id,
            )

        # Extract parameters
        owner_id, owner_name = self._extract_owner(event)
        priority = self._extract_priority(event, default=OperationalItemPriority.MEDIUM)
        due_at = self._extract_due_date(event)

        metadata: dict[str, Any] = {}
        if correlation_id:
            metadata["correlation_id"] = correlation_id
        if event.occurred_at:
            metadata["occurred_at"] = event.occurred_at.isoformat()

        for obs in event.observations:
            meta = getattr(obs, "metadata", {}) or {}
            metadata.update(meta)

        status = OperationalItemStatus.OPEN
        meta_status = metadata.get("status")
        if meta_status and meta_status.lower() in ("in_progress", "in progress"):
            status = OperationalItemStatus.IN_PROGRESS

        task = OperationalItem.create(
            item_type=OperationalItemType.TASK,
            summary=event.summary,
            status=status,
            priority=priority,
            owner_id=owner_id,
            owner_name=owner_name,
            due_at=due_at,
            source_event_id=source_event_id,
            source_type=source_type,
            confidence=event.confidence,
            evidence=[
                ev
                for obs in event.observations
                for ev in obs.evidence
                if ev
            ],
            metadata=metadata,
        )

        saved = self._repository.save(task)

        # Reminder trigger if requested in metadata
        if self._reminder_service is not None and metadata.get("create_reminder"):
            self._trigger_reminder(saved, metadata)

        return OperationsResult(
            event_type=event.event_type,
            operation="created",
            item=saved,
            status=saved.status,
            idempotent=False,
            affected_item_id=str(saved.identifier.graph_id),
            is_overdue=self._is_overdue(saved),
            correlation_id=correlation_id,
        )

    def _handle_task_updated(
        self,
        event: OrganizationEvent,
        *,
        source_type: str,
        source_event_id: str,
        correlation_id: str | None,
        item_id_hint: str | None,
    ) -> OperationsResult:
        existing = self._find_existing_item(
            item_id=item_id_hint,
            source_type=source_type,
            source_event_id=source_event_id,
            item_type=OperationalItemType.TASK,
            correlation_id=correlation_id,
        )

        if existing is None:
            if item_id_hint:
                raise OperationalItemNotFoundError(
                    f"Referenced operational task '{item_id_hint}' was not found for update."
                )
            # If item not found, treat as creation with updated status
            return self._handle_task_created(
                event,
                source_type=source_type,
                source_event_id=source_event_id,
                correlation_id=correlation_id,
                item_id_hint=item_id_hint,
            )

        # Parse target status from event
        target_status = existing.status
        meta = self._merge_event_metadata(event)
        explicit_status = meta.get("status", "") or meta.get("action", "")
        if explicit_status:
            parsed = self._parse_status(explicit_status)
            if parsed is not None:
                target_status = parsed
        elif existing.status == OperationalItemStatus.OPEN:
            target_status = OperationalItemStatus.IN_PROGRESS

        # Validate transition
        if target_status != existing.status:
            self.validate_transition(
                existing.status,
                target_status,
                OperationalItemType.TASK,
            )

        # Check if identical (idempotency)
        summary_changed = event.summary and event.summary != existing.summary
        status_changed = target_status != existing.status
        priority = self._extract_priority(event, default=existing.priority)
        priority_changed = priority != existing.priority

        if not summary_changed and not status_changed and not priority_changed:
            return OperationsResult(
                event_type=event.event_type,
                operation="no_op",
                item=existing,
                status=existing.status,
                idempotent=True,
                affected_item_id=str(existing.identifier.graph_id),
                is_overdue=self._is_overdue(existing),
                correlation_id=correlation_id,
            )

        # Apply updates
        existing.status = target_status
        if summary_changed:
            existing.summary = event.summary
        existing.priority = priority

        owner_id, owner_name = self._extract_owner(event)
        if owner_id:
            existing.owner_id = owner_id
        if owner_name:
            existing.owner_name = owner_name

        due_at = self._extract_due_date(event)
        if due_at is not None:
            existing.due_at = due_at

        # Append new evidence from observations
        new_evidence = [
            ev
            for obs in event.observations
            for ev in obs.evidence
            if ev and ev not in existing.evidence
        ]
        if new_evidence:
            existing.evidence = list(existing.evidence) + new_evidence

        existing.touch()
        saved = self._repository.save(existing)

        return OperationsResult(
            event_type=event.event_type,
            operation="updated",
            item=saved,
            status=saved.status,
            idempotent=False,
            affected_item_id=str(saved.identifier.graph_id),
            is_overdue=self._is_overdue(saved),
            correlation_id=correlation_id,
        )

    def _handle_task_completed(
        self,
        event: OrganizationEvent,
        *,
        source_type: str,
        source_event_id: str,
        correlation_id: str | None,
        item_id_hint: str | None,
    ) -> OperationsResult:
        existing = self._find_existing_item(
            item_id=item_id_hint,
            source_type=source_type,
            source_event_id=source_event_id,
            item_type=OperationalItemType.TASK,
            correlation_id=correlation_id,
        )

        if existing is not None:
            if existing.status == OperationalItemStatus.COMPLETED:
                return OperationsResult(
                    event_type=event.event_type,
                    operation="no_op",
                    item=existing,
                    status=OperationalItemStatus.COMPLETED,
                    idempotent=True,
                    affected_item_id=str(existing.identifier.graph_id),
                    correlation_id=correlation_id,
                )

            self.validate_transition(
                existing.status,
                OperationalItemStatus.COMPLETED,
                OperationalItemType.TASK,
            )

            existing.status = OperationalItemStatus.COMPLETED
            existing.touch()
            saved = self._repository.save(existing)

            return OperationsResult(
                event_type=event.event_type,
                operation="completed",
                item=saved,
                status=OperationalItemStatus.COMPLETED,
                idempotent=False,
                affected_item_id=str(saved.identifier.graph_id),
                correlation_id=correlation_id,
            )

        if existing is None and item_id_hint:
            raise OperationalItemNotFoundError(
                f"Referenced operational task '{item_id_hint}' was not found for completion."
            )

        # Fallback: create task directly in completed state
        owner_id, owner_name = self._extract_owner(event)
        metadata: dict[str, Any] = {}
        if correlation_id:
            metadata["correlation_id"] = correlation_id

        task = OperationalItem.create(
            item_type=OperationalItemType.TASK,
            summary=event.summary,
            status=OperationalItemStatus.COMPLETED,
            priority=self._extract_priority(event, default=OperationalItemPriority.MEDIUM),
            owner_id=owner_id,
            owner_name=owner_name,
            source_event_id=source_event_id,
            source_type=source_type,
            confidence=event.confidence,
            evidence=[
                ev
                for obs in event.observations
                for ev in obs.evidence
                if ev
            ],
            metadata=metadata,
        )
        saved = self._repository.save(task)

        return OperationsResult(
            event_type=event.event_type,
            operation="completed",
            item=saved,
            status=OperationalItemStatus.COMPLETED,
            idempotent=False,
            affected_item_id=str(saved.identifier.graph_id),
            correlation_id=correlation_id,
        )

    # =========================================================================
    # DECISION LIFECYCLE
    # =========================================================================

    def _handle_decision_made(
        self,
        event: OrganizationEvent,
        *,
        source_type: str,
        source_event_id: str,
        correlation_id: str | None,
        item_id_hint: str | None,
    ) -> OperationsResult:
        existing = self._find_existing_item(
            item_id=item_id_hint,
            source_type=source_type,
            source_event_id=source_event_id,
            item_type=OperationalItemType.DECISION,
            correlation_id=correlation_id,
        )

        if existing is not None:
            if existing.summary.strip().lower() == event.summary.strip().lower():
                return OperationsResult(
                    event_type=event.event_type,
                    operation="no_op",
                    item=existing,
                    status=existing.status,
                    idempotent=True,
                    affected_item_id=str(existing.identifier.graph_id),
                    correlation_id=correlation_id,
                )

            # Supersede previous decision if specified
            meta = self._merge_event_metadata(event)
            if meta.get("supersedes") or meta.get("action") == "supersede":
                self.validate_transition(
                    existing.status,
                    OperationalItemStatus.SUPERSEDED,
                    OperationalItemType.DECISION,
                )
                existing.status = OperationalItemStatus.SUPERSEDED
                existing.touch()
                self._repository.save(existing)

        meta = self._merge_event_metadata(event)
        initial_status = OperationalItemStatus.OPEN
        if meta.get("status") in ("accepted", "approved") or meta.get("approved"):
            initial_status = OperationalItemStatus.ACCEPTED

        metadata: dict[str, Any] = {"correlation_id": correlation_id} if correlation_id else {}
        metadata.update(meta)

        owner_id, owner_name = self._extract_owner(event)
        decision = OperationalItem.create(
            item_type=OperationalItemType.DECISION,
            summary=event.summary,
            status=initial_status,
            priority=self._extract_priority(event, default=OperationalItemPriority.HIGH),
            owner_id=owner_id,
            owner_name=owner_name,
            source_event_id=source_event_id,
            source_type=source_type,
            confidence=event.confidence,
            evidence=[
                ev
                for obs in event.observations
                for ev in obs.evidence
                if ev
            ],
            metadata=metadata,
        )

        saved = self._repository.save(decision)

        return OperationsResult(
            event_type=event.event_type,
            operation="created",
            item=saved,
            status=saved.status,
            idempotent=False,
            affected_item_id=str(saved.identifier.graph_id),
            correlation_id=correlation_id,
        )

    # =========================================================================
    # RISK LIFECYCLE
    # =========================================================================

    def _handle_risk_identified(
        self,
        event: OrganizationEvent,
        *,
        source_type: str,
        source_event_id: str,
        correlation_id: str | None,
        item_id_hint: str | None,
    ) -> OperationsResult:
        existing = self._find_existing_item(
            item_id=item_id_hint,
            source_type=source_type,
            source_event_id=source_event_id,
            item_type=OperationalItemType.RISK,
            correlation_id=correlation_id,
        )

        meta = self._merge_event_metadata(event)

        if existing is None and item_id_hint:
            raise OperationalItemNotFoundError(
                f"Referenced operational risk '{item_id_hint}' was not found."
            )

        if existing is not None:
            action = str(meta.get("action", "") or meta.get("lifecycle", "") or meta.get("status", "")).lower()

            if action in ("in_progress", "working"):
                self.validate_transition(
                    existing.status,
                    OperationalItemStatus.IN_PROGRESS,
                    OperationalItemType.RISK,
                )
                existing.status = OperationalItemStatus.IN_PROGRESS
                existing.touch()
                saved = self._repository.save(existing)
                return OperationsResult(
                    event_type=event.event_type,
                    operation="transitioned",
                    item=saved,
                    status=saved.status,
                    idempotent=False,
                    affected_item_id=str(saved.identifier.graph_id),
                    correlation_id=correlation_id,
                )

            if action in ("mitigate", "mitigated"):
                self.validate_transition(
                    existing.status,
                    OperationalItemStatus.MITIGATED,
                    OperationalItemType.RISK,
                )
                existing.status = OperationalItemStatus.MITIGATED
                existing.touch()
                saved = self._repository.save(existing)
                return OperationsResult(
                    event_type=event.event_type,
                    operation="transitioned",
                    item=saved,
                    status=saved.status,
                    idempotent=False,
                    affected_item_id=str(saved.identifier.graph_id),
                    correlation_id=correlation_id,
                )

            if action in ("accept", "accepted"):
                self.validate_transition(
                    existing.status,
                    OperationalItemStatus.ACCEPTED,
                    OperationalItemType.RISK,
                )
                existing.status = OperationalItemStatus.ACCEPTED
                existing.touch()
                saved = self._repository.save(existing)
                return OperationsResult(
                    event_type=event.event_type,
                    operation="transitioned",
                    item=saved,
                    status=saved.status,
                    idempotent=False,
                    affected_item_id=str(saved.identifier.graph_id),
                    correlation_id=correlation_id,
                )

            if action in ("close", "closed"):
                self.validate_transition(
                    existing.status,
                    OperationalItemStatus.CLOSED,
                    OperationalItemType.RISK,
                )
                existing.status = OperationalItemStatus.CLOSED
                existing.touch()
                saved = self._repository.save(existing)
                return OperationsResult(
                    event_type=event.event_type,
                    operation="transitioned",
                    item=saved,
                    status=saved.status,
                    idempotent=False,
                    affected_item_id=str(saved.identifier.graph_id),
                    correlation_id=correlation_id,
                )

            if existing.summary.strip().lower() == event.summary.strip().lower():
                return OperationsResult(
                    event_type=event.event_type,
                    operation="no_op",
                    item=existing,
                    status=existing.status,
                    idempotent=True,
                    affected_item_id=str(existing.identifier.graph_id),
                    correlation_id=correlation_id,
                )

        priority = self._extract_priority(event, default=OperationalItemPriority.HIGH)
        owner_id, owner_name = self._extract_owner(event)

        metadata: dict[str, Any] = {"correlation_id": correlation_id} if correlation_id else {}
        metadata.update(meta)

        risk = OperationalItem.create(
            item_type=OperationalItemType.RISK,
            summary=event.summary,
            status=OperationalItemStatus.OPEN,
            priority=priority,
            owner_id=owner_id,
            owner_name=owner_name,
            source_event_id=source_event_id,
            source_type=source_type,
            confidence=event.confidence,
            evidence=[
                ev
                for obs in event.observations
                for ev in obs.evidence
                if ev
            ],
            metadata=metadata,
        )

        saved = self._repository.save(risk)

        requires_action = priority in (
            OperationalItemPriority.HIGH,
            OperationalItemPriority.CRITICAL,
        )

        return OperationsResult(
            event_type=event.event_type,
            operation="created",
            item=saved,
            status=saved.status,
            idempotent=False,
            requires_action=requires_action,
            affected_item_id=str(saved.identifier.graph_id),
            correlation_id=correlation_id,
        )

    # =========================================================================
    # STATE TRANSITION VALIDATOR
    # =========================================================================

    def validate_transition(
        self,
        current_status: OperationalItemStatus,
        target_status: OperationalItemStatus,
        item_type: OperationalItemType,
    ) -> None:
        """
        Validate whether the lifecycle transition is allowed by domain rules.
        
        Raises InvalidLifecycleTransitionError if invalid.
        """
        if current_status == target_status:
            return

        table: dict[OperationalItemStatus, set[OperationalItemStatus]]
        if item_type == OperationalItemType.TASK:
            table = self._TASK_TRANSITIONS
        elif item_type == OperationalItemType.DECISION:
            table = self._DECISION_TRANSITIONS
        elif item_type == OperationalItemType.RISK:
            table = self._RISK_TRANSITIONS
        else:
            raise UnsupportedOperationalEventError(f"Unsupported item type: {item_type}")

        allowed = table.get(current_status, set())
        if target_status not in allowed:
            raise InvalidLifecycleTransitionError(
                f"Cannot transition {item_type.value} from '{current_status.value}' "
                f"to '{target_status.value}'. Allowed transitions: {[s.value for s in allowed]}."
            )

    # =========================================================================
    # QUERIES & EVIDENCE
    # =========================================================================

    def get_open_items(
        self,
        item_type: OperationalItemType | None = None,
        owner_id: str | None = None,
    ) -> list[OperationalItem]:
        """Return currently open operational items."""
        return self._repository.find_open(
            item_type=item_type,
            owner_id=owner_id,
        )

    def get_open_tasks(self, owner_id: str | None = None) -> list[OperationalItem]:
        """Return open tasks."""
        return self.get_open_items(
            item_type=OperationalItemType.TASK,
            owner_id=owner_id,
        )

    def get_open_decisions(self) -> list[OperationalItem]:
        """Return open decisions."""
        return self.get_open_items(item_type=OperationalItemType.DECISION)

    def get_open_risks(self) -> list[OperationalItem]:
        """Return active risks."""
        return self.get_open_items(item_type=OperationalItemType.RISK)

    def get_overdue_items(
        self,
        now: datetime | None = None,
    ) -> list[OperationalItem]:
        """Return overdue operational items."""
        check_time = now or datetime.now(timezone.utc)
        return self._repository.find_overdue(check_time)

    def get_item_by_id(self, item_id: str) -> OperationalItem | None:
        """Find an operational item by ID."""
        return self._repository.find_by_id(item_id)

    def retrieve_evidence(self, question: Question | str) -> list[str]:
        """
        Retrieve formatted operational evidence for POLIS question answering.
        """
        q = question if isinstance(question, Question) else Question(text=str(question))
        return self._service.retrieve_evidence(q)

    def ask(self, question: Question | str) -> dict[str, Any]:
        """
        Answer or query operational intelligence for a question.
        """
        q = question if isinstance(question, Question) else Question(text=str(question))
        evidence = self.retrieve_evidence(q)
        return {
            "question": q.text,
            "evidence": evidence,
            "summary": self.summarize_operational_state(),
        }

    def summarize_operational_state(self) -> dict[str, Any]:
        """
        Produce a high-level operational intelligence summary.
        """
        now = datetime.now(timezone.utc)
        open_tasks = self.get_open_tasks()
        overdue_tasks = self.get_overdue_items(now)
        open_decisions = self.get_open_decisions()
        open_risks = self.get_open_risks()

        critical_risks = [
            r for r in open_risks
            if r.priority in (OperationalItemPriority.HIGH, OperationalItemPriority.CRITICAL)
        ]

        return {
            "open_task_count": len(open_tasks),
            "overdue_task_count": len(overdue_tasks),
            "open_decision_count": len(open_decisions),
            "open_risk_count": len(open_risks),
            "critical_risk_count": len(critical_risks),
            "overdue_tasks": [t.summary for t in overdue_tasks],
            "critical_risks": [r.summary for r in critical_risks],
        }

    # =========================================================================
    # REMINDER INTEGRATION
    # =========================================================================

    def schedule_task_reminder(
        self,
        task_id: str,
        *,
        target_user_id: str,
        creator_user_id: str,
        channel_id: str,
        source_message_ts: str,
        source_thread_ts: str | None = None,
        timezone_name: str = "UTC",
        time_1: str = "09:00",
        time_2: str = "17:00",
    ) -> Any | None:
        """
        Schedule an explicit reminder for an operational task.
        """
        if self._reminder_service is None:
            logger.warning("Cannot schedule reminder: ReminderService is not configured.")
            return None

        task = self._repository.find_by_id(task_id)
        if task is None:
            raise OperationalItemNotFoundError(f"Task '{task_id}' not found.")

        return self._reminder_service.create(
            target_user_id=target_user_id,
            creator_user_id=creator_user_id,
            task=task.summary,
            channel_id=channel_id,
            source_message_ts=source_message_ts,
            source_thread_ts=source_thread_ts,
            timezone_name=timezone_name,
            time_1=time_1,
            time_2=time_2,
        )

    def _trigger_reminder(self, item: OperationalItem, meta: dict[str, Any]) -> None:
        try:
            target_user = meta.get("target_user_id") or meta.get("assignee") or item.owner_id
            creator_user = meta.get("creator_user_id") or target_user
            channel_id = meta.get("channel_id", "general")
            ts = meta.get("source_message_ts") or item.source_event_id or "0"

            if target_user:
                self._reminder_service.create(
                    target_user_id=target_user,
                    creator_user_id=creator_user,
                    task=item.summary,
                    channel_id=channel_id,
                    source_message_ts=ts,
                    source_thread_ts=meta.get("source_thread_ts"),
                    timezone_name=meta.get("timezone", "UTC"),
                    time_1=meta.get("time_1", "09:00"),
                    time_2=meta.get("time_2", "17:00"),
                )
        except Exception as e:
            logger.warning("Failed to auto-trigger reminder for item %s: %s", item.summary, e)

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _find_existing_item(
        self,
        *,
        item_id: str | None,
        source_type: str,
        source_event_id: str,
        item_type: OperationalItemType,
        correlation_id: str | None,
    ) -> OperationalItem | None:
        if item_id:
            found = self._repository.find_by_id(item_id)
            if found is not None:
                return found

        if source_event_id:
            found = self._repository.find_by_source_event(
                source_type,
                source_event_id,
                item_type,
            )
            if found is not None:
                return found

        if correlation_id:
            corr_matches = self._repository.find_by_correlation(
                correlation_id,
                item_type=item_type,
            )
            if corr_matches:
                return corr_matches[0]

        return None

    @staticmethod
    def _is_operational_event(event_type: OrganizationEventType) -> bool:
        return event_type in (
            OrganizationEventType.TASK_CREATED,
            OrganizationEventType.TASK_UPDATED,
            OrganizationEventType.TASK_COMPLETED,
            OrganizationEventType.DECISION_MADE,
            OrganizationEventType.RISK_IDENTIFIED,
        )

    @staticmethod
    def _extract_owner(event: OrganizationEvent) -> tuple[str, str]:
        for obs in event.observations:
            meta = getattr(obs, "metadata", {}) or {}
            owner_id = str(meta.get("owner_id") or meta.get("assignee") or meta.get("user_id") or "").strip()
            owner_name = str(meta.get("owner_name") or meta.get("assignee_name") or "").strip()
            if owner_id or owner_name:
                return owner_id, owner_name
        return "", ""

    @staticmethod
    def _extract_priority(
        event: OrganizationEvent,
        *,
        default: OperationalItemPriority,
    ) -> OperationalItemPriority:
        for obs in event.observations:
            meta = getattr(obs, "metadata", {}) or {}
            raw = str(meta.get("priority", "") or meta.get("severity", "")).lower().strip()
            if raw == "low":
                return OperationalItemPriority.LOW
            if raw == "medium":
                return OperationalItemPriority.MEDIUM
            if raw == "high":
                return OperationalItemPriority.HIGH
            if raw == "critical":
                return OperationalItemPriority.CRITICAL
        return default

    @staticmethod
    def _extract_due_date(event: OrganizationEvent) -> datetime | None:
        for obs in event.observations:
            meta = getattr(obs, "metadata", {}) or {}
            for key in ("due_at", "deadline", "due_date"):
                if key in meta and meta[key]:
                    val = meta[key]
                    if isinstance(val, datetime):
                        return val
                    if isinstance(val, str):
                        try:
                            return datetime.fromisoformat(val.replace("Z", "+00:00"))
                        except ValueError:
                            pass
        return None

    @staticmethod
    def _is_overdue(item: OperationalItem) -> bool:
        if item.due_at is None:
            return False
        if item.status in (OperationalItemStatus.COMPLETED, OperationalItemStatus.CLOSED, OperationalItemStatus.CANCELLED):
            return False
        now = datetime.now(item.due_at.tzinfo or timezone.utc)
        return item.due_at < now

    @staticmethod
    def _merge_event_metadata(event: OrganizationEvent) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for obs in event.observations:
            meta = getattr(obs, "metadata", {}) or {}
            result.update(meta)
        return result

    @staticmethod
    def _parse_status(value: str) -> OperationalItemStatus | None:
        normalized = value.lower().strip().replace(" ", "_")
        for status in OperationalItemStatus:
            if status.value == normalized:
                return status
        if normalized in ("done", "finished", "resolved"):
            return OperationalItemStatus.COMPLETED
        if normalized in ("working", "active"):
            return OperationalItemStatus.IN_PROGRESS
        return None
