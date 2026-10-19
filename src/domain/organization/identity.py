"""
Deterministic source event identity resolution for organizational events.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any

from domain.common.identifier import Identifier
from domain.organization.value_objects import OrganizationEvent


def _normalize_to_utc_iso(value: Any) -> str | None:
    """
    Parse a datetime, ISO-8601 string, or numeric epoch timestamp into
    a canonical UTC ISO-8601 string representation.

    Returns None if value is missing, invalid, or cannot be safely parsed.
    """
    if value is None:
        return None

    dt: datetime | None = None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            dt = value.replace(tzinfo=timezone.utc)
        else:
            dt = value.astimezone(timezone.utc)
    elif isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            return None
    elif isinstance(value, str):
        val_str = value.strip()
        if not val_str:
            return None

        # First, try ISO-8601 parsing (especially if date/time delimiters are present)
        if any(c in val_str for c in ("-", ":", "T", "Z")):
            try:
                cand_dt = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
                if cand_dt.tzinfo is None:
                    dt = cand_dt.replace(tzinfo=timezone.utc)
                else:
                    dt = cand_dt.astimezone(timezone.utc)
            except (TypeError, ValueError):
                dt = None

        # If not parsed as ISO-8601, try numeric epoch parsing
        if dt is None:
            try:
                epoch_val = float(val_str)
                dt = datetime.fromtimestamp(epoch_val, tz=timezone.utc)
            except (TypeError, ValueError, OverflowError, OSError):
                dt = None

        # Final fallback attempt for ISO formats without standard delimiters
        if dt is None:
            try:
                cand_dt = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
                if cand_dt.tzinfo is None:
                    dt = cand_dt.replace(tzinfo=timezone.utc)
                else:
                    dt = cand_dt.astimezone(timezone.utc)
            except (TypeError, ValueError):
                return None
    else:
        return None

    if dt is None:
        return None

    return dt.isoformat()


def derive_source_event_id(
    event: OrganizationEvent,
    *,
    source_type: str = "",
    correlation_id: str | Identifier | None = None,
    communication: Any = None,
) -> str | None:
    """
    Resolve or derive a deterministic source_event_id for an OrganizationEvent.

    Resolution hierarchy:
    1. Authoritative source_event_id on communication (if present and non-empty).
    2. Authoritative non-empty evidence string from any contributing observation.
    3. Explicit 'source_event_id' from observation metadata.
    4. Deterministic composite fallback:
       'synthetic:{source_type}:{correlation_id}:{occurred_at_utc_iso}:{actor_id}'
       (SHA256 digest if length exceeds 255 characters).
    5. Returns None if stable identity inputs are insufficient.
    """
    # 1. Authoritative source_event_id from communication
    if communication is not None and hasattr(communication, "source_event_id"):
        cand = communication.source_event_id
        if cand is not None and str(cand).strip():
            return str(cand).strip()

    # 2. Authoritative evidence from event observations
    if event.observations:
        for obs in event.observations:
            for ev in getattr(obs, "evidence", []) or []:
                if ev is not None and str(ev).strip():
                    return str(ev).strip()

    # 3. Observation metadata 'source_event_id'
    if event.observations:
        for obs in event.observations:
            meta = getattr(obs, "metadata", {}) or {}
            if "source_event_id" in meta and meta["source_event_id"]:
                cand = str(meta["source_event_id"]).strip()
                if cand:
                    return cand

    # 4. Deterministic fallback from stable architectural identity inputs
    # Container / Correlation identity (required)
    corr_val = correlation_id or event.correlation_id
    if corr_val is None and communication is not None:
        corr_val = getattr(communication, "correlation_id", None)
    if corr_val is None and event.observations:
        for obs in event.observations:
            if getattr(obs, "correlation_id", None) is not None:
                corr_val = obs.correlation_id
                break

    corr_str = None
    if isinstance(corr_val, Identifier):
        corr_str = corr_val.business_id or str(corr_val.graph_id)
    elif corr_val is not None:
        cand_str = str(corr_val).strip()
        if cand_str:
            corr_str = cand_str

    if not corr_str:
        return None

    # Temporal occurrence (required)
    occurred_val = event.occurred_at
    if occurred_val is None and event.observations:
        for obs in event.observations:
            if getattr(obs, "occurred_at", None) is not None:
                occurred_val = obs.occurred_at
                break
    if occurred_val is None and communication is not None:
        content = getattr(communication, "content", None)
        if content is not None:
            meta = getattr(content, "metadata", {}) or {}
            if "source_timestamp" in meta and meta["source_timestamp"]:
                occurred_val = meta["source_timestamp"]

    normalized_occurred_str = _normalize_to_utc_iso(occurred_val)
    if not normalized_occurred_str:
        return None

    # Actor / Author identity (required: non-empty stable actor/author identifier)
    actor_str = None
    if communication is not None and hasattr(communication, "actor"):
        actor = communication.actor
        if actor is not None:
            identity = getattr(actor, "identity", None)
            if identity is not None and getattr(identity, "internal_id", None):
                cand_actor = str(identity.internal_id).strip()
                if cand_actor:
                    actor_str = cand_actor
            if not actor_str and getattr(actor, "display_name", None):
                cand_actor = str(actor.display_name).strip()
                if cand_actor:
                    actor_str = cand_actor

    if not actor_str and event.observations:
        for obs in event.observations:
            meta = getattr(obs, "metadata", {}) or {}
            for k in ("actor_id", "speaker", "user_id", "author"):
                if k in meta and meta[k]:
                    cand_actor = str(meta[k]).strip()
                    if cand_actor:
                        actor_str = cand_actor
                        break
            if actor_str:
                break

    if not actor_str:
        return None

    src = (source_type or "").strip() or "unknown"
    raw_key = f"synthetic:{src}:{corr_str}:{normalized_occurred_str}:{actor_str}"

    if len(raw_key) > 255:
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        return f"synthetic:{src}:{digest[:40]}"

    return raw_key
