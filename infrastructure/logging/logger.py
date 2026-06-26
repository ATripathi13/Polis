from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from typing import Any

from infrastructure.config.settings import Settings


class JSONFormatter(logging.Formatter):
    """Format logs as JSON with structured fields.
    
    Every log includes:
    - timestamp: ISO 8601 format
    - level: DEBUG, INFO, WARNING, ERROR, CRITICAL
    - engine: Which engine/component produced the log
    - operation: What operation was performed
    - organization: Organization context (if available)
    - execution: Execution/request ID (if available)
    - message: Log message
    - extra: Any additional context
    """

    def __init__(
        self,
        engine: str = "core",
        organization: str | None = None,
        execution: str | None = None,
    ) -> None:
        """Initialize JSON formatter.
        
        Args:
            engine: Name of the engine/component
            organization: Organization context
            execution: Execution/request ID
        """
        super().__init__()
        self.engine = engine
        self.organization = organization
        self.execution = execution

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.
        
        Args:
            record: The log record to format.
            
        Returns:
            JSON string with structured log data.
        """
        log_data: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "engine": self.engine,
            "message": record.getMessage(),
        }

        # Add operation if available in extra
        if hasattr(record, "operation"):
            log_data["operation"] = record.operation

        # Add organization if available
        if self.organization:
            log_data["organization"] = self.organization

        # Add execution/request ID if available
        if self.execution:
            log_data["execution"] = self.execution

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add any extra fields from the record
        extra_fields = {
            k: v
            for k, v in record.__dict__.items()
            if k
            not in {
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "stack_info",
                "operation",
                "organization",
                "execution",
            }
        }

        if extra_fields:
            log_data["extra"] = extra_fields

        return json.dumps(log_data, default=str)


def setup_logging(
    settings: Settings,
    engine: str = "core",
    organization: str | None = None,
    execution: str | None = None,
) -> logging.Logger:
    """Configure JSON logging for the application.
    
    Args:
        settings: Application settings
        engine: Name of the engine/component
        organization: Organization context
        execution: Execution/request ID
        
    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(engine)
    logger.setLevel(getattr(logging, settings.log_level.upper()))

    # Remove existing handlers
    logger.handlers.clear()

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, settings.log_level.upper()))

    # Create JSON formatter
    formatter = JSONFormatter(
        engine=engine,
        organization=organization,
        execution=execution,
    )

    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def create_logger(
    engine: str,
    settings: Settings | None = None,
    organization: str | None = None,
    execution: str | None = None,
) -> logging.Logger:
    """Create or get a logger for a specific engine.
    
    Args:
        engine: Name of the engine/component
        settings: Application settings (optional, uses default if not provided)
        organization: Organization context
        execution: Execution/request ID
        
    Returns:
        Configured logger instance.
    """
    if settings is None:
        settings = Settings()

    logger = logging.getLogger(engine)

    if not logger.handlers:
        setup_logging(
            settings,
            engine=engine,
            organization=organization,
            execution=execution,
        )

    return logger


class ContextLogger:
    """Logger with embedded context (engine, organization, execution).
    
    Example:
        logger = ContextLogger("event", organization="org-123",
                              execution="exec-456")
        logger.info("Event appended", operation="append")
    """

    def __init__(
        self,
        engine: str,
        settings: Settings | None = None,
        organization: str | None = None,
        execution: str | None = None,
    ) -> None:
        """Initialize context logger.
        
        Args:
            engine: Name of the engine/component
            settings: Application settings
            organization: Organization context
            execution: Execution/request ID
        """
        self.engine = engine
        self.organization = organization
        self.execution = execution
        self.logger = create_logger(
            engine,
            settings=settings,
            organization=organization,
            execution=execution,
        )

    def debug(self, message: str, operation: str | None = None,
              **kwargs: Any) -> None:
        """Log debug message.
        
        Args:
            message: Log message
            operation: Operation name
            **kwargs: Additional context
        """
        self._log("debug", message, operation, kwargs)

    def info(self, message: str, operation: str | None = None,
             **kwargs: Any) -> None:
        """Log info message.
        
        Args:
            message: Log message
            operation: Operation name
            **kwargs: Additional context
        """
        self._log("info", message, operation, kwargs)

    def warning(self, message: str, operation: str | None = None,
                **kwargs: Any) -> None:
        """Log warning message.
        
        Args:
            message: Log message
            operation: Operation name
            **kwargs: Additional context
        """
        self._log("warning", message, operation, kwargs)

    def error(self, message: str, operation: str | None = None,
              **kwargs: Any) -> None:
        """Log error message.
        
        Args:
            message: Log message
            operation: Operation name
            **kwargs: Additional context
        """
        self._log("error", message, operation, kwargs)

    def critical(self, message: str, operation: str | None = None,
                 **kwargs: Any) -> None:
        """Log critical message.
        
        Args:
            message: Log message
            operation: Operation name
            **kwargs: Additional context
        """
        self._log("critical", message, operation, kwargs)

    def _log(self, level: str, message: str, operation: str | None,
             extra: dict[str, Any]) -> None:
        """Internal logging method.
        
        Args:
            level: Log level
            message: Log message
            operation: Operation name
            extra: Additional context
        """
        log_extra = extra.copy()
        if operation:
            log_extra["operation"] = operation

        getattr(self.logger, level)(message, extra=log_extra)
