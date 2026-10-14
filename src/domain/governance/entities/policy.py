"""
Policy entity for organizational governance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from domain.governance.enums import (
    PolicyScope,
    PolicySeverity,
    PolicyEnforcementMode,
)


@dataclass(slots=True)
class Policy:
    """
    Authoritative organizational policy definition.
    """
    policy_id: str
    name: str
    description: str
    scope: PolicyScope = PolicyScope.GENERAL
    severity: PolicySeverity = PolicySeverity.MEDIUM
    enforcement_mode: PolicyEnforcementMode = PolicyEnforcementMode.MANDATORY
    authority: str = "POLIS Governance Architecture"
    requires_approval: bool = False
    rule_description: str = ""
    condition_keywords: list[str] = field(default_factory=list)
    effective_date: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        policy_id: str,
        name: str,
        description: str,
        *,
        scope: PolicyScope = PolicyScope.GENERAL,
        severity: PolicySeverity = PolicySeverity.MEDIUM,
        enforcement_mode: PolicyEnforcementMode = PolicyEnforcementMode.MANDATORY,
        authority: str = "POLIS Governance Architecture",
        requires_approval: bool = False,
        rule_description: str = "",
        condition_keywords: list[str] | None = None,
        effective_date: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Policy:
        return cls(
            policy_id=policy_id.strip(),
            name=name.strip(),
            description=description.strip(),
            scope=scope,
            severity=severity,
            enforcement_mode=enforcement_mode,
            authority=authority.strip(),
            requires_approval=requires_approval,
            rule_description=rule_description.strip(),
            condition_keywords=list(condition_keywords or []),
            effective_date=effective_date or datetime.now(timezone.utc),
            metadata=dict(metadata or {}),
        )
