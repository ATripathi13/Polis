"""
HR & Team Directory Querying Service for POLIS.

Answers employee questions such as:
- What is Hemant's role?
- What are Vijay's responsibilities?
- What are Akshat's working hours?
- When is Hemant's next scheduled holiday?
- Who is responsible for backend development?
- What is this employee currently working on?

Integrates:
- Canonical identity resolution and ambiguous-name detection.
- Extensible directory providers (Internal, BambooHR, Workday, Roster API).
- Calendar Agent for organization holidays and approved leave tracking.
- PersonWorkService for active work items.

Strict response format:
Employee: Full name
Role: Verified designation
Working Hours: Verified schedule and time zone
Responsibilities: Primary responsibilities
Upcoming Holidays: Relevant approved leave and holidays
Current Work: Active work items, if available
Source: Authoritative data source
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from application.identity.canonical_identity_service import CanonicalIdentityService
from domain.employee.models import EmployeeLeave, EmployeeProfile
from infrastructure.directory.base import EmployeeDirectoryProvider
from infrastructure.directory.internal_provider import InternalEmployeeDirectoryProvider

logger = logging.getLogger(__name__)


class TeamDirectoryService:
    """
    Coordinates employee directory queries, working hours, leave/holiday schedules,
    and current work aggregation.
    """

    TIMEZONE = ZoneInfo("Asia/Kolkata")

    def __init__(
        self,
        directory_providers: list[EmployeeDirectoryProvider] | None = None,
        identity_service: CanonicalIdentityService | None = None,
        calendar_agent: Any | None = None,
        calendar_service: Any | None = None,
        person_work_service: Any | None = None,
    ) -> None:
        self._providers = directory_providers or [InternalEmployeeDirectoryProvider()]
        self._identity = identity_service or CanonicalIdentityService()
        self._calendar_agent = calendar_agent
        self._calendar_service = calendar_service or getattr(calendar_agent, "service", None)
        self._person_work_service = person_work_service

    # =========================================================================
    # EMPLOYEE LOOKUP & AMBIGUITY RESOLUTION
    # =========================================================================

    def find_employee(self, query: str) -> tuple[EmployeeProfile | None, list[EmployeeProfile], str | None]:
        """
        Lookup an employee by ID, name, email, or Slack/Teams ID.
        Returns:
            (resolved_profile, candidate_matches, clarification_prompt)
        """
        if not query or not query.strip():
            return None, [], "Please provide an employee name or ID."

        clean_query = query.strip()

        # 1. Direct ID lookup across connected providers
        for prov in self._providers:
            if prov.is_connected():
                match = prov.get_employee(clean_query)
                if match:
                    return match, [match], None

        # 2. Search by name/keywords across providers
        candidates: dict[str, EmployeeProfile] = {}
        for prov in self._providers:
            if prov.is_connected():
                matches = prov.search_employees(clean_query)
                for m in matches:
                    candidates[m.employee_id] = m

        cand_list = list(candidates.values())

        # Exact match check
        exact_matches = [
            c for c in cand_list
            if c.full_name.lower() == clean_query.lower()
            or (c.preferred_name and c.preferred_name.lower() == clean_query.lower())
        ]
        if len(exact_matches) == 1:
            return exact_matches[0], cand_list, None

        # If multiple exact or close matches found, handle ambiguity
        if len(cand_list) > 1:
            # Check if one candidate's full name starts with the query word
            starts_with = [
                c for c in cand_list
                if c.full_name.lower().startswith(clean_query.lower())
                or (c.preferred_name and c.preferred_name.lower() == clean_query.lower())
            ]
            if len(starts_with) == 1:
                return starts_with[0], cand_list, None

            # Multiple candidates -> return clarification prompt
            names = [f"• {c.full_name} ({c.role}, {c.team or c.department})" for c in cand_list]
            clarification = (
                f"I found multiple people matching '{clean_query}':\n"
                + "\n".join(names)
                + "\n\nCould you please specify which person you mean by their full name?"
            )
            return None, cand_list, clarification

        if len(cand_list) == 1:
            return cand_list[0], cand_list, None

        return None, [], None

    # =========================================================================
    # WORKING HOURS & HOLIDAY INTEGRATION
    # =========================================================================

    def get_upcoming_holidays_and_leaves(
        self,
        employee: EmployeeProfile,
        days_ahead: int = 30,
    ) -> list[str]:
        """
        Collect upcoming approved leaves and organizational holidays.
        Differentiates approved personal leave from public/company holidays.
        """
        today = datetime.now(self.TIMEZONE).date()
        cutoff = today + timedelta(days=days_ahead)
        items: list[str] = []

        # 1. Approved Leave from Directory Providers
        for prov in self._providers:
            if prov.is_connected():
                leaves = prov.get_leaves(employee.employee_id, start_date=today, end_date=cutoff)
                for lv in leaves:
                    if lv.status.lower() == "approved" or lv.is_approved:
                        if lv.start_date == lv.end_date:
                            date_str = lv.start_date.strftime("%b %d, %Y")
                        else:
                            date_str = f"{lv.start_date.strftime('%b %d')} - {lv.end_date.strftime('%b %d, %Y')}"
                        notes_str = f" ({lv.notes})" if lv.notes else ""
                        items.append(f"Approved Leave: {lv.leave_type} on {date_str}{notes_str}")

        # 2. Organization Holidays from Calendar Agent / Service
        if self._calendar_service is not None:
            try:
                start_dt = datetime.combine(today, datetime.min.time(), tzinfo=self.TIMEZONE)
                end_dt = datetime.combine(cutoff, datetime.max.time(), tzinfo=self.TIMEZONE)
                cal_repo = getattr(self._calendar_service, "_repository", None)
                if cal_repo is not None:
                    entries = cal_repo.find_entries(start_time=start_dt, end_time=end_dt)
                    for entry in entries:
                        etype = str(getattr(entry, "entry_type", "")).lower()
                        if "holiday" in etype:
                            title = getattr(entry, "title", "Organization Holiday")
                            ent_start = getattr(entry, "start_time", None)
                            if ent_start:
                                ent_date = ent_start.astimezone(self.TIMEZONE).strftime("%b %d, %Y")
                                items.append(f"Public/Organization Holiday: {title} ({ent_date})")
            except Exception as exc:
                logger.warning("Error fetching calendar holidays: %s", exc)

        return items

    def get_active_work_items(self, employee: EmployeeProfile) -> list[str]:
        """
        Fetch active work items from PersonWorkService if available.
        """
        if self._person_work_service is not None:
            try:
                target_id = employee.slack_user_id or employee.full_name
                summary = self._person_work_service.get_person_work_summary(target_id)
                if summary:
                    active = getattr(summary, "active_work", [])
                    if active:
                        formatted_items = []
                        for item in active[:3]:
                            if isinstance(item, dict):
                                description = item.get("work_item") or item.get("summary")
                                status = item.get("status")
                                project = item.get("project")
                                deadline = item.get("deadline")
                            else:
                                description = getattr(item, "work_item", None)
                                status = getattr(item, "status", None)
                                project = getattr(item, "project", None)
                                deadline = getattr(item, "deadline", None)

                            if not description or not isinstance(description, str):
                                continue

                            details = []
                            if status:
                                details.append(str(status).replace("_", " ").title())
                            if project:
                                details.append(f"Project: {project}")
                            if deadline:
                                details.append(f"Deadline: {deadline}")

                            formatted = description.strip()
                            if details:
                                formatted += f" ({'; '.join(details)})"

                            formatted_items.append(formatted)

                        if formatted_items:
                            return formatted_items
            except Exception as exc:
                logger.warning("Error fetching active work for %s: %s", employee.full_name, exc)
        return []

    # =========================================================================
    # QUERY HANDLING & FORMATTING
    # =========================================================================

    def answer_directory_query(self, query: str) -> str:
        """
        Produce a standardized, authoritative response for HR & Team Directory questions.
        """
        # Check if query is asking who is responsible for a topic/skill
        skill_match = re.search(r"who is (?:responsible for|handling|working on|in charge of) (.*?)(?:\?|$)", query, re.I)
        if skill_match:
            topic = skill_match.group(1).strip()
            return self._answer_responsibility_lookup(topic)

        # Extract person name candidate from query
        candidate_name = self._extract_name_candidate(query)
        emp, candidates, clarification = self.find_employee(candidate_name)

        if clarification:
            return clarification

        if not emp:
            # Fallback search whole query if candidate name extraction missed
            emp, candidates, clarification = self.find_employee(query)
            if clarification:
                return clarification
            if not emp:
                return f"I couldn't find an employee matching '{candidate_name or query}' in our verified directory."

        # Collect data fields
        holidays_and_leaves = self.get_upcoming_holidays_and_leaves(emp)
        active_work = self.get_active_work_items(emp)

        # Standardized Response Format
        output: list[str] = []
        output.append(f"**Employee:** {emp.full_name}")
        output.append(f"**Role:** {emp.role or 'Not documented'}")

        # Working hours & schedule
        days_str = ", ".join(emp.working_days) if emp.working_days else "Monday - Friday"
        output.append(f"**Working Hours:** {emp.working_hours} ({emp.time_zone}) [{days_str}]")

        # Responsibilities
        if emp.responsibilities:
            resp_str = "; ".join(emp.responsibilities)
            output.append(f"**Responsibilities:** {resp_str}")
        else:
            output.append("**Responsibilities:** None explicitly documented in directory")

        # Upcoming Holidays & Leaves
        if holidays_and_leaves:
            output.append(f"**Upcoming Holidays:** {'; '.join(holidays_and_leaves)}")
        else:
            output.append("**Upcoming Holidays:** No approved leave or holidays scheduled in the next 30 days")

        # Current Work
        if active_work:
            output.append(f"**Current Work:** {'; '.join(active_work)}")
        elif emp.areas_of_ownership:
            output.append(f"**Current Work:** Active in ownership areas: {', '.join(emp.areas_of_ownership)}")
        else:
            output.append("**Current Work:** No active workstreams currently recorded")

        # Source
        output.append(f"**Source:** {emp.source}")

        return "\n\n".join(output)

    def _answer_responsibility_lookup(self, topic: str) -> str:
        """Find employees whose responsibilities, skills, or areas of ownership match topic."""
        matches: list[EmployeeProfile] = []
        for prov in self._providers:
            if prov.is_connected():
                matches.extend(prov.search_employees(topic))

        if not matches:
            return f"I couldn't find anyone explicitly assigned to or responsible for '{topic}' in our directory."

        lines: list[str] = [f"Here are the team members responsible for or working on **{topic}**:"]
        for emp in matches:
            matching_items: list[str] = []
            for r in emp.responsibilities:
                if topic.lower() in r.lower():
                    matching_items.append(r)
            for o in emp.areas_of_ownership:
                if topic.lower() in o.lower():
                    matching_items.append(o)
            detail = f" — {', '.join(matching_items)}" if matching_items else ""
            lines.append(f"• **{emp.full_name}** ({emp.role}){detail}")

        lines.append(f"\n**Source:** Authoritative Directory")
        return "\n".join(lines)

    @staticmethod
    def _extract_name_candidate(query: str) -> str:
        """Extract suspected employee name from natural language query."""
        # Strip common prefixes
        cleaned = re.sub(
            r"^(what is|what are|when is|who is|tell me about|show me|check|get)\s+",
            "",
            query,
            flags=re.I,
        )
        # Match possessive: "Hemant's role" -> "Hemant"
        possessive = re.search(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'s", cleaned)
        if possessive:
            return possessive.group(1).strip()

        # Match "for <Name>"
        for_match = re.search(r"(?:for|about|from)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)", cleaned)
        if for_match:
            return for_match.group(1).strip()

        # Match simple words and remove surrounding punctuation.
        words = cleaned.split()
        if words:
            return re.sub(r"^[^\w]+|[^\w]+$", "", words[0]).strip()

        return re.sub(r"^[^\w]+|[^\w]+$", "", cleaned).strip()
