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
        OrganizationEventType.TASK_UPDATED: OperationalItemType.TASK,
        OrganizationEventType.TASK_COMPLETED: OperationalItemType.TASK,
        OrganizationEventType.DECISION_MADE: OperationalItemType.DECISION,
        OrganizationEventType.RISK_IDENTIFIED: OperationalItemType.RISK,
    }

    def __init__(
        self,
        repository: OperationalItemRepository,
        identity_service: Any | None = None,
    ) -> None:
        self._repository = repository
        self._identity_service = identity_service

    def process_event(
        self,
        event: OrganizationEvent,
        *,
        source_type: str = "",
        source_event_id: str = "",
    ) -> OperationalItem | None:
        item_type = self._EVENT_TYPE_MAPPING.get(
            event.event_type
        )

        if item_type is None:
            return None

        if not source_event_id and event.observations:
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
                if event.event_type == OrganizationEventType.TASK_COMPLETED:
                    existing.status = OperationalItemStatus.COMPLETED
                    existing.touch()
                    return self._repository.save(existing)
                if event.event_type == OrganizationEventType.TASK_UPDATED:
                    existing.status = OperationalItemStatus.IN_PROGRESS
                    existing.summary = event.summary
                    existing.touch()
                    return self._repository.save(existing)
                return existing

        initial_status = OperationalItemStatus.OPEN
        if event.event_type == OrganizationEventType.TASK_COMPLETED:
            initial_status = OperationalItemStatus.COMPLETED
        elif event.event_type == OrganizationEventType.TASK_UPDATED:
            initial_status = OperationalItemStatus.IN_PROGRESS

        item = OperationalItem.create(
            item_type=item_type,
            summary=event.summary,
            status=initial_status,
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
        Personal task retrieval is strictly scoped to the authenticated employee.
        Organization-wide items (decisions, risks, company announcements) remain
        distinctly categorized and never confused with personal assignments.
        """
        import re
        from application.identity import IdentityResolutionStatus

        text = getattr(question, "text", "") or str(question)
        normalized = " ".join(text.lower().strip().split())

        # 1. Resolve requester identity
        ctx = getattr(question, "context", None)
        ctx_user_id = getattr(ctx, "user_id", None) if ctx else None
        requester_user_id = getattr(question, "user_id", None) or ctx_user_id

        # 2. Check for self-reference
                # 2. Check for explicit self-reference using whole-word matching.
        # Generic phrases such as "working on today" must not imply self-reference.
        is_self_reference = bool(
            re.search(r"\b(?:my|mine|me|i)\b", normalized)
        )
        # is_self_reference = any(tok in normalized for tok in self_ref_tokens)

        # 3. Detect and resolve target employee (if not a self-reference)
        target_employee_id: str | None = None
        target_employee_name: str | None = None
        target_unresolved_label: str | None = None

        if not is_self_reference:
            raw_target_id = getattr(question, "target_user_id", None)
            raw_target_name = getattr(question, "target_user_name", None)

            # Check if text explicitly mentions a target employee name
            name_match = (
                re.search(r"\b([A-Za-z0-9_]+)'s\s+(?:overdue\s+)?(?:tasks?|todos?|to-dos?|work|actions?)\b", text, re.IGNORECASE)
                or re.search(r"\b(?:tasks?|todos?|to-dos?|work|actions?)\s+(?:for|of|assigned\s+to)\s+([A-Za-z0-9_]+)\b", text, re.IGNORECASE)
                or re.search(r"\bwhat\s+(?:is|are)\s+([A-Za-z0-9_]+)\s+working\s+on\b", text, re.IGNORECASE)
            )
            extracted_name = name_match.group(1).strip() if name_match else None
            non_person_words = {
                "my", "our", "your", "the", "a", "an", "all", "open", "any", "this", "that",
                "organization", "company", "team", "project", "everyone", "we", "us",
                "department", "whole", "system", "general",
            }
            if extracted_name and extracted_name.lower() in non_person_words:
                extracted_name = None

            candidate_name = raw_target_name or extracted_name
            candidate_id = raw_target_id

            if candidate_id:
                # Direct target_user_id was provided
                if self._identity_service and hasattr(self._identity_service, "resolve_user"):
                    res = self._identity_service.resolve_user(candidate_id)
                    if getattr(res, "resolution_status", None) == IdentityResolutionStatus.UNRESOLVED:
                        target_unresolved_label = candidate_name or candidate_id
                    else:
                        target_employee_id = getattr(res, "internal_id", candidate_id) or candidate_id
                        target_employee_name = candidate_name or getattr(res, "canonical_name", candidate_id)
                else:
                    target_employee_id = candidate_id
                    target_employee_name = candidate_name or candidate_id
            elif candidate_name:
                # Target name was provided or extracted
                if self._identity_service and hasattr(self._identity_service, "resolve_user_by_name_or_mention"):
                    res = self._identity_service.resolve_user_by_name_or_mention(candidate_name)
                    if res is not None and getattr(res, "resolution_status", None) != IdentityResolutionStatus.UNRESOLVED and getattr(res, "internal_id", None):
                        target_employee_id = res.internal_id
                        target_employee_name = getattr(res, "canonical_name", candidate_name)
                    else:
                        target_unresolved_label = candidate_name
                else:
                    # Without identity service, check if repository has items with this owner
                    matching = self._repository.find_open(item_type=OperationalItemType.TASK)
                    name_matches = [
                        i for i in matching
                        if (i.owner_name and i.owner_name.lower() == candidate_name.lower())
                        or (i.owner_id and i.owner_id.lower() == candidate_name.lower())
                    ]
                    if name_matches:
                        target_employee_id = name_matches[0].owner_id or candidate_name
                        target_employee_name = name_matches[0].owner_name or candidate_name
                    else:
                        target_unresolved_label = candidate_name

        clarification_response = [
            "Operational item: note\n"
            f"Message: Could not resolve target employee '{target_unresolved_label}'. Please clarify which employee's tasks you would like to view."
        ]

        # 1. Overdue items query
        if any(
            phrase in normalized
            for phrase in (
                "overdue",
                "past due",
                "late task",
                "late tasks",
            )
        ):
            if target_unresolved_label:
                return clarification_response

            now = datetime.now(timezone.utc)
            all_overdue = self._repository.find_overdue(now)

            if is_self_reference:
                if not requester_user_id:
                    return [
                        "Operational item: note\n"
                        "Message: Authenticated employee identity could not be verified for personal task retrieval."
                    ]
                query_ids: set[str] = {requester_user_id}
                if self._identity_service and hasattr(self._identity_service, "get_all_identifiers_for_user"):
                    query_ids.update(self._identity_service.get_all_identifiers_for_user(requester_user_id))
                items = [t for t in all_overdue if t.owner_id in query_ids]
            elif target_employee_id:
                query_ids = {target_employee_id}
                if self._identity_service and hasattr(self._identity_service, "get_all_identifiers_for_user"):
                    query_ids.update(self._identity_service.get_all_identifiers_for_user(target_employee_id))
                items = [
                    t for t in all_overdue
                    if t.owner_id in query_ids
                    or (target_employee_name and t.owner_name and t.owner_name.lower() == target_employee_name.lower())
                ]
            else:
                # General organization-wide overdue report
                items = all_overdue

            evidence = []
            for item in items:
                owner_label = item.owner_name or item.owner_id or "Unassigned"
                ev_text = (
                    f"Operational item: {item.item_type.value} [Overdue]\n"
                    f"Summary: {item.summary}\n"
                    f"Owner: {owner_label}\n"
                    f"Status: {item.status.value}\n"
                    f"Priority: {item.priority.value}"
                )
                if item.due_at is not None:
                    ev_text += f"\nDue: {item.due_at.strftime('%Y-%m-%d')}"
                evidence.append(ev_text)
            return evidence

        # 2. Organization decisions
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
            evidence = []
            for item in items:
                evidence.append(
                    f"[Organization Decision]\n"
                    f"Summary: {item.summary}\n"
                    f"Status: {item.status.value}\n"
                    f"Priority: {item.priority.value}"
                )
            return evidence

        # 3. Organization risks
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
            evidence = []
            for item in items:
                evidence.append(
                    f"[Organization Risk]\n"
                    f"Summary: {item.summary}\n"
                    f"Status: {item.status.value}\n"
                    f"Priority: {item.priority.value}"
                )
            return evidence

        # 4. Tasks (Personal vs. Target vs. Organization-wide)
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
                "break down",
                "actionable step",
                "actionable steps",
                "next step",
                "next steps",
                "start with",
                "work on",
                "working on",
            )
        ):
            if target_unresolved_label:
                return clarification_response

            if is_self_reference:
                if not requester_user_id:
                    return [
                        "Operational item: note\n"
                        "Message: Authenticated employee identity could not be verified for personal task retrieval."
                    ]

                query_ids: set[str] = {requester_user_id}
                if self._identity_service and hasattr(self._identity_service, "get_all_identifiers_for_user"):
                    query_ids.update(self._identity_service.get_all_identifiers_for_user(requester_user_id))

                personal_items = self._repository.find_open(
                    item_type=OperationalItemType.TASK,
                    owner_id=list(query_ids) if len(query_ids) > 1 else requester_user_id,
                )

                if not personal_items:
                    return [
                        f"Personal operational tasks: No open tasks currently assigned to authenticated employee ({requester_user_id})."
                    ]

                evidence = []
                for item in personal_items:
                    ev_text = (
                        f"Personal operational task:\n"
                        f"Summary: {item.summary}\n"
                        f"Status: {item.status.value}\n"
                        f"Priority: {item.priority.value}"
                    )
                    if item.due_at is not None:
                        ev_text += f"\nDue: {item.due_at.strftime('%Y-%m-%d')}"
                    evidence.append(ev_text)

                return evidence

            elif target_employee_id:
                query_ids = {target_employee_id}
                if self._identity_service and hasattr(self._identity_service, "get_all_identifiers_for_user"):
                    query_ids.update(self._identity_service.get_all_identifiers_for_user(target_employee_id))

                target_items = self._repository.find_open(
                    item_type=OperationalItemType.TASK,
                    owner_id=list(query_ids) if len(query_ids) > 1 else target_employee_id,
                )

                if not target_items:
                    display_label = target_employee_name or target_employee_id
                    return [
                        f"Personal operational tasks: No open tasks currently assigned to employee ({display_label})."
                    ]

                evidence = []
                for item in target_items:
                    ev_text = (
                        f"Personal operational task:\n"
                        f"Summary: {item.summary}\n"
                        f"Status: {item.status.value}\n"
                        f"Priority: {item.priority.value}"
                    )
                    if item.due_at is not None:
                        ev_text += f"\nDue: {item.due_at.strftime('%Y-%m-%d')}"
                    evidence.append(ev_text)

                return evidence

            # General / organization-wide query (e.g., "What tasks are open across the organization?", "What tasks are open?", "What is the audit task?")
            all_open = self._repository.find_open(
                item_type=OperationalItemType.TASK,
            )

            # Check if specific non-stopword keyword in query matches task summary (e.g. 'audit')
            stopwords = {
                "what", "is", "the", "are", "open", "task", "tasks", "a", "an", "do", "we", "have",
                "there", "any", "across", "organization", "company",
            }
            query_words = set(normalized.split()) - stopwords
            if query_words:
                matched_items = [
                    item for item in all_open
                    if any(w in item.summary.lower() for w in query_words)
                ]
                items = matched_items if matched_items else all_open
            else:
                items = all_open

            evidence = []
            for item in items:
                owner_label = item.owner_name or item.owner_id or "Unassigned"
                ev_text = (
                    f"Operational item: {item.item_type.value}\n"
                    f"Summary: {item.summary}\n"
                    f"Owner: {owner_label}\n"
                    f"Status: {item.status.value}\n"
                    f"Priority: {item.priority.value}"
                )
                if item.due_at is not None:
                    ev_text += f"\nDue: {item.due_at.strftime('%Y-%m-%d')}"
                evidence.append(ev_text)

            return evidence

        return []
