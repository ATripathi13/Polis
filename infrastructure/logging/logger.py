from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from typing import Any

from infrastructure.config.settings import Settings


class JSONFormatter(logging.Formatter):
    """Format logs as JSON with structured fields.
    
    REQUIRED fields in every log:
    - timestamp: ISO 8601 format
    - engine: Which engine/component produced the log
    - level: DEBUG, INFO, WARNING, ERROR, CRITICAL
    - operation: What operation was performed
    - correlation_id: Request/execution correlation ID (unique trace ID)
    - message: Log message
    
    OPTIONAL fields:
    - organization: Organization context
    - execution: Execution/request ID
    - exception: Exception traceback (if error)
    - extra: Any additional context
    
    RULE: No print() calls allowed in Polis. All output goes through Logger.
    RULE: Every log must have correlation_id for distributed tracing.
    """

    def __init__(
        self,
        engine: str = "core",
        organization: str | None = None,
        execution: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Initialize JSON formatter.
        
        Args:
            engine: Name of the engine/component
            organization: Organization context
            execution: Execution/request ID
            correlation_id: Correlation/trace ID (required for all logs)
        """
        super().__init__()
        self.engine = engine
        self.organization = organization
        self.execution = execution
        self.correlation_id = correlation_id or "unknown"

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.
        
        All logs must contain: timestamp, engine, level, operation,
        correlation_id, and message.
        
        Args:
            record: The log record to format.
            
        Returns:
            JSON string with required and optional fields.
        """
        # REQUIRED fields (enforced)
        log_data: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": self.engine,
            "level": record.levelname,
            "operation": getattr(record, "operation", "unknown"),
            "correlation_id": getattr(
                record,
                "correlation_id",
                self.correlation_id,
            ),
            "message": record.getMessage(),
        }

        # OPTIONAL fields
        if self.organization:
            log_data["organization"] = self.organization

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
                "correlation_id",
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
    correlation_id: str | None = None,
) -> logging.Logger:
    """Configure JSON logging for the application.
    
    Args:
        settings: Application settings
        engine: Name of the engine/component
        organization: Organization context
        execution: Execution/request ID
        correlation_id: Correlation ID for request tracing
        
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
        correlation_id=correlation_id,
    )

    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def create_logger(
    engine: str,
    settings: Settings | None = None,
    organization: str | None = None,
    execution: str | None = None,
    correlation_id: str | None = None,
) -> logging.Logger:
    """Create or get a logger for a specific engine.
    
    Args:
        engine: Name of the engine/component
        settings: Application settings (optional, uses default if not provided)
        organization: Organization context
        execution: Execution/request ID
        correlation_id: Correlation ID for request tracing
        
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
            correlation_id=correlation_id,
        )

    return logger


class ContextLogger:
    """Logger with embedded context (engine, organization, execution, correlation_id).
    
    RULE: No print() calls allowed in Polis. Use ContextLogger instead.
    RULE: Every log must have correlation_id for distributed tracing.
    
    Example:
        logger = ContextLogger(
            "event",
            organization="org-123",
            execution="exec-456",
            correlation_id="trace-789"
        )
        logger.info("Event appended", operation="append")
    """

    def __init__(
        self,
        engine: str,
        settings: Settings | None = None,
        organization: str | None = None,
        execution: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Initialize context logger.
        
        Args:
            engine: Name of the engine/component
            settings: Application settings
            organization: Organization context
            execution: Execution/request ID
            correlation_id: Correlation ID for distributed tracing
        """
        self.engine = engine
        self.organization = organization
        self.execution = execution
        self.correlation_id = correlation_id or "unknown"
        self.logger = create_logger(
            engine,
            settings=settings,
            organization=organization,
            execution=execution,
            correlation_id=self.correlation_id,
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
        
        Ensures all logs have required fields:
        timestamp, engine, level, operation, correlation_id, message.
        
        Args:
            level: Log level (debug, info, warning, error, critical)
            message: Log message text
            operation: Operation name (required)
            extra: Additional context fields
        """
        log_extra = extra.copy()
        if operation:
            log_extra["operation"] = operation
        
        # Ensure correlation_id is always present in logs
        log_extra["correlation_id"] = self.correlation_id

        getattr(self.logger, level)(message, extra=log_extra)
