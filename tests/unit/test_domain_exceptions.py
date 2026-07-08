from domain.common.exceptions import (
    DomainError,
    EntityValidationError,
)


def test_domain_exception_inheritance() -> None:
    assert issubclass(EntityValidationError, DomainError)