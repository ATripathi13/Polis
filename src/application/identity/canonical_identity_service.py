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

        # Cross-platform canonical employee internal ID unification:
        norm_email = email.lower().strip() if email else ""
        if norm_email:
            canonical_id = self._email_to_canonical_id.get(norm_email) or f"emp_{norm_email}"
            self._email_to_canonical_id[norm_email] = canonical_id
            status = IdentityResolutionStatus.RESOLVED
        else:
            canonical_id = self._platform_to_canonical_id.get((platform, clean_user_id)) or clean_user_id
            status = (
                IdentityResolutionStatus.PROVISIONAL
                if display_name_hint and display_name_hint != clean_user_id
                else IdentityResolutionStatus.UNRESOLVED
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

        # Determine channel type
        if clean_channel_id.startswith("D"):
            channel_type = "im"
            channel_name = channel_name_hint or f"dm-{clean_channel_id}"
        elif clean_channel_id.startswith("G"):
            channel_type = "mpim"
            channel_name = channel_name_hint or f"group-dm-{clean_channel_id}"
        elif clean_channel_id.startswith("C"):
            channel_type = "private" if is_private_hint else "public"
            channel_name = channel_name_hint or clean_channel_id
        elif platform in (PlatformType.TEAMS.value, "microsoft_teams"):
            channel_type = "meeting" if "meeting" in clean_channel_id.lower() else "channel"
            channel_name = channel_name_hint or clean_channel_id
        else:
            channel_type = "public"
            channel_name = channel_name_hint or clean_channel_id

        identity = CanonicalChannelIdentity(
            platform=platform,
            platform_channel_id=clean_channel_id,
            channel_name=channel_name,
            channel_type=channel_type,
            metadata={"external_id": clean_channel_id},
        )
        self._channel_cache[cache_key] = identity
        return identity

    def clear_cache(self) -> None:
        """Clear the in-memory resolution caches."""
        self._user_cache.clear()
        self._channel_cache.clear()
        self._email_to_canonical_id.clear()
        self._platform_to_canonical_id.clear()
        self._canonical_to_external_ids.clear()
