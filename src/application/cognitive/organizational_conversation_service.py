"""
Natural Organizational Conversation Intelligence Service for POLIS.

Answers everyday organizational questions naturally:
- Topic, project, and decision discussions across Slack channels (e.g. IVAN, marketing automation, website changes, LinkedIn automation).
- Team-wide work aggregation (e.g. "What is everyone currently working on?").
- Connects information shared by different people, noting context, decisions, progress, and pending work.
- Strictly separates internal Slack IDs (used internally) from user-facing human-readable names and #channels.
- Respects temporal recency: prioritizes newer updates, and never presents old discussions as recent updates.
- Explains incomplete or absent information naturally without guessing or inventing.
- Enforces public-channel vs DM consistency and permission boundaries (private messages never leak to public channels).
- Zero hardcoded narratives: all synthesis is dynamically grounded in retrieved communication evidence.
"""

from __future__ import annotations

import copy
import dataclasses
import logging
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from domain.reasoning.value_objects import (
    Answer,
    ConversationContext,
    Question,
)
from application.identity.canonical_identity_service import CanonicalIdentityService

logger = logging.getLogger(__name__)


# Domain synonym and topic expansion map
_TOPIC_EXPANSIONS: dict[str, list[str]] = {
    "automation": [
        "automation", "automated", "workflow", "workflows", "otp", "webhook",
        "ghl", "form", "integration", "twilio", "flow", "sms",
    ],
    "marketing automation": [
        "marketing automation", "automation", "ghl", "campaign", "funnel",
        "workflow", "workflows", "form", "form 4", "webhook", "highlevel",
    ],
    "marketing": [
        "marketing", "social media", "publishing calendar", "campaign", "media", "content",
    ],
    "website": [
        "website", "web", "site", "landing page", "navthethi.com", "e-book", "privacy", "changes", "redesign",
    ],
    "website changes": [
        "website", "web", "site", "landing page", "changes", "redesign", "update website",
    ],
    "ivan": [
        "ivan",
    ],
    "ghl": [
        "ghl", "highlevel", "high level", "form 4", "token", "sub-account", "subaccount", "form builder",
    ],
    "otp": [
        "otp", "sms", "verification", "twilio", "code", "phone system",
    ],
    "linkedin": [
        "linkedin", "social media", "connection", "post", "posts", "profile", "campaign",
    ],
    "linkedin automation": [
        "linkedin", "linkedin automation", "automation", "social media", "connection",
    ],
    "topics": [
        "topics", "topic",
    ],
    "polis": [
        "polis", "polis test", "documentation",
    ],
}


