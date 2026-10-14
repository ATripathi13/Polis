"""
ApprovalRequest entity for organizational governance.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from domain.governance.enums import ApprovalStatus


@dataclass(slots=True)
class ApprovalRequest:
    """
    Tracks an authorization/approval lifecycle for governance actions.
    """
    id: str
    title: str
    target_object: str
    requester_id: str
    status: ApprovalStatus = ApprovalStatus.REQUESTED
    policy_id: str | None = None
    approver_id: str | None = None
    source_event_id: str = ""
    source_type: str = ""
    correlation_id: str | None = None
    evidence: list[str] = field(default_factory=list)
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    granted_at: datetime | None = None
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        title: str,
        target_object: str,
        requester_id: str,
        *,
        id: str | None = None,
        policy_id: str | None = None,
        status: ApprovalStatus = ApprovalStatus.REQUESTED,
        source_event_id: str = "",
        source_type: str = "",
        correlation_id: str | None = None,
        evidence: list[str] | None = None,
        notes: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        return cls(
            id=id or str(uuid.uuid4()),
            title=title.strip(),
            target_object=target_object.strip(),
            requester_id=requester_id.strip(),
            status=status,
            policy_id=policy_id.strip() if policy_id else None,
            approver_id=None,
            source_event_id=(
                str(getattr(source_event_id, "business_id", None) or getattr(source_event_id, "graph_id", None) or source_event_id).strip()
                if source_event_id is not None
                else ""
            ),
            source_type=(
                str(getattr(source_type, "business_id", None) or getattr(source_type, "graph_id", None) or source_type).strip()
                if source_type is not None
                else ""
            ),
            correlation_id=(
                str(getattr(correlation_id, "business_id", None) or getattr(correlation_id, "graph_id", None) or correlation_id).strip()
                if correlation_id is not None
                else None
            ),
            evidence=list(evidence or []),
            requested_at=datetime.now(timezone.utc),
            granted_at=None,
            notes=notes.strip(),
            metadata=dict(metadata or {}),
        )
