"""
Calendar Agent specialist capability for POLIS.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo

from domain.calendar.entities.calendar_entry import CalendarEntry
from domain.calendar.enums import (
    CalendarAudienceType,
    CalendarDeliveryStatus,
    CalendarEntryStatus,
    CalendarEntryType,
)
from domain.calendar.exceptions import (
    CalendarDomainError,
    CalendarEntryNotFoundError,
    InvalidAudienceError,
    InvalidCalendarEntryError,
    InvalidTimeRangeError,
    UnauthorizedCalendarActionError,
)
from domain.calendar.value_objects import is_raw_slack_id as _is_raw_slack_id
from domain.reasoning.value_objects import Question
from application.calendar.calendar_service import CalendarService

logger = logging.getLogger(__name__)


class CalendarAgent:
    """
    Specialist agent responsible for organizational calendar intelligence.

    Coordinates activities, holidays, and announcements, handles natural-language
    intents, verifies authorization and audience, maintains deterministic validation,
    and provides evidence to POLIS.
    """

    def __init__(
        self,
        service: CalendarService,
        default_timezone: str = "Asia/Kolkata",
        identity_resolver: Any = None,
    ) -> None:
        self._service = service
        self._default_timezone = default_timezone
        self._identity_resolver = identity_resolver

    @property
    def service(self) -> CalendarService:
        return self._service

    def _resolve_user_display_name(self, user_id: str | None) -> str | None:
        """Resolve a user ID to a human-readable display name, returning None if unresolvable."""
        if not user_id:
            return None
        cleaned_id = user_id.strip()
        if cleaned_id.startswith("<@") and cleaned_id.endswith(">"):
            parts = cleaned_id[2:-1].split("|", 1)
            cleaned_id = parts[0].strip()

        # 1. Try explicit identity_resolver if provided
        if self._identity_resolver is not None:
            if hasattr(self._identity_resolver, "get_display_name"):
                try:
                    name = self._identity_resolver.get_display_name(cleaned_id)
                    if name and not _is_raw_slack_id(name) and name != cleaned_id:
                        return name.strip()
                except Exception:
                    pass
            if hasattr(self._identity_resolver, "resolve_user"):
                try:
                    user_data = self._identity_resolver.resolve_user(cleaned_id)
                    if isinstance(user_data, dict) and user_data.get("id") == cleaned_id:
                        profile = user_data.get("profile", {}) if isinstance(user_data.get("profile"), dict) else {}
                        candidate = (
                            user_data.get("real_name")
                            or profile.get("display_name")
                            or user_data.get("name")
                        )
                        if candidate and not _is_raw_slack_id(candidate) and candidate != cleaned_id:
                            return candidate.strip()
                except Exception:
                    pass

        # 2. Try through CalendarService's audience_service directory provider
        try:
            aud_svc = getattr(self._service, "audience_service", None)
            provider = getattr(aud_svc, "directory_provider", None) if aud_svc else None
            if provider and hasattr(provider, "resolve_user"):
                user_data = provider.resolve_user(cleaned_id)
                if isinstance(user_data, dict) and user_data.get("id") == cleaned_id:
                    candidate = (
                        user_data.get("real_name")
                        or user_data.get("name")
                    )
                    if candidate and not _is_raw_slack_id(candidate) and candidate != cleaned_id:
                        return candidate.strip()
        except Exception:
            pass

        return None

    def _format_audience(self, entry: CalendarEntry) -> str:
        """Format audience for display without exposing raw internal IDs."""
        if entry.audience_type == CalendarAudienceType.INDIVIDUAL:
            disp_name = entry.metadata.get("audience_display_name")
            if not disp_name or _is_raw_slack_id(disp_name):
                disp_name = self._resolve_user_display_name(entry.audience_id)
            if disp_name and not _is_raw_slack_id(disp_name):
                return f"individual ({disp_name})"
            return "individual"
        elif entry.audience_type == CalendarAudienceType.ORGANIZATION:
            return "organization"
        elif entry.audience_type == CalendarAudienceType.TEAM:
            disp_name = entry.metadata.get("audience_display_name")
            if disp_name and not _is_raw_slack_id(disp_name) and str(disp_name).strip():
                return f"team ({str(disp_name).strip()})"
            return "team"
        return entry.audience_type.value

    # =========================================================================
    # SPECIALIST QUESTION & EVIDENCE METHODS (POLIS COGNITIVE INTEGRATION)
    # =========================================================================

    def retrieve_evidence(self, question: Question | str) -> list[str]:
        """
        Retrieve structured calendar evidence for POLIS unified cognitive engine.
        """
        text = question.text if isinstance(question, Question) else str(question)
        normalized = text.lower()

        # Check if question asks about calendar, holidays, activities, announcements, schedule
        keywords = ("calendar", "holiday", "activity", "announcement", "schedule", "events", "meeting")
        if not any(k in normalized for k in keywords):
            return []

        # Find upcoming scheduled entries
        now = datetime.now(timezone.utc)
        horizon = now + timedelta(days=30)
        entries = self._service.list_entries(
            start_range=now - timedelta(days=1),
            end_range=horizon,
            status=CalendarEntryStatus.SCHEDULED,
            limit=20,
        )
        requester_id = (
            question.context.user_id
            if isinstance(question, Question) and question.context is not None
            else None
        )

        entries = [
            entry
            for entry in entries
            if entry.audience_type == CalendarAudienceType.ORGANIZATION
            or (
                requester_id is not None
                and entry.is_visible_to(requester_id)
            )
        ]
        evidence: list[str] = []
        for entry in entries:
            try:
                tz = ZoneInfo(entry.timezone)
                local_start = entry.start_time.astimezone(tz)
                start_str = local_start.strftime("%Y-%m-%d %I:%M %p")
            except Exception:
                start_str = entry.start_time.strftime("%Y-%m-%d %H:%M UTC")


            ev = (
                f"Calendar Entry [{entry.entry_type.value.upper()}]: '{entry.title}'\n"
                f"ID: {entry.entry_id}\n"
                f"Scheduled Start: {start_str} ({entry.timezone})\n"
                f"Audience: {self._format_audience(entry)}\n"
                f"Status: {entry.status.value}\n"
            )
            if entry.description:
                ev += f"Details: {entry.description}\n"
            evidence.append(ev)

        return evidence

    def ask(self, question: Question | str) -> dict[str, Any]:
        """Direct specialist query answering."""
        text = question.text if isinstance(question, Question) else str(question)
        evidence = self.retrieve_evidence(question)
        return {
            "question": text,
            "evidence": evidence,
            "total_entries": len(evidence),
        }

    # =========================================================================
    # CONVERSATIONAL INTENT PARSING & DISPATCH
    # =========================================================================

    def handle_message(
        self,
        text: str,
        *,
        user_id: str,
        channel_id: str = "",
    ) -> str | None:
        """
        Inspect message for calendar intents. If matching, execute deterministically
        and return the response string. Returns None if the message is not calendar-related.
        """
        cleaned = text.strip()
        lower = cleaned.lower()

        # 1. Intent: Cancel event
        cancel_match = re.search(
            r"\b(?:cancel|delete|remove)\s+(?:calendar\s+)?(?:entry|event|activity|holiday|announcement)\s+([a-zA-Z0-9_\-]+)",
            lower,
        )
        if cancel_match:
            target_ref = cancel_match.group(1).strip()
            return self._handle_cancel(target_ref, user_id=user_id)

        # 2. Intent: Inspect reminder status
        reminder_status_match = re.search(
            r"\b(?:reminder\s+status|has\s+(?:the\s+)?reminder\s+been\s+sent|check\s+reminder)\s+(?:for\s+)?([a-zA-Z0-9_\-]+)",
            lower,
        )
        if reminder_status_match:
            target_ref = reminder_status_match.group(1).strip()
            return self._handle_reminder_status(target_ref, user_id=user_id)

        # 3. Intent: Who is this for / audience query
        audience_match = re.search(
            r"\bwho\s+is\s+(?:the\s+)?(?:entry|event|activity|holiday|announcement)\s+([a-zA-Z0-9_\-]+)\s+(?:intended\s+)?for\b",
            lower,
        )
        if audience_match:
            target_ref = audience_match.group(1).strip()
            return self._handle_who_is_for(target_ref, user_id=user_id)

        # 4. Intent: List / What's on the calendar
        if any(
            pattern in lower
            for pattern in (
                "what is on the calendar",
                "what's on the calendar",
                "upcoming calendar",
                "list calendar",
                "upcoming activities",
                "upcoming holidays",
                "upcoming announcements",
                "view calendar",
            )
        ):
            return self._handle_list(lower, user_id=user_id)

        # 5. Intent: Create / Schedule calendar entry
        if self._is_schedule_intent(lower):
            return self._handle_schedule(cleaned, user_id=user_id)

        # 6. Intent: Reschedule / Update entry
        if any(w in lower for w in ("reschedule", "postpone", "move event", "update event")):
            return self._handle_update(cleaned, user_id=user_id)

        return None

    def _is_schedule_intent(self, text: str) -> bool:
        """Detect whether message is a command to schedule a calendar entry."""
        if re.search(
            r"\b(?:schedule|add|create)\s+(?:a\s+|an\s+)?(?:activity|holiday|announcement|event)\b",
            text,
        ):
            return True
        if re.search(
            r"\b(?:add|create|schedule)\s+(?:a\s+)?(?:company\s+)?calendar\s+entry\b",
            text,
        ):
            return True
        if re.search(r"\b(?:set|schedule)\s+(?:a\s+|an\s+)?holiday\b", text):
            return True
        if re.search(r"\bpost\s+announcement\b", text):
            return True
        return False

    def _handle_schedule(self, text: str, *, user_id: str) -> str:
        """Parse, validate, and create a calendar entry."""
        lower = text.lower()

        # Determine type
        entry_type = CalendarEntryType.ACTIVITY
        if "holiday" in lower:
            entry_type = CalendarEntryType.HOLIDAY
        elif "announcement" in lower:
            entry_type = CalendarEntryType.ANNOUNCEMENT

        # Extract title
        title = self._extract_title(text)
        if not title:
            return (
                f"I understood you want to schedule a {entry_type.value}. "
                "What is the title of the entry?"
            )

        # Extract start datetime
        start_dt = self._extract_datetime(text)
        if start_dt is None:
            return (
                f"I have the title '{title}'. "
                "When is this scheduled to take place? Please provide a date and time (e.g., '2026-10-25 14:00')."
            )

        # Extract audience
        audience_type, audience_id = self._extract_audience(text, fallback_user=user_id)
        if not audience_type:
            return (
                f"Who should the {entry_type.value} '{title}' be scheduled for? "
                "Please specify: an individual (e.g., @user), a team (e.g., 'engineering team'), or the whole organization."
            )

        # Extract optional description
        desc_match = re.search(r"(?im)^\s*[-*•]?\s*(?:details|description|note|notes)\s*:\s*(.+?)\s*$", text)
        description = desc_match.group(1).strip() if desc_match else ""

        try:
            entry = self._service.create_entry(
                title=title,
                description=description,
                entry_type=entry_type,
                creator_id=user_id,
                start_time=start_dt,
                timezone_name=self._default_timezone,
                audience_type=audience_type,
                audience_identifier=audience_id,
            )

            tz = ZoneInfo(entry.timezone)
            local_start = entry.start_time.astimezone(tz)
            start_str = local_start.strftime("%Y-%m-%d %I:%M %p")
            due_time = self._service.reminder_policy.calculate_due_time(entry.start_time).astimezone(tz)
            due_str = due_time.strftime("%Y-%m-%d %I:%M %p")

            return (
                f"Done! I've added it to the calendar.\n\n"
                f"✅ Successfully scheduled *{entry.entry_type.value.capitalize()}*:\n"
                f"• *Title:* {entry.title}\n"
                f"• *ID:* `{entry.entry_id}`\n"
                f"• *Scheduled Start:* {start_str} ({entry.timezone})\n"
                f"• *Audience:* {self._format_audience(entry)}\n"
                f"• *Reminder Scheduled:* {due_str} ({entry.timezone}) [exactly 15 hours before start]"
            )

        except CalendarDomainError as err:
            return f"⚠️ I couldn't create that calendar entry: {str(err)}"
        except Exception:
            logger.exception("Unexpected error creating calendar entry")
            return "⚠️ I ran into an error while creating the calendar entry. Please try again."

    def _handle_list(self, lower: str, *, user_id: str) -> str:
        """List upcoming entries visible to the user."""
        filter_type: CalendarEntryType | None = None
        if "holiday" in lower:
            filter_type = CalendarEntryType.HOLIDAY
        elif "activity" in lower:
            filter_type = CalendarEntryType.ACTIVITY
        elif "announcement" in lower:
            filter_type = CalendarEntryType.ANNOUNCEMENT

        now = datetime.now(timezone.utc)
        horizon = now + timedelta(days=14)
        entries = self._service.list_entries(
            start_range=now - timedelta(hours=1),
            end_range=horizon,
            entry_type=filter_type,
            status=CalendarEntryStatus.SCHEDULED,
            limit=10,
        )

        visible = [e for e in entries if e.is_visible_to(user_id)]
        if not visible:
            label = f"{filter_type.value}s" if filter_type else "entries"
            return f"I didn't find any scheduled upcoming {label} on the calendar."

        lines = ["📅 *Upcoming Calendar Entries:*"]
        for entry in visible:
            try:
                tz = ZoneInfo(entry.timezone)
                local_start = entry.start_time.astimezone(tz)
                start_str = local_start.strftime("%Y-%m-%d %I:%M %p")
            except Exception:
                start_str = entry.start_time.strftime("%Y-%m-%d %H:%M UTC")

            lines.append(
                f"• *[{entry.entry_type.value.capitalize()}]* `{entry.entry_id}`: *{entry.title}* "
                f"on {start_str} ({entry.timezone}) — Audience: {self._format_audience(entry)}"
            )

        return "\n".join(lines)

    def _handle_cancel(self, target_ref: str, *, user_id: str) -> str:
        """Cancel a calendar entry by ID or title match."""
        entry = self._find_entry_by_ref(target_ref, user_id=user_id)
        if entry is None:
            return f"I couldn't find an active calendar entry matching '{target_ref}'."

        try:
            self._service.cancel_entry(entry.entry_id, requester_id=user_id)
            return (
                f"Done! I've cancelled it.\n\n"
                f"🚫 Successfully cancelled *{entry.title}* (`{entry.entry_id}`). "
                "Any pending reminders have been cancelled."
            )
        except UnauthorizedCalendarActionError:
            return "I can't cancel this calendar entry because you are not authorized. Only the creator can cancel it."
        except CalendarDomainError as err:
            return f"⚠️ I couldn't cancel that entry: {str(err)}"

    def _handle_reminder_status(self, target_ref: str, *, user_id: str) -> str:
        """Inspect reminder status for an entry."""
        entry = self._find_entry_by_ref(target_ref, user_id=user_id)
        if entry is None:
            return f"I couldn't find a calendar entry matching '{target_ref}'."
        if entry.creator_id != user_id:
            return "I can't show reminder delivery details for this entry because you are not authorized. Only the creator can view them."

        deliveries = self._service.get_reminder_status(
            entry.entry_id,
            requester_id=user_id,
        )
        if not deliveries:
            return f"I didn't find any reminders configured for entry *{entry.title}* (`{entry.entry_id}`)."

        lines = [f"🔔 *Reminder Delivery Status for '{entry.title}' (`{entry.entry_id}`):*"]
        for d in deliveries:
            status_emoji = "✅" if d.status == CalendarDeliveryStatus.SENT else ("⏳" if d.status == CalendarDeliveryStatus.PENDING else "❌")
            recipient_label = "Recipient"
            recipient_name: str | None = None
            if entry.audience_type == CalendarAudienceType.INDIVIDUAL and d.recipient_id == entry.audience_id:
                candidate = entry.metadata.get("audience_display_name")
                if candidate and not _is_raw_slack_id(candidate):
                    recipient_name = candidate.strip()
            if not recipient_name:
                recipient_name = self._resolve_user_display_name(d.recipient_id)
            if recipient_name and not _is_raw_slack_id(recipient_name):
                recipient_label = f"Recipient: {recipient_name}"

            lines.append(
                f"• {status_emoji} {recipient_label} (via {d.delivery_channel}) — Status: *{d.status.value.upper()}* "
                f"(Due: {d.due_at.strftime('%Y-%m-%d %H:%M UTC')}, Attempts: {d.attempt_count})"
            )
        return "\n".join(lines)

    def _handle_who_is_for(self, target_ref: str, *, user_id: str) -> str:
        """Describe intended audience of an entry."""
        entry = self._find_entry_by_ref(target_ref, user_id=user_id)
        if entry is None:
            return f"Could not find a calendar entry matching '{target_ref}'."
        if entry.audience_type == CalendarAudienceType.INDIVIDUAL:
            disp_name = entry.metadata.get("audience_display_name")
            if not disp_name or _is_raw_slack_id(disp_name):
                disp_name = self._resolve_user_display_name(entry.audience_id)
            if disp_name and not _is_raw_slack_id(disp_name):
                return (
                    f"Entry *{entry.title}* (`{entry.entry_id}`) is intended for *{disp_name}* (individual)."
                )
            return (
                f"Entry *{entry.title}* (`{entry.entry_id}`) is intended for an individual recipient."
            )
        elif entry.audience_type == CalendarAudienceType.TEAM:
            disp_name = entry.metadata.get("audience_display_name")
            if disp_name and not _is_raw_slack_id(disp_name) and str(disp_name).strip():
                return (
                    f"Entry *{entry.title}* (`{entry.entry_id}`) is intended for the *{str(disp_name).strip()}* team."
                )
            return (
                f"Entry *{entry.title}* (`{entry.entry_id}`) is intended for a team."
            )
        elif entry.audience_type == CalendarAudienceType.ORGANIZATION:
            return (
                f"Entry *{entry.title}* (`{entry.entry_id}`) is intended for the *whole organization*."
            )
        return (
            f"Entry *{entry.title}* (`{entry.entry_id}`) is intended for: "
            f"*{entry.audience_type.value.capitalize()}*."
        )

    def _handle_update(self, text: str, *, user_id: str) -> str:
        """Handle rescheduling or modifying an entry."""
        target_ref_match = re.search(
            r"\b(?:reschedule|update|move)\s+(?:event\s+|entry\s+)?([a-zA-Z0-9_\-]+)",
            text,
            re.IGNORECASE,
        )
        if not target_ref_match:
            return "Which calendar entry would you like to update? Please provide the entry ID or title."

        target_ref = target_ref_match.group(1).strip()
        entry = self._find_entry_by_ref(target_ref, user_id=user_id)
        if entry is None:
            return f"I couldn't find an entry matching '{target_ref}'."

        new_dt = self._extract_datetime(text)
        if new_dt is None:
            return f"I found entry '{entry.title}'. What is the new scheduled date and time?"

        try:
            updated = self._service.update_entry(
                entry.entry_id,
                requester_id=user_id,
                start_time=new_dt,
            )
            tz = ZoneInfo(updated.timezone)
            start_str = updated.start_time.astimezone(tz).strftime("%Y-%m-%d %I:%M %p")
            due_time = self._service.reminder_policy.calculate_due_time(updated.start_time).astimezone(tz)
            due_str = due_time.strftime("%Y-%m-%d %I:%M %p")

            return (
                f"Done! I've updated the calendar.\n\n"
                f"🔄 Successfully rescheduled *{updated.title}* (`{updated.entry_id}`):\n"
                f"• *New Start:* {start_str} ({updated.timezone})\n"
                f"• *New Reminder Due:* {due_str} ({updated.timezone})\n"
                f"• *Version:* {updated.version} (prior pending reminders were cancelled and recalculated)."
            )
        except UnauthorizedCalendarActionError:
            return "I can't update this calendar entry because you are not authorized. Only the creator can update it."
        except CalendarDomainError as err:
            return f"⚠️ I couldn't update that entry: {str(err)}"

    # =========================================================================
    # EXTRACTION & RESOLUTION HELPERS
    # =========================================================================

    def _find_entry_by_ref(
        self,
        target_ref: str,
        *,
        user_id: str,
    ) -> CalendarEntry | None:
        """Locate an entry by ID or title, returning only entries visible to the requester."""
        if not user_id:
            return None

        def visible(entry: CalendarEntry) -> bool:
            return entry.is_visible_to(user_id)

        entry = self._service.get_entry(target_ref)
        if entry is not None:
            return entry if visible(entry) else None

        all_entries = self._service.list_entries(limit=100)
        cleaned_ref = target_ref.lower().strip()

        for candidate in all_entries:
            if not visible(candidate):
                continue
            if (
                candidate.title.lower() == cleaned_ref
                or cleaned_ref in candidate.title.lower()
            ):
                return candidate

        return None

    def _extract_title(self, text: str) -> str | None:
        """Extract title from message."""
        # Support structured Slack requests with a dedicated Title field.
        field_match = re.search(
            r"(?im)^\s*[-*•]?\s*Title\s*:\s*(.+?)\s*$",
            text,
        )
        if field_match:
            return field_match.group(1).strip()

        # Check quoted strings: "Title" or 'Title'
        quotes = re.findall(r'["\']([^"\']+)["\']', text)
        if quotes:
            return quotes[0].strip()

        # Check 'named <title>' or 'titled <title>' or 'called <title>'
        named = re.search(r"\b(?:named|titled|called)\s+([a-zA-Z0-9_\-\s]+?)(?:\s+(?:on|at|for|to)|$)", text, re.IGNORECASE)
        if named:
            return named.group(1).strip()

        # Pattern: schedule <type> <title> on/for/at
        m = re.search(
            r"\b(?:schedule|add|create|set)\s+(?:a\s+|an\s+)?(?:activity|holiday|announcement|event)\s+([a-zA-Z0-9_\-\s]+?)(?:\s+(?:on|at|for|to|with)|$)",
            text,
            re.IGNORECASE,
        )
        if m:
            val = m.group(1).strip()
            # Avoid picking words like 'for the team'
            if val and not val.lower().startswith(("for", "on", "at")):
                return val

        return None

    def _extract_datetime(self, text: str) -> datetime | None:
        """Extract a timezone-aware start datetime from ISO or written dates."""
        tz = ZoneInfo(self._default_timezone)

        # Support dates such as "24 November 2026" with times such as "9:00 AM IST".
        written_date = re.search(
            r"(?i)\b(\d{1,2})\s+"
            r"(January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+(\d{4})\b",
            text,
        )
        if written_date:
            try:
                parsed_date = datetime.strptime(
                    " ".join(written_date.groups()), "%d %B %Y"
                ).date()
                time_match = re.search(
                    r"(?i)\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\b",
                    text,
                )
                if time_match:
                    hour = int(time_match.group(1)) % 12
                    if time_match.group(3).upper() == "PM":
                        hour += 12
                    minute = int(time_match.group(2) or "0")
                    parsed_time = time(hour, minute)
                else:
                    parsed_time = time(9, 0)
                return datetime.combine(parsed_date, parsed_time, tzinfo=tz)
            except ValueError:
                pass

        # Support ISO dates with optional 24-hour times.
        iso_match = re.search(
            r"\b(\d{4}-\d{2}-\d{2})(?:[T\s](\d{2}:\d{2}(?::\d{2})?))?\b",
            text,
        )
        if iso_match:
            try:
                parsed_date = date.fromisoformat(iso_match.group(1))
                time_text = iso_match.group(2) or "09:00"
                parts = [int(part) for part in time_text.split(":")]
                parsed_time = time(parts[0], parts[1])
                return datetime.combine(parsed_date, parsed_time, tzinfo=tz)
            except ValueError:
                pass

        # Support relative dates such as "tomorrow at 10am" and "today at 3pm".
        now = datetime.now(tz)
        lower = text.lower()
        target_date: date | None = None
        if re.search(r"\btomorrow\b", lower):
            target_date = now.date() + timedelta(days=1)
        elif re.search(r"\btoday\b", lower):
            target_date = now.date()

        if target_date is not None:
            time_match = re.search(
                r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
                lower,
            )
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2) or 0)
                ampm = time_match.group(3)
                if ampm == "pm" and hour < 12:
                    hour += 12
                elif ampm == "am" and hour == 12:
                    hour = 0
                try:
                    return datetime.combine(
                        target_date, time(hour, minute), tzinfo=tz
                    )
                except ValueError:
                    return None
            return datetime.combine(target_date, time(9, 0), tzinfo=tz)

        return None

    def _extract_audience(
        self,
        text: str,
        fallback_user: str,
    ) -> tuple[CalendarAudienceType, str]:
        """Extract audience specification from text."""
        lower = text.lower()

        # Organization audience
        if any(w in lower for w in ("organization", "entire company", "all employees", "all hands", "everyone", "org")):
            return CalendarAudienceType.ORGANIZATION, "organization"

        # Mention pattern: <@U12345>
        mention = re.search(r"<@([A-Za-z0-9_]+)(?:\|[^>]+)?>", text)
        if mention:
            return CalendarAudienceType.INDIVIDUAL, mention.group(1)

        # Team pattern: team <team_name> or for <name> team
        team_match = re.search(r"\b(?:for\s+(?:the\s+)?)?([a-zA-Z0-9_\-]+)\s+team\b", lower)
        if team_match:
            return CalendarAudienceType.TEAM, team_match.group(1).strip()

        team_match2 = re.search(r"\bteam\s+([a-zA-Z0-9_\-]+)\b", lower)
        if team_match2:
            return CalendarAudienceType.TEAM, team_match2.group(1).strip()

        # Individual name pattern: for <name>
        for_match = re.search(r"\bfor\s+([a-zA-Z0-9_\-]+)\b", text)
        if for_match:
            candidate = for_match.group(1).strip()
            if candidate.lower() not in ("the", "a", "an", "all", "our", "today", "tomorrow"):
                return CalendarAudienceType.INDIVIDUAL, candidate

        # Default fallback to the creator
        return CalendarAudienceType.INDIVIDUAL, fallback_user

    # =========================================================================
    # STRUCTURED CALENDAR EXECUTION (PHASE 3.3 STAGE B2)
    # =========================================================================

    def _resolve_datetime_param(
        self,
        parameters: dict[str, Any],
        tz_name: str,
    ) -> tuple[datetime | None, datetime | None]:
        """
        Resolve start_time and optional end_time from structured parameters.
        Derives end_time from duration_minutes only when start_time and a valid
        positive duration are present.
        """
        try:
            tz = ZoneInfo(tz_name)
        except Exception as err:
            raise InvalidTimeRangeError(f"Invalid timezone: {tz_name}") from err

        start_dt: datetime | None = None
        raw_start = parameters.get("start_time")
        if isinstance(raw_start, datetime):
            start_dt = raw_start if raw_start.tzinfo is not None else raw_start.replace(tzinfo=tz)
        elif isinstance(raw_start, str) and raw_start.strip():
            clean_str = raw_start.strip()
            try:
                parsed = datetime.fromisoformat(clean_str)
                start_dt = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=tz)
            except Exception:
                start_dt = self._extract_datetime(clean_str)

        if start_dt is None:
            # Check dates and times collections or strings
            raw_dates = parameters.get("dates") or parameters.get("date")
            raw_times = parameters.get("times") or parameters.get("time")
            if raw_dates and raw_times:
                d_str = str(raw_dates[0] if isinstance(raw_dates, list) else raw_dates).strip()
                t_str = str(raw_times[0] if isinstance(raw_times, list) else raw_times).strip()
                try:
                    d_parsed = date.fromisoformat(d_str)
                    t_parsed = time.fromisoformat(t_str)
                    start_dt = datetime.combine(d_parsed, t_parsed, tzinfo=tz)
                except Exception:
                    start_dt = self._extract_datetime(f"{d_str} {t_str}")
                    if start_dt is None:
                        start_dt = self._extract_datetime(f"{d_str} at {t_str}")

        # Resolve end_dt
        end_dt: datetime | None = None
        raw_end = parameters.get("end_time")
        if isinstance(raw_end, datetime):
            end_dt = raw_end if raw_end.tzinfo is not None else raw_end.replace(tzinfo=tz)
        elif isinstance(raw_end, str) and raw_end.strip():
            clean_end = raw_end.strip()
            try:
                parsed_end = datetime.fromisoformat(clean_end)
                end_dt = parsed_end if parsed_end.tzinfo is not None else parsed_end.replace(tzinfo=tz)
            except Exception:
                end_dt = self._extract_datetime(clean_end)

        # Derive end_time from duration_minutes if end_time not provided
        if end_dt is None and "duration_minutes" in parameters and parameters["duration_minutes"] is not None:
            raw_duration = parameters["duration_minutes"]
            try:
                dur_mins = int(raw_duration)
                if dur_mins <= 0:
                    raise InvalidTimeRangeError("duration_minutes must be a positive integer.")
                if start_dt is not None:
                    end_dt = start_dt + timedelta(minutes=dur_mins)
            except (ValueError, TypeError) as err:
                raise InvalidTimeRangeError(f"duration_minutes must be a positive integer: {err}") from err

        if start_dt is not None and end_dt is not None and end_dt < start_dt:
            raise InvalidTimeRangeError("End time cannot precede start time.")

        return start_dt, end_dt

    def _resolve_audience_params(
        self,
        parameters: dict[str, Any],
    ) -> tuple[CalendarAudienceType, str, str]:
        """
        Resolve audience type, identifier, and optional display name from parameters.
        Enforces safeguards: does not invent audience or substitute requester.
        """
        raw_type = parameters.get("audience_type")
        target_type: CalendarAudienceType | None = None
        if isinstance(raw_type, CalendarAudienceType):
            target_type = raw_type
        elif isinstance(raw_type, str) and raw_type.strip():
            try:
                target_type = CalendarAudienceType(raw_type.strip().lower())
            except ValueError as err:
                raise InvalidAudienceError(
                    f"Unsupported audience type: '{raw_type}'. "
                    f"Supported types: individual, team, organization."
                ) from err

        # If audience_type was not explicitly given, check contextual fields
        if target_type is None:
            if parameters.get("team_names"):
                target_type = CalendarAudienceType.TEAM
            elif parameters.get("target_user_id") or parameters.get("employee_names"):
                target_type = CalendarAudienceType.INDIVIDUAL

        if target_type is None:
            raise InvalidAudienceError("Audience type and identifier are required.")

        # Resolve audience identifier
        aud_id: str | None = parameters.get("audience_identifier") or parameters.get("audience_id")
        if not aud_id or not str(aud_id).strip():
            if target_type == CalendarAudienceType.TEAM and parameters.get("team_names"):
                team_list = parameters["team_names"]
                aud_id = team_list[0] if isinstance(team_list, list) and team_list else str(team_list)
            elif target_type == CalendarAudienceType.INDIVIDUAL:
                if parameters.get("target_user_id"):
                    aud_id = str(parameters["target_user_id"])
                elif parameters.get("employee_names"):
                    emp_list = parameters["employee_names"]
                    aud_id = emp_list[0] if isinstance(emp_list, list) and emp_list else str(emp_list)
            elif target_type == CalendarAudienceType.ORGANIZATION:
                aud_id = "organization"

        if not aud_id or not str(aud_id).strip():
            raise InvalidAudienceError(f"Audience identifier is required for '{target_type.value}' audience.")

        display_name = str(parameters.get("display_name") or "").strip()
        return target_type, str(aud_id).strip(), display_name

    def create_entry_structured(
        self,
        parameters: dict[str, Any],
        *,
        user_id: str,
    ) -> CalendarEntry:
        """
        Create a calendar entry from validated structured parameters.
        """
        if not user_id or not str(user_id).strip():
            raise UnauthorizedCalendarActionError("Requester identity cannot be empty.")
        clean_user_id = str(user_id).strip()

        title = parameters.get("title") or parameters.get("event_title") or parameters.get("summary")
        if not title or not str(title).strip():
            raise InvalidCalendarEntryError("Calendar entry title cannot be empty.")
        clean_title = str(title).strip()

        tz_name = str(
            parameters.get("timezone_name")
            or parameters.get("timezone")
            or self._default_timezone
        ).strip()

        start_dt, end_dt = self._resolve_datetime_param(parameters, tz_name)
        if start_dt is None:
            raise InvalidTimeRangeError("Valid start date and time are required.")

        aud_type, aud_id, disp_name = self._resolve_audience_params(parameters)

        raw_type = parameters.get("entry_type") or CalendarEntryType.ACTIVITY
        if isinstance(raw_type, str):
            try:
                entry_type = CalendarEntryType(raw_type.strip().lower())
            except ValueError as err:
                raise InvalidCalendarEntryError(
                    f"Invalid entry type '{raw_type}'. Must be activity, holiday, or announcement."
                ) from err
        else:
            entry_type = raw_type

        description = str(parameters.get("description") or parameters.get("details") or "").strip()
        raw_meta = dict(parameters.get("metadata") or {})
        # Protect system attributes from being overwritten by metadata
        safe_meta = {
            k: v for k, v in raw_meta.items()
            if k not in ("creator_id", "entry_id", "version", "status", "created_at", "updated_at")
        }

        entry = self._service.create_entry(
            title=clean_title,
            description=description,
            entry_type=entry_type,
            creator_id=clean_user_id,
            start_time=start_dt,
            end_time=end_dt,
            timezone_name=tz_name,
            audience_type=aud_type,
            audience_identifier=aud_id,
            display_name=disp_name,
            metadata=safe_meta,
        )
        return entry

    def update_entry_structured(
        self,
        parameters: dict[str, Any],
        *,
        user_id: str,
    ) -> CalendarEntry:
        """
        Update an existing calendar entry from validated structured parameters.
        Enforces creator-only authorization via CalendarService.
        """
        if not user_id or not str(user_id).strip():
            raise UnauthorizedCalendarActionError("Requester identity cannot be empty.")
        clean_user_id = str(user_id).strip()

        entry_id = parameters.get("entry_id") or parameters.get("item_reference")
        if not entry_id or not str(entry_id).strip():
            raise InvalidCalendarEntryError("entry_id is required for calendar updates.")
        clean_entry_id = str(entry_id).strip()

        # Check for invalid duration_minutes early if present
        if "duration_minutes" in parameters and parameters["duration_minutes"] is not None:
            try:
                dur = int(parameters["duration_minutes"])
                if dur <= 0:
                    raise InvalidTimeRangeError("duration_minutes must be a positive integer.")
            except (ValueError, TypeError) as err:
                raise InvalidTimeRangeError(f"duration_minutes must be a positive integer: {err}") from err

        raw_title = parameters.get("title") or parameters.get("event_title")
        title = str(raw_title).strip() if raw_title is not None else None

        raw_desc = parameters.get("description") or parameters.get("details")
        description = str(raw_desc).strip() if raw_desc is not None else None

        new_tz = parameters.get("timezone_name") or parameters.get("timezone")
        if new_tz:
            try:
                ZoneInfo(str(new_tz).strip())
                new_tz = str(new_tz).strip()
            except Exception as err:
                raise InvalidTimeRangeError(f"Invalid timezone: {new_tz}") from err

        tz_for_calc = new_tz or self._default_timezone
        new_start, new_end = self._resolve_datetime_param(parameters, tz_for_calc)

        new_aud_type: CalendarAudienceType | None = None
        new_aud_id: str | None = None
        if any(k in parameters for k in ("audience_type", "audience_identifier", "audience_id", "team_names", "employee_names")):
            new_aud_type, new_aud_id, _ = self._resolve_audience_params(parameters)

        updated = self._service.update_entry(
            entry_id=clean_entry_id,
            requester_id=clean_user_id,
            title=title,
            description=description,
            start_time=new_start,
            end_time=new_end,
            timezone_name=new_tz,
            audience_type=new_aud_type,
            audience_identifier=new_aud_id,
        )
        return updated

    def cancel_entry_structured(
        self,
        parameters: dict[str, Any],
        *,
        user_id: str,
    ) -> CalendarEntry:
        """
        Cancel a calendar entry from validated structured parameters.
        Enforces creator-only authorization via CalendarService.
        """
        if not user_id or not str(user_id).strip():
            raise UnauthorizedCalendarActionError("Requester identity cannot be empty.")
        clean_user_id = str(user_id).strip()

        entry_id = parameters.get("entry_id") or parameters.get("item_reference")
        if not entry_id or not str(entry_id).strip():
            raise InvalidCalendarEntryError("entry_id is required for calendar cancellation.")
        clean_entry_id = str(entry_id).strip()

        cancelled = self._service.cancel_entry(
            entry_id=clean_entry_id,
            requester_id=clean_user_id,
        )
        return cancelled

    def format_confirmation(
        self,
        entry: CalendarEntry,
        operation: str = "create",
    ) -> str:
        """Format an outcome confirmation message for a calendar mutation."""
        op = operation.lower().strip()
        if op in ("cancel", "cancel_event", "delete"):
            return (
                f"Done! I've cancelled it.\n\n"
                f"🚫 Successfully cancelled *{entry.title}* (`{entry.entry_id}`). "
                "Any pending reminders have been cancelled."
            )

        tz = ZoneInfo(entry.timezone)
        if op in ("update", "update_event", "reschedule"):
            start_str = entry.start_time.astimezone(tz).strftime("%Y-%m-%d %I:%M %p")
            due_time = self._service.reminder_policy.calculate_due_time(entry.start_time).astimezone(tz)
            due_str = due_time.strftime("%Y-%m-%d %I:%M %p")
            return (
                f"Done! I've updated the calendar.\n\n"
                f"🔄 Successfully rescheduled *{entry.title}* (`{entry.entry_id}`):\n"
                f"• *New Start:* {start_str} ({entry.timezone})\n"
                f"• *New Reminder Due:* {due_str} ({entry.timezone})\n"
                f"• *Version:* {entry.version} (prior pending reminders were cancelled and recalculated)."
            )

        # Default: create
        local_start = entry.start_time.astimezone(tz)
        start_str = local_start.strftime("%Y-%m-%d %I:%M %p")
        due_time = self._service.reminder_policy.calculate_due_time(entry.start_time).astimezone(tz)
        due_str = due_time.strftime("%Y-%m-%d %I:%M %p")
        return (
            f"Done! I've added it to the calendar.\n\n"
            f"✅ Successfully scheduled *{entry.entry_type.value.capitalize()}*:\n"
            f"• *Title:* {entry.title}\n"
            f"• *ID:* `{entry.entry_id}`\n"
            f"• *Scheduled Start:* {start_str} ({entry.timezone})\n"
            f"• *Audience:* {self._format_audience(entry)}\n"
            f"• *Reminder Scheduled:* {due_str} ({entry.timezone}) [exactly 15 hours before start]"
        )

    def execute_structured(
        self,
        action: str,
        parameters: dict[str, Any],
        *,
        user_id: str,
    ) -> str:
        """
        Execute a calendar action with structured parameters and return truthful confirmation.
        """
        act = action.lower().strip()
        if act in ("create", "create_event", "schedule", "add"):
            entry = self.create_entry_structured(parameters, user_id=user_id)
            return self.format_confirmation(entry, operation="create")
        elif act in ("update", "update_event", "reschedule", "modify"):
            entry = self.update_entry_structured(parameters, user_id=user_id)
            return self.format_confirmation(entry, operation="update")
        elif act in ("cancel", "cancel_event", "delete", "remove"):
            entry = self.cancel_entry_structured(parameters, user_id=user_id)
            return self.format_confirmation(entry, operation="cancel")
        else:
            raise InvalidCalendarEntryError(f"Unsupported calendar action: '{action}'")