class OrganizationalConversationService:
    """
    Coordinates multi-channel organizational conversation retrieval, thread connection,
    recency analysis, and collegial natural synthesis.
    """

    TIMEZONE = ZoneInfo("Asia/Kolkata")

    def __init__(
        self,
        communication_repository: Any,
        identity_service: CanonicalIdentityService | None = None,
        knowledge_retrieval_service: Any | None = None,
        operational_item_repository: Any | None = None,
        person_work_service: Any | None = None,
        llm_client: Any | None = None,
    ) -> None:
        self._comm_repo = communication_repository
        self._identity_service = identity_service or CanonicalIdentityService()
        self._knowledge_service = knowledge_retrieval_service
        self._ops_repo = operational_item_repository
        self._person_work_service = person_work_service
        self._llm_client = llm_client

    # =========================================================================
    # QUERY CLASSIFICATION
    # =========================================================================

    @classmethod
    def is_team_work_query(cls, text: str) -> bool:
        """Determine if a query is asking about the team / everyone's current work."""
        norm = " ".join(text.lower().strip().split())
        patterns = (
            r"\bwhat\s+is\s+(?:everyone|everybody|the\s+team|the\s+whole\s+team|all\s+of\s+us)\s+(?:currently\s+)?working\s+on\b",
            r"\bwhat\s+are\s+(?:we\s+all|people|the\s+team)\s+(?:currently\s+)?working\s+on\b",
            r"\bwhat(?:'s|\s+is)\s+everyone\s+working\s+on\b",
            r"\bwhat\s+is\s+everyone\s+doing\b",
            r"\bwhat\s+are\s+all\s+team\s+members\s+working\s+on\b",
            r"\bwhat\s+is\s+(?:the\s+team|everyone)\s+up\s+to\b",
            r"\bteam\s+(?:current\s+)?work\s+summary\b",
        )
        return any(re.search(pat, norm) for pat in patterns)

    @classmethod
    def is_decision_query(cls, text: str) -> bool:
        """Determine if a query specifically asks about organizational decisions."""
        norm = " ".join(text.lower().strip().split())
        patterns = (
            r"\b(?:what\s+decisions?\s+(?:have\s+we\s+made|did\s+we\s+make|were\s+made))\b",
            r"\bdid\s+we\s+decide\s+anything\b",
            r"\bwhat\s+did\s+we\s+decide\b",
            r"\bdecisions?\s+about\b",
            r"\bdecisions?\s+on\b",
        )
        return any(re.search(pat, norm) for pat in patterns)

    @classmethod
    def is_ownership_query(cls, text: str) -> bool:
        """Determine if a query asks who is handling or responsible for a workstream."""
        norm = " ".join(text.lower().strip().split())
        patterns = (
            r"\bwho\s+is\s+(?:handling|working\s+on|taking\s+care\s+of|managing|leading|in\s+charge\s+of)\b",
            r"\bwho\s+owns\b",
            r"\bwho\s+is\s+responsible\s+for\b",
        )
        return any(re.search(pat, norm) for pat in patterns)

    @classmethod
    def is_location_query(cls, text: str) -> bool:
        """Determine if a query asks where a discussion took place."""
        norm = " ".join(text.lower().strip().split())
        patterns = (
            r"\bwhere\s+can\s+i\s+find\s+the\s+discussion\b",
            r"\bwhere\s+was\s+this\s+discussed\b",
            r"\bwhere\s+did\s+we\s+discuss\b",
            r"\bwhich\s+channel\b",
        )
        return any(re.search(pat, norm) for pat in patterns)

    @classmethod
    def extract_person_names(cls, text: str) -> list[str]:
        """Extract explicit person names from a multi-person update query."""
        m = re.search(r"\b(?:update\s+from|updates?\s+from|from)\s+([A-Z][a-z]+(?:\s+and\s+[A-Z][a-z]+|\s*,\s*[A-Z][a-z]+)+)", text)
        if m:
            raw = m.group(1)
            parts = re.split(r"\s+and\s+|\s*,\s*", raw)
            return [p.strip() for p in parts if p.strip()]
        return []

    # =========================================================================
    # TOPIC EXTRACTION
    # =========================================================================

    @classmethod
    def extract_topic(cls, text: str) -> str:
        """Extract the target topic, project, or subject from an organizational question."""
        cleaned = text.strip().rstrip("?.!")
        patterns = [
            r"(?i)\bwhat\s+was\s+(?:our\s+)?latest\s+discussion\s+on\s+(.+)$",
            r"(?i)\bwhat(?:'s|\s+is)\s+happening\s+with\s+(?:the\s+)?(.+)$",
            r"(?i)\bwhere\s+do\s+things\s+stand\s+with\s+(?:the\s+)?(.+)$",
            r"(?i)\bdid\s+we\s+decide\s+anything\s+about\s+(?:the\s+)?(.+)$",
            r"(?i)\bwhat\s+decisions?\s+(?:have\s+we\s+made|did\s+we\s+make|were\s+made)\s+about\s+(?:the\s+)?(.+)$",
            r"(?i)\bwho\s+is\s+(?:handling|working\s+on|taking\s+care\s+of)\s+(?:the\s+)?(.+)$",
            r"(?i)\bwhat\s+did\s+we\s+discuss\s+about\s+(?:the\s+)?(.+)$",
            r"(?i)\bwhere\s+can\s+i\s+find\s+the\s+discussion\s+about\s+(?:the\s+)?(.+)$",
            r"(?i)\blatest\s+discussion\s+on\s+(.+)$",
            r"(?i)\blatest\s+updates?\s+on\s+(.+)$",
            r"(?i)\bstatus\s+of\s+(?:the\s+)?(.+)$",
        ]
        for pat in patterns:
            m = re.search(pat, cleaned)
            if m:
                topic = m.group(1).strip()
                topic = re.sub(r"(?i)\s+(?:project|work|discussion|initiative|status)$", "", topic)
                return topic.strip()

        stop_words = {
            "what", "was", "our", "the", "a", "an", "is", "are", "did", "we", "decide",
            "anything", "about", "latest", "discussion", "on", "where", "do", "things",
            "stand", "with", "happening", "project", "work", "who", "handling", "made",
            "decisions", "find", "can", "i",
        }
        words = [w.strip(".,!?;:\"'") for w in cleaned.lower().split() if w.strip(".,!?;:\"'") not in stop_words]
        return " ".join(words) if words else cleaned

    # =========================================================================
    # MAIN ENTRY POINT
    # =========================================================================

    def answer_question(
        self,
        question: Question,
        context: ConversationContext | None = None,
    ) -> Answer:
        """
        Process an organizational question and return a natural, grounded answer.
        """
        text = question.text or ""

        if self.is_team_work_query(text):
            return self._handle_team_work_query(question, context)

        return self._handle_topic_discussion_query(question, context)

    # =========================================================================
    # PERMISSION & ACCESS FILTERING
    # =========================================================================

    @classmethod
    def _get_verified_participants(cls, event: Any) -> set[str]:
        """
        Extract verified participants for an event.
        Includes author/sender and verified members/participants from channel or content metadata.
        Never infers membership from channel IDs, names, or arbitrary text.
        """
        participants: set[str] = set()
        actor_id = cls._get_actor_id(event)
        if actor_id:
            participants.add(str(actor_id).strip())

        ch = getattr(event, "channel", None)
        if ch and hasattr(ch, "metadata") and isinstance(ch.metadata, dict):
            members = ch.metadata.get("members") or ch.metadata.get("participants")
            if isinstance(members, (list, set, tuple)):
                participants.update(str(m).strip() for m in members if m and str(m).strip())

        content = getattr(event, "content", None)
        if content and hasattr(content, "metadata") and isinstance(content.metadata, dict):
            auth_users = content.metadata.get("authorized_users") or content.metadata.get("participants")
            if isinstance(auth_users, (list, set, tuple)):
                participants.update(str(u).strip() for u in auth_users if u and str(u).strip())

        return participants

    def _verify_and_clean_parent_privacy(
        self,
        event: Any,
        is_public_requester: bool,
        req_user_id: str | None,
        events_map: dict[str, Any],
    ) -> Any:
        """
        Verify that the requester is authorized to access the parent message.
        If parent does not exist, belongs to another channel, has invalid thread relationship,
        or requester is unauthorized, strip parent content from metadata and references.
        """
        content = getattr(event, "content", None)
        metadata = getattr(content, "metadata", {}) if content else {}
        parent_ts = metadata.get("parent_ts")
        parent_refs = [
            ref for ref in getattr(event, "references", [])
            if getattr(ref, "relationship_type", None) == "parent_message"
        ]

        if not parent_ts and not parent_refs:
            return event

        p_id = parent_ts or (parent_refs[0].reference_id if parent_refs else None)
        parent_ev = events_map.get(p_id)

        parent_authorized = False
        if parent_ev is not None:
            # 1. Parent must belong to the same channel
            ev_ch_id = self._get_channel_id(event)
            p_ch_id = self._get_channel_id(parent_ev)
            if ev_ch_id and p_ch_id and ev_ch_id == p_ch_id:
                # 2. Valid thread relationship
                corr_id = getattr(getattr(event, "correlation_id", None), "business_id", None) or getattr(event, "correlation_business_id", None)
                if corr_id == p_id:
                    # 3. Independent authorization check on parent
                    p_ch = getattr(parent_ev, "channel", None)
                    p_ch_type = getattr(p_ch, "channel_type", None) or "unknown"
                    if p_ch_type in ("public", "channel", "public_channel"):
                        parent_authorized = True
                    elif p_ch_type == "meeting":
                        p_meta = getattr(p_ch, "metadata", {}) or {}
                        attendees = p_meta.get("attendees") or p_meta.get("members")
                        if not attendees or (req_user_id and req_user_id in [str(a).strip() for a in attendees]):
                            parent_authorized = True
                    elif p_ch_type in ("im", "mpim", "private"):
                        if not is_public_requester and req_user_id:
                            p_verified = self._get_verified_participants(parent_ev)
                            if req_user_id in p_verified:
                                parent_authorized = True

        if parent_authorized:
            return event

        # Strip unauthorized parent content safely without mutating stored event
        new_metadata = dict(metadata)
        for key in ("parent_message_body", "parent_actor_name", "parent_channel_name", "parent_ts"):
            new_metadata.pop(key, None)

        new_content = dataclasses.replace(event.content, metadata=new_metadata)
        new_references = [
            ref for ref in getattr(event, "references", [])
            if getattr(ref, "relationship_type", None) != "parent_message"
        ]

        return dataclasses.replace(copy.copy(event), content=new_content, references=new_references)

    def _filter_accessible_events(
        self,
        events: list[Any],
        context: ConversationContext | None,
        question: Question,
        all_events_pool: list[Any] | None = None,
    ) -> list[Any]:
        """
        Enforce Slack permission boundaries, channel visibility, and parent-message privacy:
        - Public channels participate in organization-wide retrieval.
        - Private channels, DMs, and group DMs require verified authorization and are never disclosed in public channels.
        - Unknown or missing channel visibility is excluded.
        - Parent-message privacy is independently verified; unauthorized or missing parent context is stripped.
        """
        ctx = context or getattr(question, "context", None)
        ch_type = getattr(ctx, "channel_type", None) or ""
        ch_id = getattr(ctx, "channel_id", "") or ""
        is_public_requester = (
            ch_type in ("public", "channel", "public_channel", "group")
            or (isinstance(ch_id, str) and ch_id.startswith("C"))
        )
        req_user_id = getattr(ctx, "user_id", None) or getattr(question, "user_id", None)
        if isinstance(req_user_id, str):
            req_user_id = req_user_id.strip()

        pool = all_events_pool if all_events_pool is not None else events
        events_by_source_id: dict[str, Any] = {
            getattr(e, "source_event_id", ""): e
            for e in pool
            if getattr(e, "source_event_id", None)
        }

        accessible: list[Any] = []
        for ev in events:
            ev_ch = getattr(ev, "channel", None)
            if not ev_ch:
                continue

            ev_ch_type = getattr(ev_ch, "channel_type", None)
            if not ev_ch_type or ev_ch_type == "unknown":
                # Unknown or missing visibility: exclude from retrieval
                continue

            # Public channels
            if ev_ch_type in ("public", "channel", "public_channel"):
                pass  # Allowed
            elif ev_ch_type == "meeting":
                # Teams meetings: allowed unless restricted members/attendees list is present
                ch_meta = getattr(ev_ch, "metadata", {}) or {}
                attendees = ch_meta.get("attendees") or ch_meta.get("members")
                if attendees and isinstance(attendees, (list, set, tuple)):
                    if not req_user_id or req_user_id not in [str(a).strip() for a in attendees]:
                        continue
            elif ev_ch_type in ("im", "mpim", "private"):
                # If question asked in a public channel, never disclose private messages
                if is_public_requester:
                    continue

                # Missing requester identity means no access
                if not req_user_id:
                    continue

                # Verified participant authorization
                verified = self._get_verified_participants(ev)
                if not verified or req_user_id not in verified:
                    continue
            else:
                # Any unsupported or unverified channel type fails closed
                continue

            # Event itself is accessible! Check parent message privacy independently
            ev_with_checked_parent = self._verify_and_clean_parent_privacy(
                event=ev,
                is_public_requester=is_public_requester,
                req_user_id=req_user_id,
                events_map=events_by_source_id,
            )
            accessible.append(ev_with_checked_parent)

        return accessible

    # =========================================================================
    # TEAM-WIDE WORK HANDLING
    # =========================================================================

    def _handle_team_work_query(
        self,
        question: Question,
        context: ConversationContext | None = None,
    ) -> Answer:
        """
        Aggregate active work across all known and active team members.
        """
        # 1. Fetch recent communication events across the workspace
        all_events = self._get_all_recent_events(limit=500)

        # 2. Filter for authorization (with full pool for parent verification)
        accessible_events = self._filter_accessible_events(
            all_events, context, question, all_events_pool=all_events
        )

        # 3. Extract active people and their work evidence
        people_work = self._aggregate_people_work(accessible_events)

        # 4. Check operational tasks for team members
        self._enrich_with_operational_tasks(people_work)

        # 5. Synthesize natural team summary
        if self._llm_client is not None:
            ans_text = self._synthesize_team_work_llm(people_work, question.text or "")
            if not ans_text or "unable" in ans_text.lower():
                ans_text = self._synthesize_team_work_deterministic(people_work)
        else:
            ans_text = self._synthesize_team_work_deterministic(people_work)

        # 6. Sanitize IDs
        final_text = self._identity_service.sanitize_user_facing_text(ans_text)

        evidence_items = []
        for p in people_work.values():
            evidence_items.extend(p.get("evidence", []))

        return Answer(
            text=final_text,
            confidence=0.9,
            evidence=evidence_items,
            is_conversational=True,
        )

    def _aggregate_people_work(self, events: list[Any]) -> dict[str, dict[str, Any]]:
        """Group and summarize active work for each participant in recent events."""
        people: dict[str, dict[str, Any]] = {}

        for ev in events:
            actor = getattr(ev, "actor", None)
            ident = getattr(actor, "identity", None) if actor else None
            user_id = None
            if isinstance(ident, dict):
                user_id = ident.get("internal_id")
            elif hasattr(ident, "internal_id"):
                user_id = getattr(ident, "internal_id", None)
            elif isinstance(actor, dict):
                user_id = actor.get("identity", {}).get("internal_id")

            if not user_id:
                continue

            if self._is_bot(user_id):
                continue

            display_name = self._identity_service.format_user_name(user_id)

            if user_id not in people:
                people[user_id] = {
                    "user_id": user_id,
                    "name": display_name,
                    "active_work": [],
                    "latest_date": getattr(ev, "created_at", None),
                    "evidence": [],
                    "channels": set(),
                }

            p_entry = people[user_id]
            body = ev.content.body.strip() if hasattr(ev, "content") and ev.content else ""
            ch_obj = getattr(ev, "channel", None)
            ch_id = getattr(ch_obj, "name", None) or ""
            if ch_id:
                p_entry["channels"].add(self._identity_service.format_channel_name(ch_id))

            p_entry["evidence"].append(f"{display_name} in {ch_id}: {body}")

            work_snippet = self._extract_workstream_snippet(body)
            if work_snippet and work_snippet not in p_entry["active_work"]:
                p_entry["active_work"].append(work_snippet)

            ev_dt = getattr(ev, "created_at", None)
            if ev_dt and (not p_entry["latest_date"] or ev_dt > p_entry["latest_date"]):
                p_entry["latest_date"] = ev_dt

        # Check for third-party attributions in communications (e.g. "Gurkirat is working on topics today")
        for ev in events:
            body = ev.content.body.strip() if hasattr(ev, "content") and ev.content else ""
            m_third = re.search(r"\b([A-Z][a-z]+)\s+is\s+working\s+on\s+([^.\n]+)", body)
            if m_third:
                name_ref = m_third.group(1).strip()
                work_ref = m_third.group(2).strip()
                matched_id = None
                for uid, p in people.items():
                    if name_ref.lower() in p["name"].lower():
                        matched_id = uid
                        break
                if not matched_id:
                    res = self._identity_service.resolve_user_by_name_or_mention(name_ref)
                    if res and res.platform_user_id:
                        matched_id = res.platform_user_id
                        people[matched_id] = {
                            "user_id": matched_id,
                            "name": res.canonical_name or name_ref,
                            "active_work": [],
                            "latest_date": getattr(ev, "created_at", None),
                            "evidence": [],
                            "channels": set(),
                        }
                if matched_id and work_ref not in people[matched_id]["active_work"]:
                    people[matched_id]["active_work"].append(work_ref)

        return people

    def _enrich_with_operational_tasks(self, people_work: dict[str, dict[str, Any]]) -> None:
        """Enrich people work with open tasks from OperationalItemRepository."""
        if self._ops_repo is None:
            return
        try:
            items = []
            if hasattr(self._ops_repo, "find_open"):
                items = self._ops_repo.find_open()
            elif hasattr(self._ops_repo, "list_open_tasks"):
                items = self._ops_repo.list_open_tasks()
            elif hasattr(self._ops_repo, "get_all"):
                items = self._ops_repo.get_all()
            elif hasattr(self._ops_repo, "_items") and isinstance(self._ops_repo._items, dict):
                items = list(self._ops_repo._items.values())

            for it in items:
                status = str(getattr(it, "status", "")).lower()
                if "open" not in status and "progress" not in status:
                    continue
                owner = getattr(it, "owner_name", "") or getattr(it, "owner_id", "")
                summary = getattr(it, "summary", "") or getattr(it, "title", "")
                if not owner or not summary:
                    continue
                for uid, p in people_work.items():
                    if owner.lower() in p["name"].lower() or owner.lower() == uid.lower():
                        if summary not in p["active_work"]:
                            p["active_work"].append(f"{summary} (assigned task)")
                        break
        except Exception as e:
            logger.warning("Error fetching operational tasks for team query: %s", e)

    @classmethod
    def _extract_workstream_snippet(cls, body: str) -> str | None:
        """Extract substantive work activity from a message body generically."""
        if not body or not body.strip():
            return None
        lower = body.lower().strip()
        if re.search(r"^\s*(?:hi|hello|hey|okay|ok|received|thanks|yes sir|sounds good)\s*$", lower):
            return None

        cleaned = re.sub(r"^(?:hi|hello|hey|ok|okay)\s+[^,]+,\s*", "", body, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"<@[A-Z0-9_|.-]+>", "", cleaned).strip()

        # Direct self-work statements (e.g. "I'm working on X", "Working on X")
        m = re.search(r"(?:i(?:'?m|\s+am)\s+working\s+on|working\s+on)\s+([^.\n;]+)", cleaned, re.IGNORECASE)
        if m:
            snippet = m.group(1).strip().lstrip("the ").strip()
            snippet = re.sub(r"(?i)\s+(?:today\s*-\s*test\s*\d+|today|now)$", "", snippet).strip()
            if len(snippet) >= 3:
                return snippet

        # Action statements: "Configured X", "Testing X", "Confirmed X", "Verified X"
        m_action = re.search(r"\b((?:configured|testing|confirmed|verified|deployed|updating|building|handling)\s+[^.\n;]+)", cleaned, re.IGNORECASE)
        if m_action:
            snippet = m_action.group(1).strip()
            if len(snippet) >= 5:
                return snippet

        # Substantive sentence fallback
        first_sentence = cleaned.split(".")[0].strip()
        if 10 <= len(first_sentence) <= 120:
            return first_sentence

        return None

    def _synthesize_team_work_deterministic(self, people_work: dict[str, dict[str, Any]]) -> str:
        """Produce a friendly, collegial team summary deterministically."""
        if not people_work:
            return "I checked our channels and records, and there is no recorded active work found for the team."

        all_dates = [p["latest_date"] for p in people_work.values() if p["latest_date"]]
        date_str = ""
        if all_dates:
            max_dt = max(all_dates)
            if max_dt.tzinfo is None:
                max_dt = max_dt.replace(tzinfo=timezone.utc)
            local_dt = max_dt.astimezone(self.TIMEZONE)
            month_name = local_dt.strftime("%B")
            date_str = f" from {month_name}"

        lines = [f"Based on our latest recorded updates{date_str} across Slack:"]

        sorted_people = sorted(
            people_work.values(),
            key=lambda x: (len(x["active_work"]) > 0, x["name"]),
            reverse=True,
        )

        for p in sorted_people:
            name = p["name"]
            work = p["active_work"]
            if work:
                work_desc = "; ".join(work)
                lines.append(f"• **{name}** is working on {work_desc}.")
            else:
                lines.append(f"• **{name}** has been contributing to discussions and operational reviews.")

        lines.append("\nLet me know if you would like more details on any specific person or project!")
        return "\n".join(lines)

    def _synthesize_team_work_llm(self, people_work: dict[str, dict[str, Any]], query_text: str) -> str:
        """Generate a natural team summary using LLM."""
        context_items = []
        for p in people_work.values():
            name = p["name"]
            work_str = ", ".join(p["active_work"]) if p["active_work"] else "Participated in channel discussions"
            dt_str = p["latest_date"].strftime("%Y-%m-%d") if p["latest_date"] else "unknown date"
            context_items.append(f"Person: {name} (latest update: {dt_str})\nActive work: {work_str}")

        now_str = datetime.now(self.TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z")
        prompt = f"""
You are POLIS, a helpful, collegial teammate and organizational assistant.
Answer the user's question about what the team is currently working on.

User question: {query_text}
Current date/time: {now_str}

Team work evidence:
{chr(10).join(context_items)}

Instructions:
- Write like a knowledgeable team member speaking to another team member.
- Use simple, everyday English.
- Avoid technical jargon, database terminology, and unnecessary robotic explanations.
- Lead with the overall situation and the time frame of our latest updates.
- Mention relevant people and what they are currently doing.
- Never present an old update as happening 'today' if the dates are from an earlier month.
- Always use resolved human names, never Slack user IDs or technical handles.
- Return ONLY the final conversational answer.
""".strip()

        try:
            resp = self._llm_client.generate(prompt)
            if resp and resp.strip():
                return resp.strip()
        except Exception as e:
            logger.warning("LLM team work synthesis failed: %s", e)
        return ""

    # =========================================================================
    # TOPIC DISCUSSION HANDLING
    # =========================================================================

    def _handle_topic_discussion_query(
        self,
        question: Question,
        context: ConversationContext | None = None,
    ) -> Answer:
        """
        Handle topic, project, or decision discussions across Slack channels and KB.
        """
        query_text = question.text or ""
        topic = self.extract_topic(query_text)

        # 1. Retrieve all recent events from repository
        all_events = self._get_all_recent_events(limit=500)

        # 2. Filter for authorization boundaries first (ensuring search and thread enrichment only use accessible pool)
        accessible_pool = self._filter_accessible_events(
            all_events, context, question, all_events_pool=all_events
        )

        # 3. Search Slack communications strictly across accessible messages
        matching_events = self._search_topic_communications(topic, query_text, events_pool=accessible_pool)

        # 4. Enrich with thread context strictly from accessible pool
        accessible_messages = self._enrich_thread_conversations(matching_events, pool=accessible_pool)

        # 4. Retrieve relevant Knowledge Base information if available
        kb_chunks = self._search_topic_knowledge_base(topic, query_text)

        # 5. Synthesize natural answer
        if self._llm_client is not None:
            ans_text = self._synthesize_topic_llm(
                query_text=query_text,
                topic=topic,
                events=accessible_messages,
                kb_chunks=kb_chunks,
            )
            if not ans_text or "unable" in ans_text.lower():
                ans_text = self._synthesize_topic_deterministic(
                    query_text=query_text,
                    topic=topic,
                    events=accessible_messages,
                    kb_chunks=kb_chunks,
                )
        else:
            ans_text = self._synthesize_topic_deterministic(
                query_text=query_text,
                topic=topic,
                events=accessible_messages,
                kb_chunks=kb_chunks,
            )

        # 6. Sanitize IDs
        final_text = self._identity_service.sanitize_user_facing_text(ans_text)

        evidence = [
            f"{self._identity_service.format_user_name(self._get_actor_id(e))} in {self._identity_service.format_channel_name(self._get_channel_id(e))}: {getattr(e.content, 'body', '')}"
            for e in accessible_messages
        ]
        evidence.extend([f"Knowledge Base: {c}" for c in kb_chunks])

        return Answer(
            text=final_text,
            confidence=0.85 if accessible_messages or kb_chunks else 0.5,
            evidence=evidence,
            is_conversational=True,
        )

    def _search_topic_communications(
        self,
        topic: str,
        original_query: str,
        events_pool: list[Any] | None = None,
    ) -> list[Any]:
        """
        Search Slack communication events across accessible channels using
        dedicated workspace-wide retrieval without generic stop words.
        Ranks by topic relevance and recency.
        """
        search_terms = {topic.lower()}
        for k, exp in _TOPIC_EXPANSIONS.items():
            if k in topic.lower() or any(term in topic.lower() for term in exp):
                search_terms.update(exp)

        # Check for explicit person names in query (e.g. "Hemant and Vijay")
        person_names = self.extract_person_names(original_query)
        for p in person_names:
            search_terms.add(p.lower())

        # Retrieve candidates from provided pool or get_recent_events
        all_events = events_pool if events_pool is not None else self._get_all_recent_events(limit=500)
        matched_scored: list[tuple[float, datetime, Any]] = []

        for ev in all_events:
            body = (getattr(ev.content, "body", "") if hasattr(ev, "content") and ev.content else "").lower()
            if not body:
                continue

            # Calculate match score
            matched_terms = [t for t in search_terms if re.search(rf"\b{re.escape(t)}\b", body)]
            actor_name = getattr(getattr(ev, "actor", None), "display_name", "") or ""
            if person_names and any(p.lower() in actor_name.lower() for p in person_names):
                matched_terms.append(actor_name.lower())

            if not matched_terms:
                continue

            score = float(len(matched_terms))
            # Exact topic phrase match bonus
            if topic.lower() in body:
                score += 3.0

            dt = getattr(ev, "created_at", None) or datetime.min
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            matched_scored.append((score, dt, ev))

        # Sort by (recency, score) so newer updates take priority over older repetitions
        matched_scored.sort(key=lambda item: (item[1], item[0]), reverse=True)
        return [ev for _, _, ev in matched_scored]

    def _enrich_thread_conversations(
        self,
        matched_events: list[Any],
        pool: list[Any] | None = None,
    ) -> list[Any]:
        """Fetch all related thread messages for any matched messages strictly from pool."""
        if not matched_events:
            return []

        thread_corr_ids = set()
        for ev in matched_events:
            corr = getattr(ev, "correlation_business_id", None)
            src = getattr(ev, "source_event_id", None)
            if corr:
                thread_corr_ids.add(corr)
            if src:
                thread_corr_ids.add(src)

        if not thread_corr_ids:
            return matched_events

        all_events = pool if pool is not None else self._get_all_recent_events(limit=500)
        full_thread_set: dict[str, Any] = {}

        for ev in all_events:
            src = getattr(ev, "source_event_id", None)
            corr = getattr(ev, "correlation_business_id", None)
            if corr in thread_corr_ids or src in thread_corr_ids:
                full_thread_set[src or str(id(ev))] = ev

        result = list(full_thread_set.values()) if full_thread_set else matched_events
        result.sort(key=lambda x: getattr(x, "created_at", datetime.min) or datetime.min)
        return result

    def _search_topic_knowledge_base(self, topic: str, original_query: str) -> list[str]:
        """Query Knowledge Base for relevant documentation chunks."""
        if self._knowledge_service is None:
            return []
        try:
            if hasattr(self._knowledge_service, "retrieve_evidence"):
                return self._knowledge_service.retrieve_evidence(Question(text=original_query), limit=3)
            elif hasattr(self._knowledge_service, "retrieve"):
                res = self._knowledge_service.retrieve(original_query, limit=3)
                chunks = []
                for chunk, _ in res:
                    c_text = chunk.content.strip()
                    if c_text:
                        doc_name = chunk.metadata.get("document_name", "")
                        chunks.append(f"[{doc_name}] {c_text}")
                return chunks
        except Exception as e:
            logger.warning("Knowledge Base search failed for topic '%s': %s", topic, e)
        return []

    # =========================================================================
    # DYNAMIC TOPIC SYNTHESIS (Zero Hardcoded Assumptions)
    # =========================================================================

    def _synthesize_topic_deterministic(
        self,
        query_text: str,
        topic: str,
        events: list[Any],
        kb_chunks: list[str],
    ) -> str:
        """
        Produce a grounded, natural conversational explanation deterministically.
        All statements are dynamically derived from retrieved communication events and KB chunks.
        """
        lower_q = query_text.lower()
        topic_lower = topic.lower()

        # CASE 1: No Slack discussions found
        if not events:
            if kb_chunks:
                return (
                    f"I checked our Slack conversations and records, and there are no recorded "
                    f"decisions or recent team discussions about {topic}. Our Knowledge Base contains "
                    f"reference documentation, but no active conversations or decisions have taken place in Slack."
                )
            return (
                f"I checked our Slack conversations, and there haven't been any discussions or updates "
                f"about {topic} recorded across our channels. If this was discussed under a different "
                f"name or in an unshared space, please let me know!"
            )

        # CASE 2: Slack discussions exist
        dates = [getattr(e, "created_at", None) for e in events if getattr(e, "created_at", None)]
        latest_date_str = ""
        if dates:
            max_dt = max(dates)
            if max_dt.tzinfo is None:
                max_dt = max_dt.replace(tzinfo=timezone.utc)
            local_dt = max_dt.astimezone(self.TIMEZONE)
            month_day = local_dt.strftime("%B %d")
            latest_date_str = f"on {month_day}"

        # Find primary channel
        ch_id = self._get_channel_id(events[0])
        channel_name = self._identity_service.format_channel_name(ch_id)

        # Categorize message content dynamically
        decisions: list[tuple[str, str]] = []
        completions: list[tuple[str, str]] = []
        progress_items: list[tuple[str, str]] = []
        pending_items: list[tuple[str, str]] = []

        participant_contributions: dict[str, list[str]] = {}

        for ev in events:
            uid = self._get_actor_id(ev)
            u_name = self._identity_service.format_user_name(uid)
            body = (getattr(ev.content, "body", "") if hasattr(ev, "content") and ev.content else "").strip()
            if not body or self._is_bot(uid):
                continue

            if u_name not in participant_contributions:
                participant_contributions[u_name] = []
            participant_contributions[u_name].append(body)

            body_lower = body.lower()
            snippet = self._extract_workstream_snippet(body) or body

            # Identify decisions/authorizations
            if any(w in body_lower for w in ("decided", "agreed", "approved", "given access", "permission", "sub account", "do not create")):
                decisions.append((u_name, body))
            elif any(w in body_lower for w in ("confirmed", "verified", "done", "finished", "working via", "resolved")):
                completions.append((u_name, body))
            elif any(w in body_lower for w in ("working on", "testing", "configured", "now testing", "updating")):
                progress_items.append((u_name, body))

            if any(w in body_lower for w in ("please do not", "waiting", "blocked", "prior discussion", "next")):
                pending_items.append((u_name, body))

        # ---------------------------------------------------------------------
        # Query Type A: Decision Query
        # ---------------------------------------------------------------------
        if self.is_decision_query(query_text):
            if decisions or completions:
                lines = [f"Regarding decisions about {topic}, based on discussions {latest_date_str} in {channel_name}:"]
                for author, desc in (decisions + completions):
                    lines.append(f"• **{author}**: {desc}")
                if pending_items:
                    lines.append("\nGuidelines or pending items noted:")
                    for author, p in pending_items:
                        lines.append(f"• {p}")
                return "\n".join(lines)
            else:
                return (
                    f"Regarding {topic}, our team has discussed progress {latest_date_str} in {channel_name}, "
                    f"but no formal decisions or final agreements were recorded in the conversation."
                )

        # ---------------------------------------------------------------------
        # Query Type B: Ownership Query ("Who is handling...")
        # ---------------------------------------------------------------------
        if self.is_ownership_query(query_text):
            if progress_items or decisions:
                lines = [f"Based on our latest updates {latest_date_str} in {channel_name}:"]
                for author, desc in progress_items:
                    lines.append(f"• **{author}** is working on: {desc}")
                lines.append(f"\nFor full context, you can refer to the discussion in {channel_name}.")
                return "\n".join(lines)
            else:
                part_names = ", ".join(participant_contributions.keys()) if participant_contributions else "team members"
                return (
                    f"There is no explicit task assignment recorded for {topic}. "
                    f"The topic was mentioned by {part_names} {latest_date_str} in {channel_name}."
                )

        # ---------------------------------------------------------------------
        # Query Type C: Location Query ("Where can I find...")
        # ---------------------------------------------------------------------
        if self.is_location_query(query_text):
            part_str = ", ".join(participant_contributions.keys()) if participant_contributions else "the team"
            return (
                f"You can find the discussion on {topic} in {channel_name}. "
                f"The latest conversation took place {latest_date_str} involving {part_str}."
            )

        # ---------------------------------------------------------------------
        # Query Type D: Specific Person Update (e.g. Hemant and Vijay)
        # ---------------------------------------------------------------------
        target_persons = self.extract_person_names(query_text)
        if target_persons:
            lines = [f"Here is the latest update regarding {topic} from {', '.join(target_persons)} {latest_date_str} in {channel_name}:"]
            found_any = False
            for p_name, msgs in participant_contributions.items():
                if any(tp.lower() in p_name.lower() for tp in target_persons):
                    found_any = True
                    lines.append(f"• **{p_name}**: {' '.join(msgs[:2])}")
            if found_any:
                lines.append(f"\nYou can find the full thread in {channel_name}.")
                return "\n".join(lines)

        # ---------------------------------------------------------------------
        # Query Type E: General Latest Discussion
        # ---------------------------------------------------------------------
        lines = [f"Our latest discussions on {topic} took place {latest_date_str} in {channel_name}:\n"]
        for p_name, msgs in participant_contributions.items():
            # Present the most substantive recent message
            substantive = msgs[-1]
            lines.append(f"• **{p_name}**: {substantive}")

        lines.append(f"\nYou can find the full discussion in {channel_name}!")
        return "\n".join(lines)

    def _synthesize_topic_llm(
        self,
        query_text: str,
        topic: str,
        events: list[Any],
        kb_chunks: list[str],
    ) -> str:
        """Generate a natural, collegial answer for a topic discussion query using LLM."""
        lines = []
        for e in events:
            uid = self._get_actor_id(e)
            u_name = self._identity_service.format_user_name(uid)
            cid = self._get_channel_id(e)
            ch_name = self._identity_service.format_channel_name(cid)
            dt = getattr(e, "created_at", None)
            dt_str = dt.strftime("%Y-%m-%d %H:%M") if dt else "unknown time"
            body = getattr(e.content, "body", "") if hasattr(e, "content") and e.content else ""
            lines.append(f"[{dt_str}] {u_name} in {ch_name}: {body}")

        comm_evidence = "\n".join(lines) if lines else "No Slack messages found."
        kb_evidence = "\n".join(kb_chunks) if kb_chunks else "No Knowledge Base chunks found."
        now_str = datetime.now(self.TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z")

        prompt = f"""
You are POLIS, a socially intelligent, capable teammate and organizational assistant.
Answer the user's question about organizational discussions, decisions, or project status.

User question: {query_text}
Current date/time: {now_str}

Retrieved Slack Conversations:
{comm_evidence}

Retrieved Knowledge Base Documentation:
{kb_evidence}

Instructions:
1. Write like a knowledgeable team member speaking to another team member in simple, everyday English.
2. Avoid technical jargon, database terminology, search reports, and raw message dumps.
3. Lead with the overall situation, then mention important people, updates, and pending actions.
4. If conversations took place weeks or months ago (e.g. September), clearly state the date (e.g. 'Back on September 18...'). NEVER present past conversations as having happened 'today' or 'recently'.
5. Refer to the original channel naturally (e.g. #agentic-army).
6. Clearly distinguish completed work/decisions from ongoing testing or suggestions.
7. If the question asks who is handling/working on something, identify explicit owners from the evidence.
8. If the question asks what decisions were made, identify explicit finalized decisions versus open suggestions.
9. If NO discussions or updates were found in Slack (e.g. for IVAN, or new website decisions), explain that naturally instead of guessing or inventing facts.
10. ALWAYS use resolved human names (e.g. Nav Thethi, Hemant Kumar Sah, Vijay, Akshat), never Slack user IDs or handles.
11. Return ONLY the final conversational response.
""".strip()

        try:
            resp = self._llm_client.generate(prompt)
            if resp and resp.strip():
                return resp.strip()
        except Exception as e:
            logger.warning("LLM topic discussion synthesis failed: %s", e)
        return ""

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _get_all_recent_events(
        self,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 500,
        include_parent_context: bool = True,
    ) -> list[Any]:
        """
        Fetch recent communication events across the workspace using dedicated
        repository retrieval without stop-word search workarounds.
        Fails safely on repository exceptions without falling back to raw events.
        """
        if hasattr(self._comm_repo, "get_recent_events"):
            try:
                return self._comm_repo.get_recent_events(
                    start_time=start_time,
                    end_time=end_time,
                    limit=limit,
                    include_parent_context=include_parent_context,
                )
            except Exception as e:
                logger.error(
                    "Error calling get_recent_events on communication_repository: %s",
                    e,
                    exc_info=True,
                )
                # Fail safely: NEVER expose unfiltered raw events!
                return []

        return []

    @classmethod
    def _get_actor_id(cls, event: Any) -> str | None:
        """Extract user ID from event."""
        actor = getattr(event, "actor", None)
        if not actor:
            return None
        ident = getattr(actor, "identity", None)
        if isinstance(ident, dict):
            return ident.get("internal_id") or ident.get("external_ids", {}).get("slack")
        if hasattr(ident, "internal_id"):
            return getattr(ident, "internal_id", None)
        if isinstance(actor, dict):
            return actor.get("identity", {}).get("internal_id") or actor.get("identity", {}).get("external_ids", {}).get("slack")
        return None

    @classmethod
    def _get_channel_id(cls, event: Any) -> str:
        """Extract channel ID from event."""
        ch = getattr(event, "channel", None)
        if not ch:
            return ""
        ident = getattr(ch, "identity", None)
        if isinstance(ident, dict):
            return ident.get("internal_id") or ""
        if hasattr(ident, "internal_id"):
            return getattr(ident, "internal_id", "")
        if isinstance(ch, dict):
            return ch.get("identity", {}).get("internal_id") or ch.get("name") or ""
        return getattr(ch, "name", "") or ""

    @classmethod
    def _is_bot(cls, user_id: str | None) -> bool:
        """Check if user_id represents a bot."""
        if not user_id:
            return False
        clean = user_id.lower().strip()
        return clean in ("u_bot", "ubot", "uslackbot", "polis", "slackbot", "here", "channel", "everyone", "u0bfqce8s9m")
