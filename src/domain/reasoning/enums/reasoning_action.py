from enum import Enum


class ReasoningAction(str, Enum):
    """
    Possible outcomes of organizational reasoning.
    """

    IGNORE = "ignore"

    REPLY = "reply"

    ASK_CLARIFICATION = "ask_clarification"

    FLAG_CONTRADICTION = "flag_contradiction"

    CREATE_TASK = "create_task"

    CREATE_DECISION = "create_decision"

    ESCALATE = "escalate"