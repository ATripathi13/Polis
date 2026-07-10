"""
Types of organizational events.
"""

from enum import Enum


class OrganizationEventType(str, Enum):
    """
    Canonical organizational events understood by POLIS.
    """

    UNKNOWN = "unknown"

    # Knowledge
    KNOWLEDGE_DISCOVERED = "knowledge_discovered"
    KNOWLEDGE_UPDATED = "knowledge_updated"

    # Work
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"
    TASK_COMPLETED = "task_completed"

    # Decisions
    DECISION_MADE = "decision_made"

    # Governance
    RISK_IDENTIFIED = "risk_identified"
    CONTRADICTION_DETECTED = "contradiction_detected"
    POLICY_VIOLATION = "policy_violation"

    # Collaboration
    APPROVAL_GRANTED = "approval_granted"
    QUESTION_ASKED = "question_asked"

    # Communication
    SUMMARY_REQUESTED = "summary_requested"