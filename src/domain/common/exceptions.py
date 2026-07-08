"""
Domain exceptions for Polis.

The domain layer defines business-level exceptions only.
Infrastructure-specific exceptions belong outside the domain.
"""


class DomainError(Exception):
    """Base class for all domain exceptions."""


class EntityValidationError(DomainError):
    """Raised when an entity violates a business rule."""


class DomainRuleViolation(DomainError):
    """Raised when a domain invariant is violated."""


class EntityNotFound(DomainError):
    """Raised when an entity cannot be found."""


class InvalidStateTransition(DomainError):
    """Raised when an entity attempts an invalid state transition."""