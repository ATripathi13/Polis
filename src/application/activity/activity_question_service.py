from __future__ import annotations

from domain.activity import ActivityService
from domain.reasoning import Answer, Question


class ActivityQuestionService:
    """
    Answers questions about currently observed activity.
    """

    def __init__(
        self,
        activity_service: ActivityService,
    ) -> None:
        self._activity_service = activity_service

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