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
            "begin work",
            "beginning my work",
            "starting my work",
            "i'm back to work",
            "im back to work",
            "i am back to work",
            "back at work",
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
            "i'm done for today",
            "im done for today",
            "i am done for today",
            "i'm done for the day",
            "im done for the day",
            "i am done for the day",
            "finished work",
            "work is done",
            "done working",
            "stopping work",
            "stop working",
            "leaving work",
            "logging out",
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
            "take a break",
            "going on break",
            "going for a break",
            "going for break",
            "going for lunch",
            "stepping away",
            "stepping out",
            "be right back",
            "brb",
            "on break",
            "on a break",
            "i'm on break",
            "im on break",
            "i am on break",
            "i'm on a break",
            "im on a break",
            "i am on a break",
            "i'm in break",
            "im in break",
            "i am in break",
            "in break",
            "i'm taking a break",
            "im taking a break",
            "i am taking a break",
            "going on a break",
            "i'm going on break",
            "im going on break",
            "i am going on break",
            "i'm going for a break",
            "im going for a break",
            "i am going for a break",
            "taking lunch",
            "going to lunch",
            "on lunch",
            "on lunch break",
            "taking a lunch break",
            "i'm taking lunch",
            "im taking lunch",
            "i am taking lunch",
            "stepping away for a bit",
            "stepping out for a bit",
            "i'm going for break",
            "im going for break",
            "i am going for break",
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
            "i am back",
            "back from lunch",
            "back from break",
            "back from my break",
            "returning",
            "returned",
            "i'm back from lunch",
            "im back from lunch",
            "i am back from lunch",
            "i'm back from break",
            "im back from break",
            "i am back from break",
            "back to work",            
        }:
            return DetectedActivity(
                activity_type=ActivityType.BREAK_END,
                note=text,
            )

        return None