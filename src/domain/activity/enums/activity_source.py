from enum import Enum


class ActivitySource(str, Enum):
    SLACK = "slack"
    MANUAL = "manual"
