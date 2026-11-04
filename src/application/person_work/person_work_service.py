"""
Person Work Service for POLIS.

Retrieves, extracts, deduplicates, and synthesizes recent work, tasks,
commitments, progress updates, blockers, and discussions for a specific person
from organizational Slack communications and formal operational items.
Provides humanized intelligence synthesis using the configured LLM client
with a robust, readable deterministic fallback.
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
    project: str | None = None
    updates: list[str] = field(default_factory=list)


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
    query_focus: str = "current_work"
    is_self: bool = False

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
    organizational conversation records and providing humanized synthesis.
    """

    def __init__(
        self,
        communication_repository: CommunicationRepository,
        operational_item_repository: OperationalItemRepository | None = None,
        identity_service: Any | None = None,
        llm_client: Any | None = None,
    ) -> None:
        self._communication_repository = communication_repository
        self._operational_item_repository = operational_item_repository
        self._identity_service = identity_service
        self._llm_client = llm_client

    @property
    def llm_client(self) -> Any | None:
        return self._llm_client

    @llm_client.setter
    def llm_client(self, client: Any) -> None:
        self._llm_client = client

    def get_person_work_summary(
        self,
        target_user_id: str | None,
        target_user_name: str | None = None,
        requester_user_id: str | None = None,
        lookback_days: int = 7,
        query_text: str | None = None,
        is_self: bool = False,
        requester_channel_type: str | None = None,
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

        # Parse lookback window from query text if present
        if query_text:
            lowered_q = query_text.lower()
            if "30 days" in lowered_q or "month" in lowered_q or "past month" in lowered_q:
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
            is_self=is_self,
        )

        # 2. Extract work items from communications
        raw_items: list[ExtractedWorkItem] = []
        for comm in communications:
            # Enforce permission boundaries
            ch_type = getattr(comm.channel, "channel_type", "")
            ch_id = getattr(getattr(comm.channel, "identity", None), "internal_id", "")
            if ch_type in ("im", "mpim", "private"):
                # Requirement: Do not use inaccessible private messages to answer a public-channel question
                if requester_channel_type == "public":
                    continue
                # In DMs / private channels, verify requester authorization
                actor_internal = getattr(getattr(comm.actor, "identity", None), "internal_id", "")
                authorized_users: set[str] = set()
                if actor_internal:
                    authorized_users.add(actor_internal)
                if isinstance(ch_id, str):
                    for part in ch_id.replace("_", "-").split("-"):
                        if part:
                            authorized_users.add(part)
                if hasattr(comm.channel, "metadata") and isinstance(comm.channel.metadata, dict):
                    authorized_users.update(comm.channel.metadata.get("members", []))
                if hasattr(comm.content, "metadata") and isinstance(comm.content.metadata, dict):
                    authorized_users.update(comm.content.metadata.get("authorized_users", []))
                if hasattr(comm, "mentions") and isinstance(comm.mentions, list):
                    authorized_users.update(comm.mentions)

                if requester_user_id and requester_user_id not in authorized_users and requester_user_id not in ch_id:
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

        # 4. Deduplicate, group workstreams, and apply recency precedence
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

        # 6. Generate humanized synthesis
        summary.formatted_response = self.synthesize_response(
            summary=summary,
            query_text=query_text,
            is_self=is_self,
        )
        return summary

    @staticmethod
    def _is_ignorable_message(text: str) -> bool:
        s = text.strip()
        if not s:
            return True

        lowered = s.lower()
        clean = re.sub(r"[?!.,;:]+$", "", lowered).strip()

        # 1. Pure greetings and polite formulas
        if re.match(
            r"^(?:hi|hello|hey|good\s+morning|good\s+afternoon|good\s+evening|greetings|welcome|thanks|thank\s+you|cheers|bye|goodbye)\b(?:\s+(?:all|team|there|polis|everyone|folks|guys|here))?$",
            clean,
        ):
            return True

        # 2. Bot capability questions and generic prompts
        if re.search(
            r"\b(?:what\s+can\s+you\s+help\s+(?:me\s+)?with|what\s+can\s+you\s+do|how\s+(?:can|do)\s+you\s+help|help\s+me\b|who\s+are\s+you|what\s+is\s+polis)\b",
            lowered,
        ):
            return True

        # 3. Identity meta-questions (e.g. "Who is Akshat?")
        if re.match(r"^who\s+is\s+[a-zA-Z0-9_\-\s]+$", clean):
            return True

        return False

    @staticmethod
    def _is_interrogative_or_non_work(sentence: str) -> bool:
        s = sentence.strip()
        if not s:
            return True

        lowered = s.lower().strip()
        clean = re.sub(r"[?!.,;:]+$", "", lowered).strip()

        # Check for pure greetings inside sentence splits
        if re.match(r"^(?:hi|hello|hey|thanks|thank\s+you|cheers|bye)\b", clean) and len(clean.split()) <= 3:
            return True

        # Check for bot capability prompts
        if re.search(r"\b(?:what\s+can\s+you\s+help|what\s+can\s+you\s+do|help\s+me\b|who\s+are\s+you)\b", lowered):
            return True

        # Check for interrogative inquiries about status, current work, or completed work
        query_patterns = [
            r"^what\s+(?:am\s+i|are\s+my|is\s+my|should\s+i|have\s+i)\b",
            r"^what\s+(?:is|are|has|have|did|was|were)\s+[a-zA-Z0-9_\-\s]+(?:\s+(?:working\s+on|completed|finished|doing|handling|blocked\s+on|responsible\s+for|up\s+to))?\b",
            r"^what\s+tasks?\s+has\s+[a-zA-Z0-9_\-\s]+\s+(?:handled|completed|worked\s+on)\b",
            r"^who\s+(?:is|are|was|were)\s+[a-zA-Z0-9_\-\s]+$",
            r"^who\s+(?:is|are)\s+working\s+on\b",
            r"^(?:is|are|has|have|can|could|would|will|should)\s+anyone\b",
            r"^(?:any\s+updates?|any\s+news|any\s+blockers?)\b",
        ]
        for pat in query_patterns:
            if re.search(pat, clean):
                return True

        # If it ends with ? and starts with question word without affirmative work declaration
        if s.endswith("?") or "?" in s:
            if re.match(r"^(?:what|who|when|where|why|how|which|whose|is|are|has|have|can|could|would|will|do|does|did)\b", clean):
                if not re.search(r"\b(?:i\s+(?:am|have|had|will|'ve|'m|'ll|started|completed)|the\s+.*(?:is|are)\s+(?:deployed|complete|done|blocked))\b", lowered):
                    return True

        return False

    def _extract_from_communication(
        self,
        comm: CommunicationEvent,
        target_ids: set[str],
        target_name: str,
    ) -> list[ExtractedWorkItem]:
        body = (comm.content.body or "").strip()
        if not body or self._is_ignorable_message(body):
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
                sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", body) if s.strip()]
                for s in sentences:
                    classified = self._classify_statement(s)
                    if not classified:
                        continue
                    s_type, s_desc = classified
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
                            project=parent_topic,
                        )
                    )
                if items:
                    return items

            # Standalone message or direct statements
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", body) if s.strip()]
            for s in sentences:
                classified = self._classify_statement(s)
                if not classified:
                    continue
                s_type, s_desc = classified
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
            id_patterns = [rf"<@{re.escape(uid)}(?:\|[^>]+)?>" for uid in target_ids]
            name_pattern = re.escape(target_name) if target_name and len(target_name) >= 2 else ""

            target_tokens = id_patterns + ([name_pattern] if name_pattern else [])
            combined_token = "(?:" + "|".join(target_tokens) + ")"

            assign_match = re.search(
                rf"{combined_token}\s*[,:]?\s*(?:please|kindly|could you|can you)\s+(.+)$",
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
                # Merely mentioned or discussed
                # Only include if substantive project discussion, NOT a question or greeting to the employee
                if not self._is_interrogative_or_non_work(body) and len(body.split()) >= 4:
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

    def _classify_statement(self, sentence: str) -> tuple[WorkActivityType, str] | None:
        s = sentence.strip()
        if self._is_interrogative_or_non_work(s):
            return None

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
        if re.search(
            r"\b(?:i\s+will\s+start|i'll\s+start|i\s+will|i'll|i\s+plan\s+to|planning\s+to|i\s+shall|going\s+to\s+start|will\s+handle|will\s+take\s+care|commit\s+to)\b",
            lowered,
        ):
            return WorkActivityType.COMMITMENT, self._clean_topic_phrase(s)

        # 3. Completed work (Scenario A, E)
        if re.search(
            r"\b(?:have\s+completed|is\s+complete|are\s+complete|completed|have\s+finished|finished|passed\s+all\s+tests|is\s+done|are\s+done|has\s+passed|is\s+now\s+deployed|deployed|have\s+fixed|fixed|resolved|has\s+been\s+fixed|have\s+resolved)\b",
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
            r"\b(?:i\s+am\s+implementing|currently\s+implementing|implementing|i\s+am\s+working\s+on|working\s+on|i\s+am\s+refining|refining|building|developing|handling|still\s+need\s+to|need\s+to|have\s+started|started|validating|testing|i\s+am\s+preparing|preparing)\b",
            lowered,
        ):
            return WorkActivityType.ACTIVE_WORK, self._clean_topic_phrase(s)

        # 6. Substantive factual statement defaults to recent discussion
        if len(s.split()) >= 3 and not s.endswith("?"):
            return WorkActivityType.RECENT_DISCUSSION, self._clean_topic_phrase(s)

        return None

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
        cleaned = re.sub(
            r"^(?:i\s+am\s+|i'm\s+|i\s+have\s+|i've\s+|i\s+will\s+|i'll\s+|currently\s+|we\s+need\s+to\s+|please\s+)",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        return cleaned[:120] if cleaned else text[:120]

    def _consolidate_and_rank(self, items: list[ExtractedWorkItem]) -> list[ExtractedWorkItem]:
        """
        Deduplicate items, group related updates under common workstreams,
        and apply recency precedence.
        """
        if not items:
            return []

        # Sort items by timestamp ascending so newer updates process last
        sorted_items = sorted(
            items,
            key=lambda x: x.timestamp or datetime.min.replace(tzinfo=timezone.utc),
        )

        consolidated_map: dict[str, ExtractedWorkItem] = {}

        # Project workstreams to group related updates together
        workstreams = [
            ("POLIS production deployment", ["polis", "deployment", "deployed", "docker", "production", "slack integration"]),
            ("Canva graphics generation", ["canva", "graphics", "prompts"]),
            ("IVAN QA workflow", ["ivan", "qa", "testing personas"]),
            ("Calendar Agent", ["calendar agent", "calendar"]),
            ("Organizational Event Engine", ["event engine", "organizational event"]),
            ("API integration", ["api integration", "api credentials"]),
            ("PDF preview improvements", ["pdf preview", "pdf"]),
            ("email OTP verification flow", ["email otp", "email verification", "otp verification", "booking workflow", "otp timeout", "verification flow", "otp"]),
            ("knowledge base and shortlinks", ["knowledge base", "shortlink", "shortlinks", "shortlink accuracy"]),
            ("PolisBot governance", ["governance", "accountability", "polisbot"]),
        ]

        for item in sorted_items:
            item_text = (item.work_item + " " + item.latest_update).lower()
            ws_key = None
            for name, keywords in workstreams:
                if any(kw in item_text for kw in keywords):
                    ws_key = name
                    break

            norm_key = ws_key or self._normalize_item_key(item.work_item)
            if not norm_key:
                continue

            matching_key = None
            if norm_key in consolidated_map:
                matching_key = norm_key
            else:
                norm_tokens = set(norm_key.split())
                for k, existing_item in consolidated_map.items():
                    # Thread or parent project match connects related updates
                    if item.project and existing_item.project and item.project.lower() == existing_item.project.lower():
                        matching_key = k
                        break
                    k_tokens = set(k.split())
                    union = norm_tokens | k_tokens
                    if not union:
                        continue
                    jaccard = len(norm_tokens & k_tokens) / len(union)
                    common = norm_tokens & k_tokens
                    if jaccard >= 0.35 or len(common) >= 2:
                        matching_key = k
                        break

            if matching_key:
                existing = consolidated_map[matching_key]
                # Preserve and append updates
                all_updates = existing.updates + [item.latest_update]
                item.updates = all_updates

                # Preserve the established project / topic title if the newer update is a progress update
                canonical_markers = (
                    "canva", "polis", "event engine", "calendar", "ivan", "api",
                    "email", "otp", "verification", "knowledge", "governance"
                )
                if ws_key:
                    if any(k in existing.work_item.lower() for k in canonical_markers):
                        item.work_item = existing.work_item
                    else:
                        item.work_item = ws_key
                elif any(k in existing.work_item.lower() for k in canonical_markers):
                    if not any(k in item.work_item.lower() for k in canonical_markers):
                        item.work_item = existing.work_item

                # If newer update is COMPLETED, update state to completed
                if item.activity_type == WorkActivityType.COMPLETED_WORK:
                    consolidated_map[matching_key] = item
                # If newer update is ACTIVE, keep newer active update
                elif item.activity_type == WorkActivityType.ACTIVE_WORK:
                    consolidated_map[matching_key] = item
                # If newer update is BLOCKER, prioritize blocker
                elif item.activity_type == WorkActivityType.BLOCKER:
                    consolidated_map[matching_key] = item
                else:
                    if (item.timestamp or datetime.min.replace(tzinfo=timezone.utc)) >= (existing.timestamp or datetime.min.replace(tzinfo=timezone.utc)):
                        consolidated_map[matching_key] = item
            else:
                item.updates = [item.latest_update]
                consolidated_map[norm_key] = item

        # Return sorted by recency descending (newest first)
        return sorted(
            consolidated_map.values(),
            key=lambda x: x.timestamp or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    @staticmethod
    def _normalize_item_key(text: str) -> str:
        words = re.findall(r"\b[a-zA-Z0-9_-]+\b", text.lower())
        stop = {
            "i", "am", "the", "a", "an", "is", "are", "complete", "completed", "working",
            "on", "start", "to", "for", "in", "it", "old", "new", "current", "latest",
            "recent", "changes", "change", "update", "updates", "task", "tasks",
        }
        meaningful = [w for w in words if w not in stop]
        return " ".join(sorted(meaningful)) if meaningful else " ".join(words)

    @staticmethod
    def _determine_query_focus(query_text: str | None) -> str:
        if not query_text:
            return "current_work"
        lowered = query_text.lower()
        if re.search(r"\b(?:what\s+has\s+changed|what\s+changed|changes?|diff)\b", lowered):
            return "changes"
        if re.search(r"\b(?:pending|remaining|still\s+(?:open|in\s+progress|ongoing)|outstanding)\b", lowered):
            return "pending"
        if re.search(r"\b(?:progress|how\s+far|advancement|status\s+update)\b", lowered):
            return "progress"
        if any(w in lowered for w in ("blocked", "blocker", "dependency", "dependencies", "obstacle", "impediment", "waiting on")):
            return "blockers"
        if re.search(r"\b(?:completed|finished|shipped|closed|what\s+(?:has|did)\s+[a-zA-Z0-9_.-]+\s+(?:complete|finish|done))\b", lowered):
            return "completed"
        if any(w in lowered for w in ("assigned", "assigned to", "delegated", "responsibilities", "responsible for")):
            return "assigned"
        if any(w in lowered for w in ("summary", "priorities", "priority", "overview")):
            return "summary_and_priorities"
        return "current_work"

    def synthesize_response(
        self,
        summary: PersonWorkSummary,
        query_text: str | None = None,
        is_self: bool = False,
    ) -> str:
        """
        Synthesize a natural, humanized response using the configured LLM client
        or falling back gracefully to a clean, structured deterministic response.
        """
        query_focus = self._determine_query_focus(query_text)
        summary.query_focus = query_focus
        summary.is_self = is_self

        has_any = bool(
            summary.active_work
            or summary.commitments
            or summary.assigned_work
            or summary.completed_work
            or summary.blockers
            or summary.discussions
        )
        if not has_any:
            target_ref = "you" if is_self else summary.person_name
            return (
                f"I searched organizational communications and tasks for {target_ref} "
                f"over the past {summary.time_window_days} days, but found no recent work activity, "
                "commitments, or discussions recorded during this period."
            )

        # Attempt LLM response synthesis if LLM client is available
        if self._llm_client is not None and hasattr(self._llm_client, "generate"):
            try:
                llm_response = self._synthesize_with_llm(
                    summary=summary,
                    query_text=query_text or "What are the recent work items and priorities?",
                    query_focus=query_focus,
                    is_self=is_self,
                )
                if llm_response and len(llm_response.strip()) > 20:
                    return llm_response.strip()
            except Exception as exc:
                logger.warning("LLM response synthesis failed, falling back to deterministic: %s", exc)

        return self._synthesize_deterministic_fallback(summary, query_focus, is_self)

    def _synthesize_with_llm(
        self,
        summary: PersonWorkSummary,
        query_text: str,
        query_focus: str,
        is_self: bool,
    ) -> str:
        evidence_lines: list[str] = []
        if summary.active_work:
            evidence_lines.append("Active Work & Workstreams:")
            for item in summary.active_work:
                evidence_lines.append(f"- Project: {item.work_item} | Latest update: {item.latest_update}")
        if summary.assigned_work:
            evidence_lines.append("Assigned Tasks:")
            for item in summary.assigned_work:
                evidence_lines.append(f"- Task: {item.work_item} | Details: {item.latest_update}")
        if summary.commitments:
            evidence_lines.append("Upcoming Commitments / Planned Work:")
            for item in summary.commitments:
                evidence_lines.append(f"- Commitment: {item.work_item} | Details: {item.latest_update}")
        if summary.completed_work:
            evidence_lines.append("Recently Completed Work:")
            for item in summary.completed_work:
                evidence_lines.append(f"- Completed: {item.work_item} | Details: {item.latest_update}")
        if summary.blockers:
            evidence_lines.append("Blockers & Dependencies:")
            for item in summary.blockers:
                evidence_lines.append(f"- Blocker: {item.work_item} | Details: {item.latest_update}")
        if summary.discussions:
            evidence_lines.append("Recent Discussions (without confirmed ownership):")
            for item in summary.discussions[:3]:
                evidence_lines.append(f"- Discussion: {item.work_item}")

        structured_evidence = "\n".join(evidence_lines)
        target_desc = f"{summary.person_name} (the user themselves)" if is_self else summary.person_name

        prompt = f"""You are POLIS, a knowledgeable, helpful human colleague and organizational intelligence assistant.
Communicate naturally like a human colleague—NOT like a database search engine, mechanical reporter, or raw transcript dump.

User question: {query_text}
Target person: {target_desc}
Query focus: {query_focus}
Time window: past {summary.time_window_days} days

Structured Work Evidence:
{structured_evidence}

Core Instructions:
1. Speak naturally and conversationally, directly addressing what the user asked.
2. Form a complete, coherent understanding of workstreams (e.g. connected problem, assignment, and completion confirmations).
3. Distinguish clearly between:
   - Confirmed completed work
   - Ongoing active work
   - Assigned tasks and commitments
   - Blockers and dependencies
4. Never confuse a question about someone's work with evidence that they performed that work.
5. If information is incomplete or unverified, acknowledge it conversationally (e.g., "I can see that [Person] has been involved in [Work], but I couldn't find a clear update confirming whether the remaining tasks have been completed.").
6. If the user asks specifically about completed work, focus on verified completions. If they ask about current work, highlight ongoing focus and note completed work in proper context.
7. Avoid unnecessary channel names, raw IDs, status codes, or explanations of how information was retrieved.
8. If the user asks about themselves ("What am I working on?", "my priorities"), address them directly in the second person ("You have been focusing on..."). If asking about a colleague, use their name ("Hemant has been focusing on...").
9. Where structured formatting helps readability, organize with clean headers and bullet points:
   - Short natural opening statement.
   - **Current Work**
   - **Assigned Work and Commitments**
   - **Recently Completed**
   - **Blockers and Dependencies**
   - **Overall Priorities**

Return ONLY the natural response.
"""
        return self._llm_client.generate(prompt)

    def _synthesize_deterministic_fallback(
        self,
        summary: PersonWorkSummary,
        query_focus: str,
        is_self: bool,
    ) -> str:
        sections: list[str] = []

        if query_focus == "blockers":
            if summary.blockers:
                intro = "Here are the blockers and dependencies identified for your work:" if is_self else f"Here are the blockers and dependencies identified for {summary.person_name}:"
                sections.append(intro)
                lines = ["**Blockers and Dependencies**"]
                for b in summary.blockers:
                    lines.append(f"• **{b.work_item}** — {b.latest_update}")
                sections.append("\n".join(lines))
            else:
                target_str = "your work" if is_self else f"{summary.person_name}'s work"
                sections.append(f"There are currently no recorded blockers or dependencies impeding {target_str}.")
            return "\n\n".join(sections)

        elif query_focus == "completed":
            if summary.completed_work:
                intro = "Here is a summary of the work you have recently completed:" if is_self else f"Here is a summary of the work {summary.person_name} has recently completed:"
                sections.append(intro)
                lines = ["**Recently Completed**"]
                for c in summary.completed_work:
                    lines.append(f"• **{c.work_item}** — {c.latest_update}")
                sections.append("\n".join(lines))
                if summary.active_work:
                    ref_name = "Your" if is_self else f"{summary.person_name}'s"
                    sections.append(f"{ref_name} other work, including {summary.active_work[0].work_item}, appears to be ongoing.")
            else:
                target_str = "you" if is_self else summary.person_name
                if summary.active_work:
                    sections.append(
                        f"I checked recent records for {target_str}, but found no confirmed completed tasks in the past {summary.time_window_days} days. "
                        f"Work on {summary.active_work[0].work_item} appears to be ongoing."
                    )
                else:
                    sections.append(
                        f"I checked recent records for {target_str}, but found no confirmed completed tasks in the past {summary.time_window_days} days."
                    )
            return "\n\n".join(sections)

        elif query_focus == "pending":
            pending_items = summary.active_work + summary.assigned_work + summary.commitments + summary.blockers
            if pending_items:
                intro = "Here is the pending and ongoing work identified for your projects:" if is_self else f"Here is the pending and ongoing work identified for {summary.person_name}:"
                sections.append(intro)
                if summary.active_work:
                    lines = ["**Current Work**"]
                    for item in summary.active_work:
                        lines.append(f"• **{item.work_item}** — {item.latest_update}")
                    sections.append("\n".join(lines))
                combined_commitments = summary.assigned_work + summary.commitments
                if combined_commitments:
                    lines = ["**Assigned Work and Commitments**"]
                    for item in combined_commitments:
                        deadline_str = f" (Deadline: {item.deadline})" if item.deadline else ""
                        lines.append(f"• **{item.work_item}** — {item.latest_update}{deadline_str}")
                    sections.append("\n".join(lines))
                if summary.blockers:
                    lines = ["**Blockers and Dependencies**"]
                    for item in summary.blockers:
                        lines.append(f"• **{item.work_item}** — {item.latest_update}")
                    sections.append("\n".join(lines))
            else:
                target_str = "you" if is_self else summary.person_name
                sections.append(f"There are currently no pending tasks or active work recorded for {target_str}; all recent work appears to have been completed.")
            return "\n\n".join(sections)

        elif query_focus == "assigned":
            combined_assigned = summary.assigned_work + summary.commitments
            if combined_assigned:
                intro = "Here are the tasks currently assigned to you:" if is_self else f"Here are the tasks currently assigned to {summary.person_name}:"
                sections.append(intro)
                lines = ["**Assigned Work and Commitments**"]
                for item in combined_assigned:
                    deadline_str = f" (Deadline: {item.deadline})" if item.deadline else ""
                    lines.append(f"• **{item.work_item}** — {item.latest_update}{deadline_str}")
                sections.append("\n".join(lines))
            else:
                target_str = "you" if is_self else summary.person_name
                sections.append(f"There are no explicit task assignments recorded for {target_str} in the past {summary.time_window_days} days.")
            return "\n\n".join(sections)

        # General summary / current work / progress / changes
        if is_self:
            intro = "Here is a summary of your current work and priorities:"
        else:
            intro = f"Here is a summary of recent work and priorities for {summary.person_name}:"
        sections.append(intro)

        if summary.active_work:
            lines = ["**Current Work**"]
            for item in summary.active_work:
                desc = item.latest_update if item.latest_update and item.latest_update.lower() != item.work_item.lower() else "Active work"
                lines.append(f"• **{item.work_item}** — {desc}")
            sections.append("\n".join(lines))

        combined_commitments = summary.assigned_work + summary.commitments
        if combined_commitments:
            lines = ["**Assigned Work and Commitments**"]
            for item in combined_commitments:
                deadline_str = f" (Deadline: {item.deadline})" if item.deadline else ""
                lines.append(f"• **{item.work_item}** — {item.latest_update}{deadline_str}")
            sections.append("\n".join(lines))

        if summary.completed_work:
            lines = ["**Recently Completed**"]
            for item in summary.completed_work:
                lines.append(f"• **{item.work_item}** — {item.latest_update}")
            sections.append("\n".join(lines))

        if summary.blockers:
            lines = ["**Blockers and Dependencies**"]
            for item in summary.blockers:
                lines.append(f"• **{item.work_item}** — {item.latest_update}")
            sections.append("\n".join(lines))

        if summary.discussions and not summary.active_work:
            lines = ["**Recent Discussions**"]
            for item in summary.discussions[:3]:
                lines.append(f"• **{item.work_item}**")
            sections.append("\n".join(lines))

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

        if summary.completed_work and summary.active_work:
            ref_name = "His" if not is_self else "Your"
            sections.append(f"The {summary.completed_work[0].work_item} fixes have also been completed, according to the latest recorded updates. {ref_name} other work appears to be ongoing.")

        return "\n\n".join(sections)

    def format_summary_response(self, summary: PersonWorkSummary) -> str:
        """
        Produce a humanized, structured response for the given summary.
        Maintains backward compatibility with previous callers.
        """
        return self.synthesize_response(
            summary=summary,
            query_text=summary.query_focus,
            is_self=summary.is_self,
        )
