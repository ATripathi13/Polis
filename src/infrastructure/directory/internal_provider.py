"""
Internal Authoritative Employee Directory Provider for POLIS.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from domain.employee.models import EmployeeLeave, EmployeeProfile
from .base import EmployeeDirectoryProvider


_VERIFIED_EMPLOYEES: list[dict[str, Any]] = [
    {
        "employee_id": "EMP-001",
        "full_name": "Akshat Tripathi",
        "preferred_name": "Akshat",
        "role": "AI Agent Implementor",
        "department": "Engineering",
        "team": "Core AI & Agent Systems",
        "reporting_manager": "Nav Thethi",
        "working_hours": "09:30 - 18:30",
        "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "time_zone": "Asia/Kolkata",
        "responsibilities": [
            "Agentic AI architecture and implementation",
            "Cognitive planner and multi-step reasoning",
            "Slack and Teams connector pipelines",
            "Canonical identity resolution",
        ],
        "skills": ["Python", "FastAPI", "LLM Orchestration", "PostgreSQL", "Slack API", "Docker"],
        "areas_of_ownership": ["Agent Systems", "POLIS Core Engine", "Integrations"],
        "email": "akshat@example.com",
        "slack_user_id": "U0BB8T4BVEK",
        "teams_user_id": "29:akshat-tripathi-teams",
        "source": "Internal Directory",
    },
    {
        "employee_id": "EMP-002",
        "full_name": "Nav Thethi",
        "preferred_name": "Nav",
        "role": "Founder & Engineering Leadership",
        "department": "Leadership",
        "team": "Executive",
        "reporting_manager": None,
        "working_hours": "09:00 - 18:00",
        "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "time_zone": "Asia/Kolkata",
        "responsibilities": [
            "Organizational strategy and product roadmap",
            "High-level system design and review",
            "Executive decision making and milestone planning",
        ],
        "skills": ["System Architecture", "Leadership", "Product Strategy", "Full Stack Development"],
        "areas_of_ownership": ["Product Roadmap", "Organizational Strategy"],
        "email": "nav@navthethi.com",
        "slack_user_id": "U0BBHB87SJF",
        "teams_user_id": "29:nav-thethi-teams",
        "source": "Internal Directory",
    },
    {
        "employee_id": "EMP-003",
        "full_name": "Hemant Kumar Sah",
        "preferred_name": "Hemant",
        "role": "Full Stack Engineer",
        "department": "Engineering",
        "team": "Automation & Backend Integrations",
        "reporting_manager": "Nav Thethi",
        "working_hours": "09:30 - 18:30",
        "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "time_zone": "Asia/Kolkata",
        "responsibilities": [
            "Workflow automations and webhook integrations",
            "GHL (GoHighLevel) forms and Twilio SMS verification",
            "Marketing automation pipelines",
            "Backend API development and maintenance",
        ],
        "skills": ["Python", "Node.js", "Webhook Integrations", "Twilio API", "GHL Automation", "REST APIs"],
        "areas_of_ownership": ["Marketing Automation", "SMS Verification", "Workflow Integrations"],
        "email": "hemant@example.com",
        "slack_user_id": "U0BU41F6CTD",
        "teams_user_id": "29:hemant-sah-teams",
        "source": "Internal Directory",
    },
    {
        "employee_id": "EMP-004",
        "full_name": "Vijay Sharma",
        "preferred_name": "Vijay",
        "role": "Full Stack Engineer",
        "department": "Engineering",
        "team": "Web & Client Platforms",
        "reporting_manager": "Nav Thethi",
        "working_hours": "09:30 - 18:30",
        "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "time_zone": "Asia/Kolkata",
        "responsibilities": [
            "Website maintenance, redesign and landing pages (navthethi.com)",
            "Frontend client application development",
            "Form builders and token integrations",
            "Integration testing and UI performance",
        ],
        "skills": ["React", "TypeScript", "Next.js", "CSS/Tailwind", "Python", "API Integration"],
        "areas_of_ownership": ["Website & Landing Pages", "Web Platforms", "Client UI"],
        "email": "vijay@example.com",
        "slack_user_id": "U0C3EE6L8AE",
        "teams_user_id": "29:vijay-sharma-teams",
        "source": "Internal Directory",
    },
    {
        "employee_id": "EMP-005",
        "full_name": "Gurkirat Singh",
        "preferred_name": "Gurkirat",
        "role": "Operations & Quality Specialist",
        "department": "Operations",
        "team": "Operations & QA",
        "reporting_manager": "Nav Thethi",
        "working_hours": "09:30 - 18:30",
        "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "time_zone": "Asia/Kolkata",
        "responsibilities": [
            "Operational item tracking and review",
            "Quality assurance and process compliance",
            "Team coordination and risk identification",
        ],
        "skills": ["Quality Assurance", "Process Management", "Test Automation", "Jira"],
        "areas_of_ownership": ["Operations Quality", "Compliance Processes"],
        "email": "gurkirat@example.com",
        "slack_user_id": "U0BBPU6400M",
        "teams_user_id": "29:gurkirat-singh-teams",
        "source": "Internal Directory",
    },
    {
        "employee_id": "EMP-006",
        "full_name": "Pravesh Verma",
        "preferred_name": "Pravesh",
        "role": "Software Engineer",
        "department": "Engineering",
        "team": "Infrastructure & Systems",
        "reporting_manager": "Nav Thethi",
        "working_hours": "09:30 - 18:30",
        "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "time_zone": "Asia/Kolkata",
        "responsibilities": [
            "Database maintenance and query optimization",
            "Cloud infrastructure and deployment automation",
            "Monitoring and system reliability",
        ],
        "skills": ["PostgreSQL", "Docker", "Linux", "Python", "CI/CD", "Monitoring"],
        "areas_of_ownership": ["Database Systems", "Cloud Deployment"],
        "email": "pravesh@example.com",
        "slack_user_id": "U0BBRSJCR7U",
        "teams_user_id": "29:pravesh-verma-teams",
        "source": "Internal Directory",
    },
    {
        "employee_id": "EMP-007",
        "full_name": "Nishchay",
        "preferred_name": "Nishchay",
        "role": "Product & UX Designer",
        "department": "Product",
        "team": "Design & UX",
        "reporting_manager": "Nav Thethi",
        "working_hours": "10:00 - 19:00",
        "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "time_zone": "Asia/Kolkata",
        "responsibilities": [
            "Product UX workflows and user interface design",
            "Interactive design systems and mockups",
            "Feature specifications and usability testing",
        ],
        "skills": ["Figma", "Design Systems", "User Research", "Wireframing", "Product Design"],
        "areas_of_ownership": ["Product UX", "Design System"],
        "email": "nishchay@example.com",
        "slack_user_id": "U0BBWLMNVGC",
        "teams_user_id": "29:nishchay-teams",
        "source": "Internal Directory",
    },
]

_VERIFIED_LEAVES: list[EmployeeLeave] = [
    EmployeeLeave(
        leave_id="LV-001",
        employee_id="EMP-004",  # Vijay Sharma
        leave_type="Approved Leave",
        start_date=date(2026, 11, 12),
        end_date=date(2026, 11, 13),
        status="approved",
        notes="Pre-approved personal leave",
        is_approved=True,
    ),
    EmployeeLeave(
        leave_id="LV-002",
        employee_id="EMP-003",  # Hemant Kumar Sah
        leave_type="Annual Leave",
        start_date=date(2026, 11, 20),
        end_date=date(2026, 11, 21),
        status="approved",
        notes="Approved annual vacation",
        is_approved=True,
    ),
]


class InternalEmployeeDirectoryProvider(EmployeeDirectoryProvider):
    """
    Internal authoritative directory provider containing verified employee profiles
    and approved leave records.
    """

    def __init__(
        self,
        employees: list[dict[str, Any]] | None = None,
        leaves: list[EmployeeLeave] | None = None,
    ) -> None:
        raw_list = employees if employees is not None else _VERIFIED_EMPLOYEES
        self._profiles: dict[str, EmployeeProfile] = {}
        self._slack_id_map: dict[str, str] = {}
        self._teams_id_map: dict[str, str] = {}
        self._leaves: list[EmployeeLeave] = list(leaves if leaves is not None else _VERIFIED_LEAVES)

        for item in raw_list:
            prof = EmployeeProfile(
                employee_id=item["employee_id"],
                full_name=item["full_name"],
                preferred_name=item.get("preferred_name"),
                role=item.get("role", ""),
                department=item.get("department", ""),
                team=item.get("team", ""),
                reporting_manager=item.get("reporting_manager"),
                working_hours=item.get("working_hours", "09:30 - 18:30"),
                working_days=item.get("working_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]),
                time_zone=item.get("time_zone", "Asia/Kolkata"),
                responsibilities=list(item.get("responsibilities", [])),
                skills=list(item.get("skills", [])),
                areas_of_ownership=list(item.get("areas_of_ownership", [])),
                email=item.get("email"),
                slack_user_id=item.get("slack_user_id"),
                teams_user_id=item.get("teams_user_id"),
                source=item.get("source", "Internal Directory"),
                metadata=dict(item.get("metadata", {})),
            )
            self._profiles[prof.employee_id] = prof
            if prof.slack_user_id:
                self._slack_id_map[prof.slack_user_id] = prof.employee_id
            if prof.teams_user_id:
                self._teams_id_map[prof.teams_user_id] = prof.employee_id

    def is_connected(self) -> bool:
        return True

    def get_employee(self, employee_id: str) -> EmployeeProfile | None:
        if not employee_id:
            return None
        clean_id = employee_id.strip()

        # Check internal ID
        if clean_id in self._profiles:
            return self._profiles[clean_id]

        # Check Slack ID
        if clean_id in self._slack_id_map:
            return self._profiles[self._slack_id_map[clean_id]]

        # Check Teams ID
        if clean_id in self._teams_id_map:
            return self._profiles[self._teams_id_map[clean_id]]

        # Case-insensitive full name exact match
        for prof in self._profiles.values():
            if prof.full_name.lower() == clean_id.lower() or (
                prof.email and prof.email.lower() == clean_id.lower()
            ):
                return prof

        return None

    def search_employees(self, query: str) -> list[EmployeeProfile]:
        if not query or not query.strip():
            return []
        q = query.strip().lower()

        matches: list[EmployeeProfile] = []
        for prof in self._profiles.values():
            if (
                q in prof.full_name.lower()
                or (prof.preferred_name and q in prof.preferred_name.lower())
                or q in prof.role.lower()
                or q in prof.department.lower()
                or q in prof.team.lower()
                or any(q in r.lower() for r in prof.responsibilities)
                or any(q in s.lower() for s in prof.skills)
                or any(q in o.lower() for o in prof.areas_of_ownership)
            ):
                matches.append(prof)
        return matches

    def get_leaves(
        self,
        employee_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[EmployeeLeave]:
        emp = self.get_employee(employee_id)
        if not emp:
            return []

        results: list[EmployeeLeave] = []
        for lv in self._leaves:
            if lv.employee_id == emp.employee_id:
                if start_date and lv.end_date < start_date:
                    continue
                if end_date and lv.start_date > end_date:
                    continue
                results.append(lv)
        return results
