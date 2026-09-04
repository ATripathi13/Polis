from enum import Enum


class ActivityType(str, Enum):
    WORK_START = "work_start"
    WORK_END = "work_end"

    BREAK_START = "break_start"
    BREAK_END = "break_end"
