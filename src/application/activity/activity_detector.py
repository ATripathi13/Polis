from __future__ import annotations

from dataclasses import dataclass

from domain.activity import ActivityType


@dataclass(frozen=True, slots=True)
class DetectedActivity:
    """
    Result of detecting an explicit activity signal.
    """

    activity_type: ActivityType
    break_type: str | None = None
    note: str | None = None


class ActivityDetector:
    """
    Detects explicit work/activity signals from text.
    """

    def detect(
        self,
        text: str,
    ) -> DetectedActivity | None:

        normalized = " ".join(
            text.lower().strip().split()
        )

        if not normalized:
            return None

        # --------------------------------------------------
        # WORK START
        # --------------------------------------------------

        if normalized in {
            "starting work",
            "starting my day",
            "i'm starting work",
            "im starting work",
            "i am starting work",
            "back to work",
            "starting now",
            "beginning work",
        }:
            return DetectedActivity(
                activity_type=ActivityType.WORK_START,
                note=text,
            )

        # --------------------------------------------------
        # WORK END
        # --------------------------------------------------

        if normalized in {
            "done for today",
            "done for the day",
            "finished for today",
            "finished for the day",
            "ending work",
            "signing off",
            "logging off",
        }:
            return DetectedActivity(
                activity_type=ActivityType.WORK_END,
                note=text,
            )

        # --------------------------------------------------
        # BREAK START
        # --------------------------------------------------

        if normalized in {
            "taking a break",
            "going on break",
            "going for lunch",
            "stepping away",
            "be right back",
            "brb",
        }:
            return DetectedActivity(
                activity_type=ActivityType.BREAK_START,
                note=text,
            )

        # --------------------------------------------------
        # BREAK END
        # --------------------------------------------------

        if normalized in {
            "back",
            "i'm back",
            "im back",
            "back from lunch",
            "back from break",
            "returning",
        }:
            return DetectedActivity(
                activity_type=ActivityType.BREAK_END,
                note=text,
            )

        return None