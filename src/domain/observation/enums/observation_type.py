from enum import Enum


class ObservationType(str, Enum):
    """
    Types of organizational observations.
    """

    UNKNOWN = "unknown"

    QUESTION = "question"

    KNOWLEDGE = "knowledge"

    TASK = "task"

    DECISION = "decision"

    APPROVAL = "approval"

    RISK = "risk"

    CONTRADICTION = "contradiction"

    ALERT = "alert"

    SUMMARY_REQUEST = "summary_request"