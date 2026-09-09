from __future__ import annotations

from datetime import datetime, timedelta

from domain.activity import ActivityEvent, ActivityType

from .attendance_result import AttendanceResult, BreakPeriod


class AttendanceCalculator:
    """
    Deterministically calculates attendance from activity events.

    No LLM or natural-language reasoning is used here.
    """

    def calculate(self, *, events: list[ActivityEvent], now: datetime) -> AttendanceResult:
        if not events:
            raise ValueError("At least one activity event is required.")

        ordered_events = sorted(
            events,
            key=lambda event: (event.occurred_at, event.created_at),
        )

        first_event = ordered_events[0]

        work_started_at = None
        work_ended_at = None

        breaks: list[BreakPeriod] = []

        total_break_duration = timedelta(0)
        active_work_duration = timedelta(0)

        current_state = "unknown"

        open_break_started_at = None
        active_work_started_at = None

        for event in ordered_events:
            occurred_at = event.occurred_at

            if event.activity_type == ActivityType.WORK_START:
                # A new WORK_START begins a new work session.
                if work_started_at is None:
                    work_started_at = occurred_at

                work_ended_at = None
                current_state = "working"

                if active_work_started_at is None:
                    active_work_started_at = occurred_at

            elif event.activity_type == ActivityType.BREAK_START:
                # A break after WORK_END does not reopen the work session.
                if current_state == "off_work":
                    continue

                current_state = "on_break"

                if open_break_started_at is not None:
                    continue

                open_break_started_at = occurred_at

                if active_work_started_at is not None:
                    active_work_duration += max(
                        timedelta(0),
                        occurred_at - active_work_started_at,
                    )
                    active_work_started_at = None

            elif event.activity_type == ActivityType.BREAK_END:
                # A break after WORK_END is not part of the active work session.
                if current_state == "off_work":
                    continue

                if open_break_started_at is not None:
                    break_period = BreakPeriod(
                        started_at=open_break_started_at,
                        ended_at=occurred_at,
                    )

                    breaks.append(break_period)

                    total_break_duration += break_period.duration(now=now)

                    open_break_started_at = None

                current_state = "working"

                if active_work_started_at is None:
                    active_work_started_at = occurred_at

            elif event.activity_type == ActivityType.WORK_END:
                if open_break_started_at is not None:
                    break_period = BreakPeriod(
                        started_at=open_break_started_at,
                        ended_at=occurred_at,
                    )

                    breaks.append(break_period)

                    total_break_duration += break_period.duration(now=now)

                    open_break_started_at = None

                if active_work_started_at is not None:
                    active_work_duration += max(
                        timedelta(0),
                        occurred_at - active_work_started_at,
                    )
                    active_work_started_at = None

                work_ended_at = occurred_at
                current_state = "off_work"

        # Handle an active break.
        if open_break_started_at is not None:
            active_break = BreakPeriod(
                started_at=open_break_started_at,
            )

            breaks.append(active_break)

            total_break_duration += active_break.duration(now=now)

            current_state = "on_break"

        # Handle active work only if the person has not finished work.
        elif active_work_started_at is not None:
            active_work_duration += max(
                timedelta(0),
                now - active_work_started_at,
            )

            if current_state != "off_work":
                current_state = "working"

        return AttendanceResult(
            person_id=first_event.person_id,
            person_name=first_event.person_name,
            work_started_at=work_started_at,
            work_ended_at=work_ended_at,
            breaks=breaks,
            total_break_duration=total_break_duration,
            active_work_duration=active_work_duration,
            current_state=current_state,
        )
