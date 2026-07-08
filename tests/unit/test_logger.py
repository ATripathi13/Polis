from infrastructure.logging import (
    configure_logging,
    get_logger,
)


def test_logger_creation() -> None:
    configure_logging()

    logger = get_logger("test")

    assert logger is not None