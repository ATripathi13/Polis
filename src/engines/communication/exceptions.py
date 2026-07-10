from engines.communication.domain.exceptions import (
    InvalidCommunicationEventError,
)
class CommunicationError(Exception):
    """Base exception for the Communication domain."""


class InvalidCommunicationEventError(CommunicationError):
    """Raised when a CommunicationEvent violates domain invariants."""