from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from .models import (
    CanonicalChannelIdentity,
    CanonicalEmployeeIdentity,
    IdentityResolutionStatus,
    PlatformType,
)

logger = logging.getLogger(__name__)

_DEFAULT_WORKSPACE_USERS: dict[str, dict[str, str]] = {
    "U0BB8T4BVEK": {"display_name": "Akshat", "real_name": "Akshat", "title": "AI Agent Implementor"},
    "U0BBHB87SJF": {"display_name": "Nav Thethi", "real_name": "Nav Thethi", "title": ""},
    "U0BBPU6400M": {"display_name": "Gurkirat Singh", "real_name": "Gurkirat Singh", "title": ""},
    "U0BBRSJCR7U": {"display_name": "Pravesh Verma", "real_name": "Pravesh Verma", "title": ""},
    "U0BBWLMNVGC": {"display_name": "Nishchay", "real_name": "Nishchay", "title": ""},
    "U0BMLJD003G": {"display_name": "Vijay", "real_name": "Vijay", "title": ""},
    "U0BU41F6CTD": {"display_name": "Hemant Kumar Sah", "real_name": "Hemant Kumar Sah", "title": ""},
    "U0C3EE6L8AE": {"display_name": "Vijay Sharma", "real_name": "Vijay Sharma", "title": ""},
    "U0C3J7DBX36": {"display_name": "Nishchay", "real_name": "Nishchay", "title": ""},
    "U0C3J7FJ1BN": {"display_name": "Akshat Tripathi", "real_name": "Akshat Tripathi", "title": ""},
}

_DEFAULT_WORKSPACE_CHANNELS: dict[str, str] = {
    "C0BG7NWMD6D": "agentic-army",
    "C0BBMKRD4R4": "agentic-army",
    "C0C3BGUGAFK": "testing",
}


