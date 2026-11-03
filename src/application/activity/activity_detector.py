from __future__ import annotations

from dataclasses import dataclass
import re

from domain.activity import ActivityType


@dataclass(frozen=True, slots=True)
class DetectedActivity:
    """
    Result of detecting an explicit activity signal.
    """

    activity_type: ActivityType
    break_type: str | None = None
    note: str | None = None
    is_greeting: bool = False
    substantive_query: str | None = None

    @property
    def has_substantive_query(self) -> bool:
        return bool(self.substantive_query)


_EXPLICIT_WORK_START_PHRASES: frozenset[str] = frozenset({
    "starting work",
    "starting work now",
    "starting my day",
    "i'm starting work",
    "im starting work",
    "i am starting work",
    "i'm starting my day",
    "im starting my day",
    "i am starting my day",
    "starting now",
    "beginning work",
    "begin work",
    "beginning my work",
    "starting my work",
})

_EXPLICIT_WORK_END_PHRASES: frozenset[str] = frozenset({
    "done for today",
    "done for the day",
    "finished for today",
    "finished for the day",
    "ending work",
    "signing off",
    "signing off for today",
    "signing off for the day",
    "signing off now",
    "logging off",
    "logging off for today",
    "logging off for the day",
    "logging off now",
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
    "stopping now",
    "leaving work",
    "logging out",
    "i'm signing off",
    "im signing off",
    "i am signing off",
    "i'm signing off for today",
    "im signing off for today",
    "i am signing off for today",
    "i'm signing off for the day",
    "im signing off for the day",
    "i am signing off for the day",
    "i'm logging off",
    "im logging off",
    "i am logging off",
    "i'm finished for today",
    "im finished for today",
    "i am finished for today",
    "i'm finished for the day",
    "im finished for the day",
    "i am finished for the day",
    "i'm leaving work",
    "im leaving work",
    "i am leaving work",
    "i'm logging out",
    "im logging out",
    "i am logging out",
})

_BREAK_START_PHRASES: frozenset[str] = frozenset({
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
})

_BREAK_END_PHRASES: frozenset[str] = frozenset({
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
    "back at work",
    "i'm back to work",
    "im back to work",
    "i am back to work",
})

_ORDINARY_FAREWELL_PHRASES: frozenset[str] = frozenset({
    "bye",
    "goodbye",
    "good bye",
    "bye bye",
    "byebye",
    "see ya",
    "see you",
    "see you tomorrow",
    "see ya tomorrow",
    "talk later",
    "talk to you later",
    "see you later",
    "see ya later",
    "bye for now",
    "good night",
    "goodnight",
})

_BOT_MENTION_PREFIX = re.compile(
    r"^(?:<@[a-z0-9_|-]+>|@polis)\s*[,:]?\s*",
    re.IGNORECASE,
)

_ORDINARY_FAREWELL_PREFIX_PATTERN = re.compile(
    r"^(?:(?:<@[a-z0-9_|-]+>|@polis)\s*[,:]?\s*)?"
    r"(?:bye|goodbye|good\s+bye|see\s+ya|see\s+you|talk\s+later|good\s+night|goodnight)"
    r"(?:\s+(?:everyone|everybody|team|all|folks|there|tomorrow|later|for\s+now))?"
    r"(?:[\s,!.?:;—–-]+|$)",
    re.IGNORECASE,
)

_GREETING_PREFIX_PATTERN = re.compile(
    r"^(?:(?:<@[a-z0-9_|-]+>|@polis)\s*[,:]?\s*)?"
    r"(?P<greeting>"
    r"good\s+(?:morning|afternoon|evening|day)|"
    r"morning|"
    r"hello|"
    r"hey|"
    r"hi"
    r")"
    r"(?:[\s,!.?:;—–-]+(?P<audience>team|everyone|everybody|all|folks|there|polis|@polis|<@[a-z0-9_|-]+>|(?:[A-Za-z0-9_.-]+(?=[\s]*[,!.?:;—–-]|$))))?"
    r"(?P<sep>[\s,!.?:;—–-]+|$)",
    re.IGNORECASE,
)


class ActivityDetector:
    """
    Detects explicit work/activity signals from text.
    """

    def detect(
        self,
        text: str,
    ) -> DetectedActivity | None:
        trimmed = text.strip()
        if not trimmed:
            return None

        normalized = " ".join(trimmed.lower().split())
        clean = normalized.strip("!.,?:;—–- ")
        if not clean:
            return None

        clean_candidate = _BOT_MENTION_PREFIX.sub("", clean).strip("!.,?:;—–- ")
        effective_clean = clean_candidate if clean_candidate else clean
        effective_trimmed = _BOT_MENTION_PREFIX.sub("", trimmed).strip()

        # --------------------------------------------------
        # 1. ORDINARY FAREWELLS (MUST REMAIN CONVERSATIONAL ONLY)
        # --------------------------------------------------
        if (
            effective_clean in _ORDINARY_FAREWELL_PHRASES
            or bool(_ORDINARY_FAREWELL_PREFIX_PATTERN.match(trimmed))
            or bool(_ORDINARY_FAREWELL_PREFIX_PATTERN.match(effective_trimmed))
        ):
            return None

        # --------------------------------------------------
        # 2. BREAK END
        # --------------------------------------------------
        if effective_clean in _BREAK_END_PHRASES:
            return DetectedActivity(
                activity_type=ActivityType.BREAK_END,
                note=text,
            )

        # --------------------------------------------------
        # 3. BREAK START
        # --------------------------------------------------
        if effective_clean in _BREAK_START_PHRASES:
            return DetectedActivity(
                activity_type=ActivityType.BREAK_START,
                note=text,
            )

        # --------------------------------------------------
        # 4. EXPLICIT WORK END
        # --------------------------------------------------
        if effective_clean in _EXPLICIT_WORK_END_PHRASES:
            return DetectedActivity(
                activity_type=ActivityType.WORK_END,
                note=text,
            )

        # --------------------------------------------------
        # 5. EXPLICIT WORK START
        # --------------------------------------------------
        if effective_clean in _EXPLICIT_WORK_START_PHRASES:
            return DetectedActivity(
                activity_type=ActivityType.WORK_START,
                note=text,
            )

        # --------------------------------------------------
        # 6. NATURAL GREETINGS & COMPOUND GREETING MESSAGES
        # --------------------------------------------------
        greeting_match = _GREETING_PREFIX_PATTERN.match(trimmed)
        matched_str = trimmed
        if greeting_match is None and effective_trimmed:
            greeting_match = _GREETING_PREFIX_PATTERN.match(effective_trimmed)
            matched_str = effective_trimmed

        if greeting_match is not None:
            raw_remainder = matched_str[greeting_match.end():]
            clean_remainder = raw_remainder.strip(" !.,?:;—–-")
            substantive_query = raw_remainder.strip(" ,—–-") if clean_remainder else None

            return DetectedActivity(
                activity_type=ActivityType.WORK_START,
                note=text,
                is_greeting=True,
                substantive_query=substantive_query,
            )

        return None

    def classify(
        self,
        text: str,
    ) -> DetectedActivity | None:
        """
        Alias for detect(), providing explicit classification helper API.
        """
        return self.detect(text)
