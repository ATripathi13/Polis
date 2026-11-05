"""
Core Team Priority Tracker and Deterministic Priority Ranking Service for POLIS.

Answers questions such as:
- What is our highest-priority team task right now?
- What is the team currently focusing on?
- What is the most important active sprint item?
- What is blocking the current milestone?
- What is our highest-ranking overarching task currently in progress?

Deterministic ranking algorithm incorporates:
1. Explicit project-management priority (Critical > High > Medium > Low).
2. In-progress status (active team focus).
3. Active sprint or milestone membership.
4. Critical flags & blockers.
5. Upcoming deadlines.
6. Overarching initiative vs leaf subtask distinction.
7. Recent updates and changes.

Standardized output format:
Highest Priority Team Task: Exact task title
Status: Verified status
Priority: Source priority
Owner: Assigned person
Project / Sprint: Relevant project
Deadline: Due date, if available
Reason for Ranking: Evidence-backed explanation
Source: Provider and original item link
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from domain.project_management.models import Milestone, Project, Sprint, WorkItem
from infrastructure.project_management.base import ProjectManagementProvider
from infrastructure.project_management.operational_item_provider import OperationalItemProjectProvider

logger = logging.getLogger(__name__)


@dataclass
class RankedWorkItem:
    """A work item annotated with its deterministic composite ranking score and factors."""
    item: WorkItem
    score: float
    reasons: list[str] = field(default_factory=list)


class PriorityRankingService:
    """
    Coordinates project management integrations and evaluates deterministic priority ranking.
    """

    TIMEZONE = ZoneInfo("Asia/Kolkata")

    # Priority base weights
    PRIORITY_WEIGHTS = {
        "critical": 100.0,
        "high": 70.0,
        "medium": 40.0,
        "low": 10.0,
    }

    def __init__(
        self,
        providers: list[ProjectManagementProvider] | None = None,
        operational_item_repository: Any | None = None,
    ) -> None:
        if providers is not None:
            self._providers = providers
        else:
            self._providers = [OperationalItemProjectProvider(repository=operational_item_repository)]

    def get_all_work_items(self) -> list[WorkItem]:
        """Aggregate work items across all connected project management providers."""
        all_items: list[WorkItem] = []
        for prov in self._providers:
            if prov.is_connected():
                try:
                    items = prov.get_work_items()
                    all_items.extend(items)
                except Exception as exc:
                    logger.warning("Error fetching work items from %s: %s", prov.__class__.__name__, exc)
        return all_items

    def calculate_item_score(self, item: WorkItem, overarching_focus: bool = True) -> tuple[float, list[str]]:
        """
        Calculate deterministic composite score for a work item.
        """
        score = 0.0
        reasons: list[str] = []

        # 1. Base Priority
        norm_prio = item.priority.lower()
        base_prio_score = self.PRIORITY_WEIGHTS.get(norm_prio, 30.0)
        score += base_prio_score
        reasons.append(f"Source priority is '{item.source_priority}' (+{base_prio_score:.0f})")

        # 2. In-Progress Status (+45 points)
        if item.status == "in_progress":
            score += 45.0
            reasons.append("Currently active and in progress (+45)")
        elif item.status == "blocked":
            score += 25.0
            reasons.append("Item is blocked but active (+25)")
        elif item.status == "open":
            score += 15.0
            reasons.append("Open in backlog/sprint (+15)")
        elif item.status in ("completed", "closed", "cancelled"):
            # Completed tasks should not rank as highest active in-progress task
            score -= 200.0
            reasons.append(f"Already {item.status} (-200)")

        # 3. Active Sprint / Milestone (+30 points)
        if item.sprint_id or item.sprint_name:
            score += 30.0
            reasons.append(f"Committed to active sprint '{item.sprint_name or item.sprint_id}' (+30)")

        # 4. Overarching Initiative vs Leaf Subtask
        if overarching_focus:
            if item.is_overarching or item.item_type in ("initiative", "epic"):
                score += 40.0
                reasons.append("Overarching initiative/epic spanning core systems (+40)")
            elif item.parent_id or item.item_type in ("subtask", "task"):
                score += 5.0
                reasons.append("Component subtask (+5)")
        else:
            if item.item_type in ("task", "subtask"):
                score += 20.0

        # 5. Blockers & Dependencies
        if item.blockers:
            score += 15.0
            reasons.append(f"Has {len(item.blockers)} active blocker(s) requiring immediate resolution (+15)")

        # 6. Approaching Deadline
        if item.deadline:
            now = datetime.now(timezone.utc)
            deadline_utc = item.deadline if item.deadline.tzinfo else item.deadline.replace(tzinfo=timezone.utc)
            days_left = (deadline_utc - now).total_seconds() / 86400.0
            if days_left <= 2:
                score += 35.0
                reasons.append(f"Imminent deadline in {max(0, int(days_left))} day(s) (+35)")
            elif days_left <= 7:
                score += 20.0
                reasons.append(f"Upcoming deadline within {int(days_left)} days (+20)")


        return score, reasons

    def rank_work_items(
        self,
        items: list[WorkItem] | None = None,
        overarching_focus: bool = True,
        in_progress_only: bool = False,
    ) -> list[RankedWorkItem]:
        """
        Rank work items deterministically based on composite score.
        """
        pool = items if items is not None else self.get_all_work_items()

        if in_progress_only:
            pool = [it for it in pool if it.status == "in_progress"]

        ranked: list[RankedWorkItem] = []
        for it in pool:
            score, reasons = self.calculate_item_score(it, overarching_focus=overarching_focus)
            ranked.append(RankedWorkItem(item=it, score=score, reasons=reasons))

        # Sort descending by score; break ties by title alphabetical stability
        ranked.sort(key=lambda r: (-r.score, r.item.title))
        return ranked

    def get_highest_ranking_in_progress_task(self) -> RankedWorkItem | None:
        """
        Identify the highest-ranking overarching team task currently in progress.
        """
        # First attempt: strictly in_progress overarching initiatives
        ranked_in_prog = self.rank_work_items(overarching_focus=True, in_progress_only=True)
        if ranked_in_prog:
            return ranked_in_prog[0]

        # Second attempt: any in-progress work item
        all_in_prog = [it for it in self.get_all_work_items() if it.status == "in_progress"]
        if all_in_prog:
            ranked_all_in_prog = self.rank_work_items(items=all_in_prog, overarching_focus=True)
            if ranked_all_in_prog:
                return ranked_all_in_prog[0]

        # Third attempt: highest ranked open item if nothing is strictly in_progress
        ranked_all = self.rank_work_items(overarching_focus=True, in_progress_only=False)
        active_candidates = [r for r in ranked_all if r.item.status not in ("completed", "closed", "cancelled")]
        if active_candidates:
            return active_candidates[0]

        return None

    def answer_priority_query(self, query: str) -> str:
        """
        Answer single-priority and top-N team priority questions.
        """
        count_match = re.search(r"\btop\s+(\d+)\b", query, re.IGNORECASE)

        if count_match:
            requested_count = min(max(int(count_match.group(1)), 1), 20)
            ranked = self.rank_work_items(overarching_focus=True)
            active = [
                item for item in ranked
                if item.item.status not in ("completed", "closed", "cancelled")
            ][:requested_count]

            if not active:
                return (
                    "**Active Team Priorities:** No active tasks currently recorded\n\n"
                    "**Status:** Backlog empty or all recorded items completed"
                )

            sections = [f"**Top {len(active)} Active Team Priorities:**"]
            for index, ranked_item in enumerate(active, 1):
                item = ranked_item.item
                deadline = (
                    item.deadline.strftime("%b %d, %Y")
                    if item.deadline else "Not explicitly set"
                )
                owner = item.owner_name or item.owner_id or "Unassigned"
                project = item.project_name or item.project_id or "Not specified"
                if item.sprint_name:
                    project = f"{project} / {item.sprint_name}"

                sections.append(
                    f"**{index}. {item.title}**\n"
                    f"**Status:** {item.source_status}\n"
                    f"**Priority:** {item.source_priority}\n"
                    f"**Owner:** {owner}\n"
                    f"**Project / Sprint:** {project}\n"
                    f"**Deadline:** {deadline}\n"
                    f"**Reason for Ranking:** {' • '.join(ranked_item.reasons)}"
                )

            return "\n\n".join(sections)

        highest = self.get_highest_ranking_in_progress_task()
        if not highest:
            return (
                "**Highest Priority Team Task:** No active tasks currently recorded\n\n"
                "**Status:** Backlog empty or all recorded items completed\n\n"
                "**Priority:** N/A\n\n"
                "**Owner:** Unassigned\n\n"
                "**Project / Sprint:** N/A\n\n"
                "**Deadline:** None\n\n"
                "**Reason for Ranking:** No active work items available in connected project management providers.\n\n"
                "**Source:** Project Management Integration"
            )

        item = highest.item
        deadline_str = (
            item.deadline.strftime("%b %d, %Y")
            if item.deadline else "Not explicitly set"
        )
        owner_str = item.owner_name or item.owner_id or "Unassigned"
        proj_sprint = item.project_name or item.project_id
        if item.sprint_name:
            proj_sprint = f"{proj_sprint} / {item.sprint_name}"

        reason_text = " • ".join(highest.reasons)
        source_link = item.url or f"{item.source_provider} (ID: {item.item_id})"

        output = [
            f"**Highest Priority Team Task:** {item.title}",
            f"**Status:** {item.source_status}",
            f"**Priority:** {item.source_priority}",
            f"**Owner:** {owner_str}",
            f"**Project / Sprint:** {proj_sprint}",
            f"**Deadline:** {deadline_str}",
            f"**Reason for Ranking:** {reason_text}",
            f"**Source:** {source_link}",
        ]
        return "\n\n".join(output)