class CanonicalIdentityService:
    """
    Canonical Identity Resolution Service for POLIS.

    Resolves platform-specific identifiers (Slack, Microsoft Teams)
    into canonical employee and channel representations while preserving
    external platform identities and strictly adhering to identity rules:
    - Never merge employees based solely on identical display names.
    - Never guess an employee mapping when multiple candidates exist (ambiguity).
    - Expose resolution status explicitly (RESOLVED, PROVISIONAL, UNRESOLVED, AMBIGUOUS).
    """

    def __init__(
        self,
        slack_identity_service: Any | None = None,
        directory_provider: Any | None = None,
    ) -> None:
        self._slack_identity_service = slack_identity_service
        self._directory_provider = directory_provider
        self._user_cache: dict[tuple[str, str], CanonicalEmployeeIdentity] = {}
        self._channel_cache: dict[tuple[str, str], CanonicalChannelIdentity] = {}
        self._channel_registry: dict[str, str] = dict(_DEFAULT_WORKSPACE_CHANNELS)
        self._email_to_canonical_id: dict[str, str] = {}
        self._platform_to_canonical_id: dict[tuple[str, str], str] = {}
        self._canonical_to_external_ids: dict[str, dict[str, str]] = {}

    def resolve_user(
        self,
        platform_user_id: str,
        platform: str = PlatformType.SLACK.value,
        display_name_hint: str | None = None,
        email_hint: str | None = None,
    ) -> CanonicalEmployeeIdentity:
        """
        Resolve a platform-specific user ID into a CanonicalEmployeeIdentity.
        Cross-platform consistency:
        - When verified email is present, maps to unified canonical POLIS internal ID: emp_{email}.
        - Platform-specific IDs (Slack U..., Teams 29:...) remain external identifiers.
        """
        if not platform_user_id or not platform_user_id.strip():
            return CanonicalEmployeeIdentity(
                internal_id="",
                canonical_name="",
                platform=platform,
                platform_user_id="",
                resolution_status=IdentityResolutionStatus.UNRESOLVED,
            )

        clean_user_id = platform_user_id.strip()
        cache_key = (platform, clean_user_id)
        if cache_key in self._user_cache:
            return self._user_cache[cache_key]

        now = datetime.now(timezone.utc)
        email = email_hint
        real_name = ""
        display_name = (display_name_hint or clean_user_id).strip()
        slack_username = ""

        # Live lookup for Slack
        if platform in (PlatformType.SLACK.value, "slack"):
            if self._slack_identity_service is not None:
                try:
                    users = self._slack_identity_service.get_workspace_users()
                    for u in users:
                        if u.get("id") == clean_user_id:
                            profile = u.get("profile", {}) or {}
                            display_name = (
                                profile.get("display_name")
                                or profile.get("real_name")
                                or u.get("real_name")
                                or u.get("name")
                                or clean_user_id
                            ).strip()
                            real_name = (u.get("real_name") or display_name).strip()
                            email = profile.get("email") or email_hint
                            slack_username = u.get("name", "")
                            break
                except Exception:
                    logger.warning(
                        "Failed to resolve Slack user ID '%s' via SlackIdentityService",
                        clean_user_id,
                        exc_info=True,
                    )

        if not real_name and clean_user_id in _DEFAULT_WORKSPACE_USERS:
            fallback_u = _DEFAULT_WORKSPACE_USERS[clean_user_id]
            display_name = fallback_u.get("display_name") or clean_user_id
            real_name = fallback_u.get("real_name") or display_name

        # Cross-platform canonical employee internal ID unification:
        norm_email = email.lower().strip() if email else ""
        if norm_email:
            canonical_id = self._email_to_canonical_id.get(norm_email) or f"emp_{norm_email}"
            self._email_to_canonical_id[norm_email] = canonical_id
            status = IdentityResolutionStatus.RESOLVED
        else:
            canonical_id = self._platform_to_canonical_id.get((platform, clean_user_id)) or clean_user_id
            is_name_resolved = bool(
                (real_name and not self._is_raw_id(real_name))
                or (display_name and not self._is_raw_id(display_name) and display_name != clean_user_id)
                or (display_name_hint and display_name_hint != clean_user_id)
            )
            status = (
                IdentityResolutionStatus.RESOLVED
                if (real_name and not self._is_raw_id(real_name))
                else (IdentityResolutionStatus.PROVISIONAL if is_name_resolved else IdentityResolutionStatus.UNRESOLVED)
            )

        # Maintain cross-platform mapping of external identifiers
        self._platform_to_canonical_id[(platform, clean_user_id)] = canonical_id
        ext_map = self._canonical_to_external_ids.setdefault(canonical_id, {})
        ext_map[platform] = clean_user_id

        canonical_name = real_name or display_name or clean_user_id

        metadata: dict[str, Any] = {
            "external_ids": dict(ext_map),
            "platform": platform,
            "platform_user_id": clean_user_id,
        }
        if slack_username:
            metadata["slack_username"] = slack_username

        identity = CanonicalEmployeeIdentity(
            internal_id=canonical_id,
            canonical_name=canonical_name,
            platform=platform,
            platform_user_id=clean_user_id,
            email=email,
            display_name=display_name,
            resolution_status=status,
            last_verified_at=now,
            metadata=metadata,
        )
        self._user_cache[cache_key] = identity
        return identity

    def get_all_identifiers_for_user(self, identifier: str) -> set[str]:
        """
        Return all known identifiers (canonical internal ID, platform user IDs, email)
        associated with the given user identifier across platforms.
        """
        if not identifier or not identifier.strip():
            return set()
        clean = identifier.strip()
        results = {clean}

        if clean in self._canonical_to_external_ids:
            results.update(self._canonical_to_external_ids[clean].values())

        for (plat, pid), cid in self._platform_to_canonical_id.items():
            if pid == clean or cid == clean:
                results.add(cid)
                results.add(pid)
                if cid in self._canonical_to_external_ids:
                    results.update(self._canonical_to_external_ids[cid].values())

        for em, cid in self._email_to_canonical_id.items():
            if cid in results or em == clean.lower():
                results.add(cid)
                results.add(em)

        return results

    def resolve_user_by_name_or_mention(
        self,
        query: str,
        platform: str = PlatformType.SLACK.value,
    ) -> CanonicalEmployeeIdentity | None:
        """
        Resolve an employee by name or explicit mention.
        Strict Rules:
        - If multiple employees match: return None (ambiguous; never guess).
        - If no employee matches: return None.
        - Mentions (<@U12345|name> or <@U12345>) resolve directly by user ID.
        """
        if not query or not query.strip():
            return None

        cleaned = query.strip()

        # Check explicit mention
        mention_match = re.search(r"<@([A-Z0-9]+)(?:\|[^>]+)?>", cleaned)
        if mention_match:
            user_id = mention_match.group(1)
            return self.resolve_user(user_id, platform=platform)

        # Check raw user ID pattern
        if (
            len(cleaned) >= 5
            and cleaned[0].upper() in ("U", "W")
            and all(c.isalnum() or c == "_" for c in cleaned[1:])
        ):
            return self.resolve_user(cleaned.upper(), platform=platform)

        # Name search via Slack identity service or directory provider
        candidates: list[dict] = []
        if self._slack_identity_service is not None:
            try:
                users = self._slack_identity_service.get_workspace_users()
                normalized_target = " ".join(cleaned.lower().split())

                exact_matches: list[dict] = []
                word_matches: list[dict] = []

                for u in users:
                    if u.get("deleted"):
                        continue
                    profile = u.get("profile", {}) or {}
                    disp = (profile.get("display_name") or "").strip().lower()
                    real = (u.get("real_name") or profile.get("real_name") or "").strip().lower()
                    uname = (u.get("name") or "").strip().lower()

                    names = {disp, real, uname}
                    names.discard("")

                    if normalized_target in names:
                        exact_matches.append(u)
                        continue

                    # Word-boundary match (e.g. 'Hemant' matching 'Hemant Sharma')
                    if any(
                        re.search(rf"\b{re.escape(normalized_target)}\b", n)
                        for n in names
                    ):
                        word_matches.append(u)

                if len(exact_matches) == 1:
                    matched_user = exact_matches[0]
                    return self.resolve_user(matched_user["id"], platform=platform)
                elif len(exact_matches) > 1:
                    logger.warning(
                        "Multiple exact employee matches found for '%s'; refusing to guess.",
                        cleaned,
                    )
                    return None

                if len(word_matches) == 1:
                    matched_user = word_matches[0]
                    return self.resolve_user(matched_user["id"], platform=platform)
                elif len(word_matches) > 1:
                    logger.warning(
                        "Multiple partial employee matches found for '%s'; refusing to guess.",
                        cleaned,
                    )
                    return None

            except Exception:
                logger.warning(
                    "Name-based directory resolution failed for query '%s'",
                    cleaned,
                    exc_info=True,
                )

        # Fallback to registered user cache and verified workspace users
        norm_target = " ".join(cleaned.lower().split())
        # Phase 1: Exact name matching
        exact_matches = set()
        for (plat, uid), ident in self._user_cache.items():
            names = {ident.canonical_name.lower().strip(), ident.display_name.lower().strip()}
            names.discard("")
            if norm_target in names:
                exact_matches.add(uid)
        for uid, info in _DEFAULT_WORKSPACE_USERS.items():
            names = {info.get("display_name", "").lower().strip(), info.get("real_name", "").lower().strip()}
            names.discard("")
            if norm_target in names:
                exact_matches.add(uid)

        if len(exact_matches) == 1:
            return self.resolve_user(list(exact_matches)[0], platform=platform)
        elif len(exact_matches) > 1:
            logger.warning("Ambiguous exact employee match for '%s'; refusing to guess.", cleaned)
            return None

        # Phase 2: Word-boundary matching (e.g. 'Hemant' matching 'Hemant Kumar Sah')
        # Never use loose substring matching (e.g. 'an' must NOT match 'Hemant')
        word_matches = set()
        pattern = re.compile(rf"\b{re.escape(norm_target)}\b", re.IGNORECASE)
        for (plat, uid), ident in self._user_cache.items():
            names = {ident.canonical_name.lower().strip(), ident.display_name.lower().strip()}
            names.discard("")
            if any(pattern.search(n) for n in names):
                word_matches.add(uid)
        for uid, info in _DEFAULT_WORKSPACE_USERS.items():
            names = {info.get("display_name", "").lower().strip(), info.get("real_name", "").lower().strip()}
            names.discard("")
            if any(pattern.search(n) for n in names):
                word_matches.add(uid)

        if len(word_matches) == 1:
            return self.resolve_user(list(word_matches)[0], platform=platform)
        elif len(word_matches) > 1:
            logger.warning("Ambiguous word-boundary employee match for '%s'; refusing to guess.", cleaned)
            return None

        return None

    def resolve_channel(
        self,
        platform_channel_id: str,
        platform: str = PlatformType.SLACK.value,
        channel_name_hint: str | None = None,
        is_private_hint: bool = False,
    ) -> CanonicalChannelIdentity:
        """
        Resolve a platform-specific channel ID into a CanonicalChannelIdentity.
        """
        if not platform_channel_id or not platform_channel_id.strip():
            return CanonicalChannelIdentity(
                platform=platform,
                platform_channel_id="",
                channel_name="",
                channel_type="unknown",
            )

        clean_channel_id = platform_channel_id.strip()
        cache_key = (platform, clean_channel_id)
        if cache_key in self._channel_cache:
            return self._channel_cache[cache_key]

        # Determine channel type and resolution
        is_resolved = False
        resolved_name = None
        if clean_channel_id in self._channel_registry:
            resolved_name = self._channel_registry[clean_channel_id]
            is_resolved = True
        elif channel_name_hint and not self._is_raw_id(channel_name_hint):
            resolved_name = channel_name_hint.lstrip("#").strip()
            is_resolved = True

        if clean_channel_id.startswith("D"):
            channel_type = "im"
            channel_name = resolved_name or channel_name_hint or f"dm-{clean_channel_id}"
        elif clean_channel_id.startswith("G"):
            channel_type = "mpim"
            channel_name = resolved_name or channel_name_hint or f"group-dm-{clean_channel_id}"
        elif clean_channel_id.startswith("C"):
            channel_type = "private" if is_private_hint else "public"
            channel_name = resolved_name or channel_name_hint or clean_channel_id
        elif platform in (PlatformType.TEAMS.value, "microsoft_teams"):
            channel_type = "meeting" if "meeting" in clean_channel_id.lower() else "channel"
            channel_name = resolved_name or channel_name_hint or clean_channel_id
        else:
            channel_type = "unknown"
            channel_name = resolved_name or channel_name_hint or clean_channel_id

        identity = CanonicalChannelIdentity(
            platform=platform,
            platform_channel_id=clean_channel_id,
            channel_name=channel_name,
            channel_type=channel_type,
            metadata={"external_id": clean_channel_id, "is_resolved": is_resolved},
        )
        self._channel_cache[cache_key] = identity
        return identity

    def register_user(
        self,
        canonical_name: str,
        platform_user_id: str,
        platform: str = PlatformType.SLACK.value,
    ) -> None:
        """Register a known user mapping."""
        if not platform_user_id or not platform_user_id.strip():
            return
        clean_id = platform_user_id.strip()
        clean_name = canonical_name.strip()
        identity = CanonicalEmployeeIdentity(
            internal_id=f"emp_{clean_id}",
            canonical_name=clean_name,
            platform=platform,
            platform_user_id=clean_id,
            display_name=clean_name,
            resolution_status=IdentityResolutionStatus.RESOLVED,
            metadata={"external_ids": {platform: clean_id}, "is_resolved": True},
        )
        self._user_cache[(platform, clean_id)] = identity
        self._platform_to_canonical_id[(platform, clean_id)] = f"emp_{clean_id}"

    def register_channel(self, channel_id: str, channel_name: str) -> None:
        """Register a known channel mapping."""
        if not channel_id or not channel_id.strip():
            return
        clean_id = channel_id.strip()
        clean_name = channel_name.strip().lstrip("#")
        self._channel_registry[clean_id] = clean_name
        self._channel_cache.pop((PlatformType.SLACK.value, clean_id), None)

    def get_channel_name(self, channel_id: str) -> str | None:
        """Return the resolved channel name without prefix, or None if unresolved."""
        if not channel_id:
            return None
        clean = channel_id.strip()
        identity = self.resolve_channel(clean)
        name = identity.channel_name
        if name and not self._is_raw_id(name) and identity.metadata.get("is_resolved", True):
            return name.lstrip("#").strip()
        return None

    def format_channel_name(self, channel_id: str) -> str:
        """
        Format a channel ID into its human-readable user-facing representation.
        Always returns a human name prefixed with '#' (e.g. #agentic-army).
        If unresolved, returns 'an unverified channel' and never exposes the raw ID.
        """
        if not channel_id:
            return "an unverified channel"
        clean = channel_id.strip()
        name = self.get_channel_name(clean)
        if name:
            return f"#{name}"
        return "an unverified channel"

    def format_user_name(self, user_id: str) -> str:
        """
        Format a user ID into its human-readable user-facing representation.
        Always returns the resolved person name.
        If unresolved, returns 'an unverified team member' and never exposes the raw ID.
        """
        if not user_id:
            return "an unverified team member"
        clean = user_id.strip()
        identity = self.resolve_user(clean)
        name = identity.canonical_name or identity.display_name
        if name and not self._is_raw_id(name) and identity.resolution_status != IdentityResolutionStatus.UNRESOLVED:
            return name
        return "an unverified team member"

    @classmethod
    def _is_raw_id(cls, val: str) -> bool:
        """Check whether a string represents a raw Slack or Teams platform identifier."""
        if not val or not isinstance(val, str):
            return False
        clean = val.strip().lstrip("#@").strip()
        return bool(re.fullmatch(r"[UWC][A-Z0-9]{7,}", clean) or clean.startswith("29:"))

    def sanitize_user_facing_text(self, text: str) -> str:
        """
        Ensure no raw Slack user IDs or channel IDs leak into user-facing conversational text.
        Replaces:
        - <@U...> or <@U...|name> -> @ResolvedName or 'an unverified team member'
        - <#C...> or <#C...|name> -> #ResolvedChannel or 'an unverified channel'
        - Bare U0... / W0... -> ResolvedName or 'an unverified team member'
        - Bare C0... -> #ResolvedChannel or 'an unverified channel'
        """
        if not text:
            return ""
        if not isinstance(text, str):
            text = str(text)

        def replace_user_mention(m):
            uid = m.group(1)
            label = m.group(2)
            res_name = self.format_user_name(uid)
            if res_name and res_name != "an unverified team member":
                return f"@{res_name}"
            if label and not self._is_raw_id(label) and label.lower() not in ("here", "channel", "everyone", "polis", "bot"):
                return f"@{label.strip()}"
            return "an unverified team member"

        def replace_channel_mention(m):
            cid = m.group(1)
            label = m.group(2)
            if label and not self._is_raw_id(label):
                return f"#{label.strip().lstrip('#')}"
            return self.format_channel_name(cid)

        # 1. Slack syntax mentions
        sanitized = re.sub(r"<@([A-Z0-9_.-]+)(?:\|([^>]+))?>", replace_user_mention, text)
        sanitized = re.sub(r"<#([A-Z0-9_.-]+)(?:\|([^>]+))?>", replace_channel_mention, sanitized)

        # 2. Bare channel IDs (C followed by 8+ alphanumeric chars)
        def replace_bare_channel(m):
            cid = m.group(0)
            return self.format_channel_name(cid)

        sanitized = re.sub(r"\bC[A-Z0-9]{8,}\b", replace_bare_channel, sanitized)

        # 3. Bare user IDs (U or W followed by 8+ alphanumeric chars)
        def replace_bare_user(m):
            uid = m.group(0)
            return self.format_user_name(uid)

        sanitized = re.sub(r"\b[UW][A-Z0-9]{8,}\b", replace_bare_user, sanitized)

        return sanitized

    def clear_cache(self) -> None:
        """Clear the in-memory resolution caches."""
        self._user_cache.clear()
        self._channel_cache.clear()
        self._channel_registry = dict(_DEFAULT_WORKSPACE_CHANNELS)
        self._email_to_canonical_id.clear()
        self._platform_to_canonical_id.clear()
        self._canonical_to_external_ids.clear()
