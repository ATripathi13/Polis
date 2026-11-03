"""
Person Work Service for POLIS.

Retrieves, extracts, deduplicates, and synthesizes recent work, tasks,
commitments, progress updates, blockers, and discussions for a specific person
from organizational Slack communications and formal operational items.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from domain.operations import OperationalItemRepository, OperationalItemType
from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.repositories import CommunicationRepository

logger = logging.getLogger(__name__)


class WorkActivityType(str, Enum):
    ACTIVE_WORK = "active_work"
    COMMITMENT = "commitment"
    ASSIGNED_WORK = "assigned_work"
    PROGRESS_UPDATE = "progress_update"
    COMPLETED_WORK = "completed_work"
    BLOCKER = "blocker"
    RECENT_DISCUSSION = "recent_discussion"


@dataclass
class ExtractedWorkItem:
    work_item: str
    activity_type: WorkActivityType
    status: str
    latest_update: str
    timestamp: datetime | None
    source_channel: str
    source_ts: str
    person_id: str
    person_name: str
    evidence: str
    deadline: str | None = None
    dependency: str | None = None
    confidence: float = 0.8
    is_parent_context: bool = False


@dataclass
class PersonWorkSummary:
    person_id: str
    person_name: str
    active_work: list[ExtractedWorkItem] = field(default_factory=list)
    commitments: list[ExtractedWorkItem] = field(default_factory=list)
    assigned_work: list[ExtractedWorkItem] = field(default_factory=list)
    completed_work: list[ExtractedWorkItem] = field(default_factory=list)
    blockers: list[ExtractedWorkItem] = field(default_factory=list)
    discussions: list[ExtractedWorkItem] = field(default_factory=list)
    time_window_days: int = 7
    total_messages_searched: int = 0
    formatted_response: str = ""

    @property
    def items(self) -> list[ExtractedWorkItem]:
        return (
            self.active_work
            + self.commitments
            + self.assigned_work
            + self.completed_work
            + self.blockers
            + self.discussions
        )


class PersonWorkService:
    """
    Service responsible for reconstructing an employee's current work,
    commitments, completed work, blockers, and discussions from actual
    organizational conversation records.
    """

    def __init__(
        self,
        communication_repository: CommunicationRepository,
        operational_item_repository: OperationalItemRepository | None = None,
        identity_service: Any | None = None,
    ) -> None:
        self._communication_repository = communication_repository
        self._operational_item_repository = operational_item_repository
        self._identity_service = identity_service

    def get_person_work_summary(
        self,
        target_user_id: str | None,
        target_user_name: str | None = None,
        requester_user_id: str | None = None,
        lookback_days: int = 7,
        query_text: str | None = None,
    ) -> PersonWorkSummary:
        """
        Aggregate and synthesize person-specific work from recent communications.
        """
        # Determine effective employee identifiers
        all_ids: set[str] = set()
        clean_target_id = (target_user_id or "").strip()
        if clean_target_id:
            all_ids.add(clean_target_id)
            if self._identity_service is not None and hasattr(self._identity_service, "get_all_identifiers_for_user"):
                try:
                    all_ids.update(self._identity_service.get_all_identifiers_for_user(clean_target_id))
                except Exception:
                    pass

        # Resolve canonical name if not provided
        display_name = target_user_name or clean_target_id or "the employee"
        if (not target_user_name or target_user_name == clean_target_id) and clean_target_id and self._identity_service is not None:
            if hasattr(self._identity_service, "get_display_name"):
                try:
                    resolved_name = self._identity_service.get_display_name(clean_target_id)
                    if resolved_name and resolved_name != clean_target_id:
                        display_name = resolved_name
                except Exception:
                    pass

        # Parse lookback window from query text if present (e.g. "this week" -> 7 days, "30 days" / "this month" -> 30 days)
        if query_text:
            lowered_q = query_text.lower()
            if "30 days" in lowered_q or "month" in lowered_q:
                lookback_days = 30
            elif "yesterday" in lowered_q:
                lookback_days = 2
            elif "week" in lowered_q or "last few days" in lowered_q:
                lookback_days = 7

        now = datetime.now(timezone.utc)
        start_time = now - timedelta(days=lookback_days)

        # 1. Retrieve communications from repository
        communications: list[CommunicationEvent] = []
        try:
            communications = self._communication_repository.get_person_recent_activity(
                actor_ids=list(all_ids),
                actor_name=display_name if display_name != clean_target_id else None,
                start_time=start_time,
                end_time=now + timedelta(hours=1),
                limit=100,
                include_mentions=True,
                include_parent_context=True,
            )
        except Exception as exc:
            logger.exception("Failed to retrieve communications for person %s: %s", clean_target_id, exc)

        summary = PersonWorkSummary(
            person_id=clean_target_id,
            person_name=display_name,
            time_window_days=lookback_days,
            total_messages_searched=len(communications),
        )

        # 2. Extract work items from communications
        raw_items: list[ExtractedWorkItem] = []
        for comm in communications:
            # Enforce permission boundaries (Requirement 7 & Test K)
            ch_type = getattr(comm.channel, "channel_type", "")
            ch_id = getattr(getattr(comm.channel, "identity", None), "internal_id", "")
            if ch_type in ("im", "mpim", "private"):
                # For private channels/DMs: only accessible if requester is the actor or authorized
                actor_internal = getattr(getattr(comm.actor, "identity", None), "internal_id", "")
                if requester_user_id and actor_internal != requester_user_id and requester_user_id not in ch_id:
                    continue

            extracted = self._extract_from_communication(
                comm,
                target_ids=all_ids,
                target_name=display_name,
            )
            raw_items.extend(extracted)

        # 3. Retrieve formal operational items (if any exist)
        formal_items = self._extract_from_operational_items(all_ids, display_name)
        raw_items.extend(formal_items)

        # 4. Deduplicate and apply recency precedence (Scenario E)
        consolidated = self._consolidate_and_rank(raw_items)

        # 5. Partition into summary sections
        for item in consolidated:
            if item.activity_type == WorkActivityType.ACTIVE_WORK:
                summary.active_work.append(item)
            elif item.activity_type == WorkActivityType.COMMITMENT:
                summary.commitments.append(item)
            elif item.activity_type == WorkActivityType.ASSIGNED_WORK:
                summary.assigned_work.append(item)
            elif item.activity_type == WorkActivityType.COMPLETED_WORK:
                summary.completed_work.append(item)
            elif item.activity_type == WorkActivityType.BLOCKER:
                summary.blockers.append(item)
            elif item.activity_type == WorkActivityType.RECENT_DISCUSSION:
                summary.discussions.append(item)

        summary.formatted_response = self.format_summary_response(summary)
        return summary

    def _extract_from_communication(
        self,
        comm: CommunicationEvent,
        target_ids: set[str],
        target_name: str,
    ) -> list[ExtractedWorkItem]:
        body = (comm.content.body or "").strip()
        if not body:
            return []

        created_at = comm.created_at
        channel_name = comm.channel.name or "channel"
        source_ts = comm.source_event_id

        actor_internal = getattr(getattr(comm.actor, "identity", None), "internal_id", "")
        actor_name = getattr(comm.actor, "display_name", "") or actor_internal
        is_target_author = bool(actor_internal in target_ids or (target_name and actor_name.lower() == target_name.lower()))

        parent_body = comm.content.metadata.get("parent_message_body", "")
        parent_author = comm.content.metadata.get("parent_actor_name", "")
        has_parent_context = bool(parent_body and comm.correlation_id.business_id != comm.source_event_id)

        items: list[ExtractedWorkItem] = []

        # -------------------------------------------------------------
        # Case A: Authored by target person
        # -------------------------------------------------------------
        if is_target_author:
            # Handle thread reply with parent message context (Scenario C)
            if has_parent_context:
                parent_topic = self._clean_topic_phrase(parent_body)

                # Check if reply has both progress/completed and pending parts
                sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", body) if s.strip()]
                for s in sentences:
                    s_type, s_desc = self._classify_statement(s)
                    full_desc = f"{parent_topic} — {s_desc}" if parent_topic and parent_topic.lower() not in s_desc.lower() else s_desc
                    items.append(
                        ExtractedWorkItem(
                            work_item=full_desc,
                            activity_type=s_type,
                            status=self._status_for_type(s_type),
                            latest_update=s,
                            timestamp=created_at,
                            source_channel=channel_name,
                            source_ts=source_ts,
                            person_id=actor_internal,
                            person_name=actor_name,
                            evidence=f"Thread reply: \"{body}\" (Parent: \"{parent_body}\")",
                            is_parent_context=True,
                        )
                    )
                if items:
                    return items

            # Standalone message or direct statements
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", body) if s.strip()]
            for s in sentences:
                s_type, s_desc = self._classify_statement(s)
                items.append(
                    ExtractedWorkItem(
                        work_item=s_desc,
                        activity_type=s_type,
                        status=self._status_for_type(s_type),
                        latest_update=s,
                        timestamp=created_at,
                        source_channel=channel_name,
                        source_ts=source_ts,
                        person_id=actor_internal,
                        person_name=actor_name,
                        evidence=body,
                    )
                )

        # -------------------------------------------------------------
        # Case B: Authored by another employee (Mentions / Assignments)
        # -------------------------------------------------------------
        else:
            # Check for explicit assignment to target person (Scenario B)
            # e.g. "Gurkirat, please test the approval-to-post workflow" or "<@U123>, please test..."
            id_patterns = [rf"<@{re.escape(uid)}(?:\|[^>]+)?>" for uid in target_ids]
            name_pattern = re.escape(target_name) if target_name and len(target_name) >= 2 else ""

            target_tokens = id_patterns + ([name_pattern] if name_pattern else [])
            combined_token = "(?:" + "|".join(target_tokens) + ")"

            assign_match = re.search(
                rf"{combined_token}\s*[,:]?\s*(?:please|kindly|could you|can you|to)\s+(.+)$",
                body,
                re.IGNORECASE,
            )
            assign_to_match = re.search(
                rf"\b(?:assign(?:ing|ed)?\s+(?:this\s+)?to)\s+{combined_token}\b(?:\s*[:\-]\s*(.+))?",
                body,
                re.IGNORECASE,
            )

            if assign_match:
                task_desc = self._clean_topic_phrase(assign_match.group(1))
                items.append(
                    ExtractedWorkItem(
                        work_item=task_desc,
                        activity_type=WorkActivityType.ASSIGNED_WORK,
                        status="assigned",
                        latest_update=body,
                        timestamp=created_at,
                        source_channel=channel_name,
                        source_ts=source_ts,
                        person_id=list(target_ids)[0] if target_ids else "",
                        person_name=target_name,
                        evidence=f"Assigned by {actor_name}: \"{body}\"",
                    )
                )
            elif assign_to_match:
                task_desc = self._clean_topic_phrase(assign_to_match.group(1) or body)
                items.append(
                    ExtractedWorkItem(
                        work_item=task_desc,
                        activity_type=WorkActivityType.ASSIGNED_WORK,
                        status="assigned",
                        latest_update=body,
                        timestamp=created_at,
                        source_channel=channel_name,
                        source_ts=source_ts,
                        person_id=list(target_ids)[0] if target_ids else "",
                        person_name=target_name,
                        evidence=f"Assigned by {actor_name}: \"{body}\"",
                    )
                )
            else:
                # Merely mentioned or discussed without direct assignment
                topic = self._clean_topic_phrase(body)
                items.append(
                    ExtractedWorkItem(
                        work_item=topic,
                        activity_type=WorkActivityType.RECENT_DISCUSSION,
                        status="discussed",
                        latest_update=body,
                        timestamp=created_at,
                        source_channel=channel_name,
                        source_ts=source_ts,
                        person_id=list(target_ids)[0] if target_ids else "",
                        person_name=target_name,
                        evidence=f"Mentioned by {actor_name}: \"{body}\"",
                    )
                )

        return items

    def _extract_from_operational_items(
        self,
        target_ids: set[str],
        target_name: str,
    ) -> list[ExtractedWorkItem]:
        if self._operational_item_repository is None or not target_ids:
            return []

        items: list[ExtractedWorkItem] = []
        try:
            for uid in target_ids:
                recs = []
                if hasattr(self._operational_item_repository, "find_open_for_owner_or_name"):
                    recs = self._operational_item_repository.find_open_for_owner_or_name(
                        owner_id=uid,
                        owner_name=target_name,
                        item_type=OperationalItemType.TASK,
                    )
                elif hasattr(self._operational_item_repository, "find_open"):
                    recs = self._operational_item_repository.find_open(
                        owner_id=uid,
                        item_type=OperationalItemType.TASK,
                    )
                for r in recs:
                    status_str = r.status.value.lower()
                    if status_str in ("completed", "closed"):
                        act_type = WorkActivityType.COMPLETED_WORK
                    else:
                        act_type = WorkActivityType.ACTIVE_WORK

                    due_str = r.due_at.strftime("%Y-%m-%d") if r.due_at else None
                    items.append(
                        ExtractedWorkItem(
                            work_item=r.summary,
                            activity_type=act_type,
                            status=r.status.value,
                            latest_update=f"Operational task ({r.status.value})",
                            timestamp=r.created_at,
                            source_channel="Operational Items",
                            source_ts=r.id,
                            person_id=uid,
                            person_name=r.owner_name or target_name,
                            evidence=f"Polis Task ID: {r.id}",
                            deadline=due_str,
                            confidence=1.0,
                        )
                    )
        except Exception as exc:
            logger.warning("Failed to retrieve formal operational items: %s", exc)

        return items

    def _classify_statement(self, sentence: str) -> tuple[WorkActivityType, str]:
        s = sentence.strip()
        lowered = s.lower()

        # 1. Blocker (Scenario D)
        blocker_match = re.search(
            r"\b(?:blocked\s+(?:because|by|on)|blocker\s+is|waiting\s+for|can't\s+proceed\s+without)\s+(.+)$",
            s,
            re.IGNORECASE,
        )
        if blocker_match or re.search(r"\b(?:is\s+blocked|blocker|dependency)\b", lowered):
            desc = blocker_match.group(1).strip() if blocker_match else s
            return WorkActivityType.BLOCKER, self._clean_topic_phrase(desc)

        # 2. Future commitment / dependency (Scenario A)
        # Explicit will / plan statements take precedence over subordinate completion clauses
        if re.search(
            r"\b(?:i\s+will\s+start|i'll\s+start|i\s+will|i'll|i\s+plan\s+to|planning\s+to|i\s+shall|going\s+to\s+start|will\s+handle|will\s+take\s+care|commit\s+to)\b",
            lowered,
        ):
            return WorkActivityType.COMMITMENT, self._clean_topic_phrase(s)

        # 3. Completed work (Scenario A, E)
        if re.search(
            r"\b(?:have\s+completed|is\s+complete|are\s+complete|completed|have\s+finished|finished|passed\s+all\s+tests|is\s+done|are\s+done|has\s+passed)\b",
            lowered,
        ):
            return WorkActivityType.COMPLETED_WORK, self._clean_topic_phrase(s)

        # 4. Progress update (Scenario B, C)
        if re.search(
            r"\b(?:workflow\s+can\s+now|now\s+supports|have\s+updated|i've\s+updated|updated\s+the|progress\s+on)\b",
            lowered,
        ):
            return WorkActivityType.ACTIVE_WORK, self._clean_topic_phrase(s)

        # 5. Active work (Scenario A, B, C, E)
        if re.search(
            r"\b(?:i\s+am\s+implementing|currently\s+implementing|implementing|i\s+am\s+working\s+on|working\s+on|i\s+am\s+refining|refining|building|developing|handling|still\s+need\s+to|need\s+to|have\s+started|started|validating|testing)\b",
            lowered,
        ):
            return WorkActivityType.ACTIVE_WORK, self._clean_topic_phrase(s)

        # 6. Default to recent discussion
        return WorkActivityType.RECENT_DISCUSSION, self._clean_topic_phrase(s)

    def _status_for_type(self, activity_type: WorkActivityType) -> str:
        if activity_type == WorkActivityType.ACTIVE_WORK:
            return "in_progress"
        if activity_type == WorkActivityType.COMPLETED_WORK:
            return "completed"
        if activity_type == WorkActivityType.COMMITMENT:
            return "planned"
        if activity_type == WorkActivityType.BLOCKER:
            return "blocked"
        if activity_type == WorkActivityType.ASSIGNED_WORK:
            return "assigned"
        return "discussed"

    def _clean_topic_phrase(self, text: str) -> str:
        cleaned = text.strip().rstrip(".!?")
        # Remove common self-prefixes
        cleaned = re.sub(
            r"^(?:i\s+am\s+|i'm\s+|i\s+have\s+|i've\s+|i\s+will\s+|i'll\s+|currently\s+|we\s+need\s+to\s+|please\s+)",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        return cleaned[:120] if cleaned else text[:120]

    def _consolidate_and_rank(self, items: list[ExtractedWorkItem]) -> list[ExtractedWorkItem]:
        """
        Deduplicate items and apply recency precedence.
        If an item was previously active but a newer update states it is completed,
        mark it completed (Scenario E).
        """
        if not items:
            return []

        # Sort items by timestamp ascending so newer updates process last
        sorted_items = sorted(
            items,
            key=lambda x: x.timestamp or datetime.min.replace(tzinfo=timezone.utc),
        )

        consolidated_map: dict[str, ExtractedWorkItem] = {}

        for item in sorted_items:
            norm_key = self._normalize_item_key(item.work_item)
            if not norm_key:
                continue

            matching_key = None
            if norm_key in consolidated_map:
                matching_key = norm_key
            else:
                norm_tokens = set(norm_key.split())
                for k in consolidated_map:
                    k_tokens = set(k.split())
                    union = norm_tokens | k_tokens
                    if not union:
                        continue
                    jaccard = len(norm_tokens & k_tokens) / len(union)
                    if jaccard >= 0.6:
                        matching_key = k
                        break

            if matching_key:
                existing = consolidated_map[matching_key]
                # If newer update is COMPLETED, update the state to completed
                if item.activity_type == WorkActivityType.COMPLETED_WORK:
                    consolidated_map[matching_key] = item
                # If newer update is ACTIVE, keep the newer active update
                elif item.activity_type == WorkActivityType.ACTIVE_WORK and existing.activity_type != WorkActivityType.COMPLETED_WORK:
                    consolidated_map[matching_key] = item
                # If newer update is BLOCKER, prioritize blocker
                elif item.activity_type == WorkActivityType.BLOCKER:
                    consolidated_map[matching_key] = item
                else:
                    # Update evidence and timestamp if newer
                    if (item.timestamp or datetime.min.replace(tzinfo=timezone.utc)) >= (existing.timestamp or datetime.min.replace(tzinfo=timezone.utc)):
                        consolidated_map[matching_key] = item
            else:
                consolidated_map[norm_key] = item

        # Return sorted by recency descending (newest first)
        return sorted(
            consolidated_map.values(),
            key=lambda x: x.timestamp or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    @staticmethod
    def _normalize_item_key(text: str) -> str:
        # Strip stop words and normalize to cluster related updates
        words = re.findall(r"\b[a-zA-Z0-9_-]+\b", text.lower())
        stop = {
            "i", "am", "the", "a", "an", "is", "are", "complete", "completed", "working",
            "on", "start", "to", "for", "in", "it", "old", "new", "current", "latest",
            "recent", "changes", "change", "update", "updates", "task", "tasks",
        }
        meaningful = [w for w in words if w not in stop]
        return " ".join(sorted(meaningful)) if meaningful else " ".join(words)

    def format_summary_response(self, summary: PersonWorkSummary) -> str:
        """
        Produce a clear, structured, evidence-grounded response adhering to
        the Section 4.5 and Section 7 specifications.
        """
        has_any_content = bool(
            summary.active_work
            or summary.commitments
            or summary.assigned_work
            or summary.completed_work
            or summary.blockers
            or summary.discussions
        )

        if not has_any_content:
            return (
                f"I searched organizational Slack channels and recorded tasks for {summary.person_name} "
                f"over the last {summary.time_window_days} days, but found no recent work activity, "
                "commitments, or discussions recorded during this period."
            )

        sections: list[str] = []

        # Current Work
        if summary.active_work:
            lines = ["**Current Work**"]
            for item in summary.active_work:
                date_str = item.timestamp.strftime("%Y-%m-%d") if item.timestamp else "Recently"
                lines.append(f"• **{item.work_item}** — {item.latest_update} (Status: `{item.status}`, Last updated: {date_str}, Source: #{item.source_channel})")
            sections.append("\n".join(lines))

        # Assigned Work and Commitments
        combined_commitments = summary.assigned_work + summary.commitments
        if combined_commitments:
            lines = ["**Assigned Work and Commitments**"]
            for item in combined_commitments:
                deadline_part = f", Deadline: {item.deadline}" if item.deadline else ""
                lines.append(f"• **{item.work_item}** — {item.evidence}{deadline_part} (Source: #{item.source_channel})")
            sections.append("\n".join(lines))

        # Recently Completed
        if summary.completed_work:
            lines = ["**Recently Completed**"]
            for item in summary.completed_work:
                date_str = item.timestamp.strftime("%Y-%m-%d") if item.timestamp else ""
                date_part = f" on {date_str}" if date_str else ""
                lines.append(f"• **{item.work_item}** — Completed{date_part}. Evidence: \"{item.latest_update}\" (Source: #{item.source_channel})")
            sections.append("\n".join(lines))

        # Blockers and Dependencies
        if summary.blockers:
            lines = ["**Blockers and Dependencies**"]
            for item in summary.blockers:
                lines.append(f"• **{item.work_item}** — {item.latest_update} (Source: #{item.source_channel})")
            sections.append("\n".join(lines))

        # Recent Discussions
        if summary.discussions:
            lines = ["**Recent Discussions**"]
            for item in summary.discussions[:4]:
                lines.append(f"• **{item.work_item}** — {item.evidence} (Source: #{item.source_channel})")
            sections.append("\n".join(lines))

        # Overall Priorities
        priorities: list[str] = []
        if summary.active_work:
            priorities.extend([f"Continuing {item.work_item}" for item in summary.active_work[:2]])
        if summary.blockers:
            priorities.extend([f"Resolving blocker on {item.work_item}" for item in summary.blockers[:1]])
        if summary.commitments:
            priorities.extend([f"Upcoming commitment: {item.work_item}" for item in summary.commitments[:2]])

        if priorities:
            lines = ["**Overall Priorities**"]
            for p in priorities:
                lines.append(f"• {p}")
            sections.append("\n".join(lines))

        return "\n\n".join(sections)
