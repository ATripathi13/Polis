from __future__ import annotations

from domain.observation.rules.timestamp_utils import resolve_occurred_at

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)

from domain.observation.enums import (
    ObservationType,
)

from domain.observation.rules import (
    ObservationRule,
)

from domain.observation.value_objects import (
    Observation,
)


class OperationalObservationRule(
    ObservationRule,
):
    """
    Detects operational tasks, decisions, and risks
    from organizational communications.
    """

    def __init__(
        self,
        operational_understanding,
    ) -> None:
        self._operational_understanding = (
            operational_understanding
        )

    @property
    def priority(self) -> int:
        return 40

    @staticmethod
    def _is_conversational_or_bot_query(text: str) -> bool:
        """
        Detect whether a message is an assistance/capability query to POLIS
        or a casual conversational acknowledgment rather than an operational task.
        """
        import re

        lowered = " ".join(text.lower().strip().split())

        # Questions directed to POLIS regarding what it can do or conversational queries
        bot_query_patterns = (
            r"^(?:can\s+you\s+(?:tell|help|show|guide|explain|answer)|what\s+can\s+you|how\s+can\s+you|how\s+do\s+i|what\s+do\s+you\s+do)\b",
            r"^can\s+you\s+help\s+me\s+follow\s+up\s+on\s+a\s+pending\s+task\??$",
            r"^can\s+you\s+tell\s+me\s+what\s+you\s+can\s+help\s+me\s+with\??$",
        )
        if any(re.search(pat, lowered) for pat in bot_query_patterns):
            return True

        # Conversational acknowledgments without an actionable operational deliverable
        ack_patterns = (
            r"^ok(?:ay)?(?:\s+sir)?\s*(?:i\s+will\s+check(?:\s+with\s+it)?|noted|thanks|thank\s+you)?[\.!]?$",
            r"^(?:thanks|thank\s+you|got\s+it|noted|sure|understood)[\.!]?$",
        )
        if any(re.search(pat, lowered) for pat in ack_patterns):
            return True

        return False

    @staticmethod
    def _is_organization_wide(text: str) -> bool:
        """Check if message represents an organization-wide notice or holiday."""
        import re

        lowered = text.lower()
        org_tokens = (
            "for the whole organization",
            "for the organization",
            "whole organization",
            "company calendar entry",
            "company-wide",
            "organization-wide",
            "all employees",
            "company holiday schedule",
            "company holiday calendar",
            "company holiday announcement",
        )
        if any(token in lowered for token in org_tokens):
            return True

        holiday_org_patterns = (
            r"\bcompany\s+holiday\s+(?:schedule|calendar|announcement|list)\b",
            r"\b(?:schedule|calendar|announcement|list)\s+of\s+company\s+holidays\b",
        )
        return any(re.search(pat, lowered) for pat in holiday_org_patterns)

    def extract(
        self,
        communication: CommunicationEvent,
    ) -> list[Observation]:
        import re

        text = communication.content.body.strip()

        if not text:
            return []

        # 1. Deterministic screening against conversational false positives
        if self._is_conversational_or_bot_query(text):
            return []

        result = self._operational_understanding.analyze(
            text,
        )

        if not result.get("is_operational", False):
            return []

        type_mapping = {
            "task": ObservationType.TASK,
            "decision": ObservationType.DECISION,
            "risk": ObservationType.RISK,
        }

        observation_type = type_mapping.get(
            str(result.get("type", "")).lower()
        )

        if observation_type is None:
            return []

        summary = str(
            result.get("summary", text)
        ).strip()

        if not summary:
            return []

        confidence = float(
            result.get("confidence", 0.0)
        )

        # 2. Extract full actor and channel context from CommunicationEvent
        meta_actor = getattr(communication, "actor", None)
        actor_id = ""
        actor_name = ""
        actor_email = None
        actor_external_ids: dict[str, str] = {}
        if meta_actor is not None:
            identity = getattr(meta_actor, "identity", None)
            if identity is not None:
                actor_id = getattr(identity, "internal_id", "") or ""
                actor_external_ids = dict(getattr(identity, "external_ids", {}) or {})
            actor_name = getattr(meta_actor, "display_name", "") or ""
            actor_email = getattr(meta_actor, "email", None)

        meta_channel = getattr(communication, "channel", None)
        channel_id = ""
        channel_name = ""
        channel_type = ""
        if meta_channel is not None:
            ch_identity = getattr(meta_channel, "identity", None)
            if ch_identity is not None:
                channel_id = getattr(ch_identity, "internal_id", "") or ""
            channel_name = getattr(meta_channel, "name", "") or ""
            channel_type = getattr(meta_channel, "channel_type", "") or ""

        source_type = ""
        if hasattr(communication, "source") and communication.source is not None:
            source_type = (
                communication.source.value
                if hasattr(communication.source, "value")
                else str(communication.source)
            )

        # 3. Ownership and assignment cues
        # Deterministic classification: _is_organization_wide(text) is the sole authority
        is_org_wide = self._is_organization_wide(text)
        raw_ownership_type = str(result.get("ownership_type", "")).strip().lower()
        assignee = str(result.get("assignee", "")).strip()

        if is_org_wide:
            ownership_type = "organization_wide"
        else:
            # Deterministic classification failed -> cannot be organization-wide
            if raw_ownership_type == "organization_wide":
                ownership_type = ""
            else:
                ownership_type = raw_ownership_type

            if not ownership_type or ownership_type == "none":
                # Rule C / D: Delegation / instructing others -> author is not the owner
                delegation_match = re.search(
                    r"\bi\s+will\s+(?:instruct|tell|ask|assign|have|request)\s+([A-Za-z0-9_]+(?:\s+or\s+[A-Za-z0-9_]+)?)",
                    text,
                    re.IGNORECASE,
                )
                if delegation_match:
                    ownership_type = "unassigned"
                else:
                    # Rule A: Explicit assignment cues
                    assign_match = re.search(
                        r"^(?:<@([A-Z0-9]+)(?:\|[^>]+)?>|([A-Z][a-z]+)),?\s*(?:please|kindly|could you|can you|to)\b",
                        text,
                        re.IGNORECASE,
                    )
                    assign_to_match = re.search(
                        r"\b(?:assigning|assigned)\s+(?:this\s+)?to\s+(?:<@([A-Z0-9]+)(?:\|[^>]+)?>|([A-Z][a-z]+))\b",
                        text,
                        re.IGNORECASE,
                    )
                    if assign_match:
                        ownership_type = "explicit_assignment"
                        assignee = assign_match.group(1) or assign_match.group(2)
                    elif assign_to_match:
                        ownership_type = "explicit_assignment"
                        assignee = assign_to_match.group(1) or assign_to_match.group(2)
                    elif re.search(
                        r"^(?:i\s+will|i'll|i\s+am\s+going\s+to|i\s+shall)\s+[a-z]+",
                        text,
                        re.IGNORECASE,
                    ):
                        ownership_type = "self_commitment"
                    else:
                        ownership_type = "unassigned"

        metadata: dict[str, Any] = {
            "actor_id": actor_id,
            "actor_name": actor_name,
            "actor_email": actor_email,
            "actor_external_ids": actor_external_ids,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "channel_type": channel_type,
            "source_type": source_type,
            "source_event_id": communication.source_event_id,
            "ownership_type": ownership_type,
            "assignee": assignee,
            "is_organization_wide": is_org_wide,
            "scope": "organization" if is_org_wide else "personal",
            "original_text": text,
        }

        # Explicit owner metadata hints if clearly established
        if ownership_type == "self_commitment" and actor_id:
            metadata["owner_id"] = actor_id
            metadata["owner_name"] = actor_name
        elif ownership_type == "explicit_assignment" and assignee:
            metadata["assignee_name"] = assignee

        if "status" in result:
            metadata["status"] = result["status"]
        if "action" in result:
            metadata["action"] = result["action"]
        if "lifecycle" in result:
            metadata["lifecycle"] = result["lifecycle"]

        return [
            Observation(
                observation_type=observation_type,
                summary=summary,
                confidence=confidence,
                evidence=[
                    communication.source_event_id,
                ],
                correlation_id=getattr(communication, "correlation_id", None),
                occurred_at=resolve_occurred_at(communication),
                metadata=metadata,
            )
        ]
