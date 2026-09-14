from __future__ import annotations

from application.activity.activity_service import ActivityService
from domain.activity import ActivityType
from domain.reasoning import Answer, Question
from datetime import datetime, timezone

class ActivityQuestionService:
    """
    Answers questions about currently observed activity.
    """

    def __init__(
        self,
        activity_service,
        now_provider=None,
    ):
        self._activity_service = activity_service
        self._now_provider = now_provider or (
            lambda: datetime.now(timezone.utc)
        )

    def answer(
        self,
        question: Question,
    ) -> Answer | None:

        normalized = (
            question.text
            .lower()
            .strip()
            .rstrip("?!.,")
        )

        normalized = " ".join(
            normalized.split()
        )
        timestamp_answer = self._answer_person_timestamp_question(
            normalized,
        )

        if timestamp_answer is not None:
            return timestamp_answer
        
        duration_answer = self._answer_person_duration_question(
            normalized,
        )

        if duration_answer is not None:
            return duration_answer
            
        # --------------------------------------------------
        # PERSON-SPECIFIC CURRENT STATE
        # --------------------------------------------------

        person_answer = self._answer_person_current_state(
            normalized,
        )

        if person_answer is not None:
            return person_answer

        # --------------------------------------------------
        # CURRENTLY ON BREAK
        # --------------------------------------------------

        if self._is_current_break_question(
            normalized,
        ):
            events = (
                self._activity_service
                .find_currently_on_break()
            )

            return self._build_people_answer(
                events=events,
                empty_text=(
                    "No one is currently recorded "
                    "as being on break."
                ),
                single_suffix="is currently on break.",
                multiple_prefix="Currently on break: ",
            )

        # --------------------------------------------------
        # CURRENTLY WORKING
        # --------------------------------------------------

        if self._is_current_working_question(
            normalized,
        ):
            events = (
                self._activity_service
                .find_currently_working()
            )

            return self._build_people_answer(
                events=events,
                empty_text=(
                    "No one is currently recorded "
                    "as working."
                ),
                single_suffix="is currently working.",
                multiple_prefix="Currently working: ",
            )

        # --------------------------------------------------
        # CURRENTLY OFF WORK
        # --------------------------------------------------

        if self._is_current_off_work_question(
            normalized,
        ):
            events = (
                self._activity_service
                .find_currently_off_work()
            )

            return self._build_people_answer(
                events=events,
                empty_text=(
                    "No one is currently recorded "
                    "as being off work."
                ),
                single_suffix="is currently off work.",
                multiple_prefix="Currently off work: ",
            )

        return None  
    # ======================================================
    # PERSON-SPECIFIC CURRENT STATE
    # ======================================================

    def _answer_person_current_state(
        self,
        text: str,
    ) -> Answer | None:

        patterns = (
            (" on break", "break"),
            (" currently on break", "break"),
            (" taking a break", "break"),
            (" currently taking a break", "break"),
            (" working", "working"),
            (" currently working", "working"),
            (" at work", "working"),
            (" currently at work", "working"),
            (" off work", "off_work"),
            (" currently off work", "off_work"),
        )

        if not text.startswith("is "):
            return None

        for suffix, expected_state in patterns:

            if not text.endswith(suffix):
                continue

            person_name = text[
                len("is "): -len(suffix)
            ].strip()

            if not person_name:
                return None

            events = (
                self._activity_service
                .find_people_by_name(person_name)
            )

            if not events:
                return Answer(
                    text=(
                        f"I don't have activity records "
                        f"for {person_name}."
                    ),
                )

            if len(events) > 1:
                names = ", ".join(
                    event.person_name
                    for event in events
                )

                return Answer(
                    text=(
                        f"I found multiple people matching "
                        f"{person_name}: {names}."
                    ),
                )

            event = events[0]

            if expected_state == "break":
                is_current = (
                    event.activity_type
                    == ActivityType.BREAK_START
                )
                state_text = "on break"

            elif expected_state == "working":
                is_current = (
                    event.activity_type
                    in {
                        ActivityType.WORK_START,
                        ActivityType.BREAK_END,
                    }
                )
                state_text = "working"

            else:
                is_current = (
                    event.activity_type
                    == ActivityType.WORK_END
                )
                state_text = "off work"

            if is_current:
                return Answer(
                    text=(
                        f"{event.person_name} "
                        f"is currently {state_text}."
                    ),
                )

            return Answer(
                text=(
                    f"{event.person_name} "
                    f"is not currently {state_text}."
                ),
            )

        return None   
    def _answer_person_duration_question(
        self,
        text: str,
    ) -> Answer | None:
        patterns = (
            (
                "how much did ",
                " work today",
                "work_total",
            ),
            (
                "how much break time did ",
                " take today",
                "break_total",
            ),
            (
                "how long has ",
                " been working",
                "work_active",
            ),
            (
                "how long has ",
                " been on break",
                "break_active",
            ),
        )

        for prefix, suffix, duration_type in patterns:
            if not text.startswith(prefix):
                continue

            if not text.endswith(suffix):
                continue

            person_name = text[
                len(prefix): -len(suffix)
            ].strip()

            if not person_name:
                return None

            people = self._activity_service.find_people_by_name(
                person_name,
            )

            if not people:
                return Answer(
                    text=(
                        f"I don't have activity records "
                        f"for {person_name}."
                    ),
                )

            if len(people) > 1:
                names = ", ".join(
                    person.person_name
                    for person in people
                )

                return Answer(
                    text=(
                        f"I found multiple people matching "
                        f"{person_name}: {names}."
                    ),
                )

            person = people[0]

            now = self._now_provider()

            start_of_today = now.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )

            result = self._activity_service.calculate_attendance(
                person.person_id,
                start=start_of_today,
                end=now,
                now=now,
            )

            if result is None:
                return Answer(
                    text=(
                        f"I don't have activity records "
                        f"for {person.person_name} today."
                    ),
                )

            if duration_type == "work_total":
                duration = result.active_work_duration

                return Answer(
                    text=(
                        f"{person.person_name} worked "
                        f"{_format_duration(duration)} today."
                    ),
                )

            if duration_type == "break_total":
                duration = result.total_break_duration

                return Answer(
                    text=(
                        f"{person.person_name} took "
                        f"{_format_duration(duration)} "
                        f"of break time today."
                    ),
                )

            if duration_type == "work_active":
                if result.current_state != "working":
                    return Answer(
                        text=(
                            f"{person.person_name} is not "
                            f"currently working."
                        ),
                    )

                return Answer(
                    text=(
                        f"{person.person_name} has been "
                        f"working for "
                        f"{_format_duration(_current_work_duration(result, now))}."
                    ),
                )

            if duration_type == "break_active":
                if result.current_state != "on_break":
                    return Answer(
                        text=(
                            f"{person.person_name} is not "
                            f"currently on break."
                        ),
                    )

                current_break = result.current_break

                if current_break is None:
                    return Answer(
                        text=(
                            f"{person.person_name} is not "
                            f"currently on break."
                        ),
                    )

                duration = now - current_break.started_at

                return Answer(
                    text=(
                        f"{person.person_name} has been "
                        f"on break for "
                        f"{_format_duration(duration)}."
                    ),
                )

        return None
    
    def _answer_person_timestamp_question(
        self,
        text: str,
    ) -> Answer | None:
        patterns = (
            ("when did ", " start work", ActivityType.WORK_START),
            ("when did ", " go on break", ActivityType.BREAK_START),
            ("when did ", " come back", ActivityType.BREAK_END),
            ("when did ", " finish work", ActivityType.WORK_END),
        )

        for prefix, suffix, activity_type in patterns:
            if not text.startswith(prefix):
                continue

            if not text.endswith(suffix):
                continue

            person_name = text[
                len(prefix): -len(suffix)
            ].strip()

            if not person_name:
                return None

            events = self._activity_service.find_for_person_by_name(
                person_name,
            )

            if not events:
                return Answer(
                    text=(
                        f"I don't have activity records "
                        f"for {person_name}."
                    ),
                )

            if len(events) > 1:
                names = ", ".join(
                    event.person_name
                    for event in events
                )

                return Answer(
                    text=(
                        f"I found multiple people matching "
                        f"{person_name}: {names}."
                    ),
                )

            person = events[0]

            activity_events = self._activity_service.find_for_person(
                person.person_id,
            )

            today = self._now_provider().date()

            today_events = [
                event
                for event in activity_events
                if event.occurred_at.astimezone(timezone.utc).date() == today
            ]

            matching_events = [
                event
                for event in today_events
                if event.activity_type == activity_type
            ]

            if not matching_events:
                return Answer(
                    text=(
                        f"I don't have a recorded "
                        f"{activity_type.value.replace('_', ' ')} "
                        f"for {person.person_name}."
                    ),
                )

            event = matching_events[-1]

            return Answer(
                text=(
                    f"{person.person_name} "
                    f"{activity_type.value.replace('_', ' ')} "
                    f"at {event.occurred_at.isoformat()}."
                ),
            )

        return None     
    # ======================================================
    # QUESTION DETECTORS
    # ======================================================

    @staticmethod
    def _is_current_break_question(
        text: str,
    ) -> bool:

        return text in {
            "who is on break",
            "who is currently on break",
            "who's on break",
            "whos on break",
            "who is on a break",
            "who is currently on a break",
            "who is taking a break",
            "who's taking a break",
            "who is currently taking a break",
        }

    @staticmethod
    def _is_current_working_question(
        text: str,
    ) -> bool:

        return text in {
            "who is working",
            "who is currently working",
            "who's working",
            "whos working",
            "who is at work",
            "who is currently at work",
            "who is working now",
            "who is currently working now",
        }

    @staticmethod
    def _is_current_off_work_question(
        text: str,
    ) -> bool:

        return text in {
            "who is off work",
            "who is currently off work",
            "who's off work",
            "whos off work",
            "who has stopped working",
            "who is done for today",
            "who is done with work",
            "who finished work",
            "who has finished work",
            "who is not working",
            "who is currently not working",
        }

    # ======================================================
    # ANSWER BUILDER
    # ======================================================

    @staticmethod
    def _build_people_answer(
        *,
        events,
        empty_text: str,
        single_suffix: str,
        multiple_prefix: str,
    ) -> Answer:

        if not events:
            return Answer(
                text=empty_text,
            )

        names = [
            event.person_name
            for event in events
        ]

        if len(names) == 1:
            text = (
                f"{names[0]} {single_suffix}"
            )
        else:
            text = (
                multiple_prefix
                + ", ".join(names)
                + "."
            )

        return Answer(
            text=text,
        )
def _format_duration(duration: timedelta) -> str:
    total_seconds = max(0, int(duration.total_seconds()))

    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []

    if hours:
        parts.append(
            f"{hours} hour" if hours == 1 else f"{hours} hours"
        )

    if minutes:
        parts.append(
            f"{minutes} minute"
            if minutes == 1
            else f"{minutes} minutes"
        )

    if not parts:
        return "0 minutes"

    return " ".join(parts)


def _current_work_duration(
    result: AttendanceResult,
    now: datetime,
) -> timedelta:
    if result.work_started_at is None:
        return timedelta(0)

    duration = now - result.work_started_at

    return duration - result.total_break_duration