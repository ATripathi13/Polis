# Polis Development Standards

## Python Files

### Imports
Every Python file must start with:
```python
from __future__ import annotations
```

This enables postponed evaluation of annotations (PEP 563).

### Line Length
Maximum line length: **100 characters**

Use tools like `black` with `--line-length 100` to enforce this.

### Type Hints
- Every function parameter must have a type hint
- Every function return value must have a type hint
- Every class attribute must have a type hint
- No `Any` type unless absolutely necessary (and must be documented)

Example:
```python
def process_event(event_id: str, org_id: str) -> dict[str, Any]:
    """Process an event."""
    pass
```

### Module Structure
Every Python file must have `__init__.py` in its directory.

Example `__init__.py`:
```python
from __future__ import annotations

from .module import MyClass

__all__ = ["MyClass"]
```

### No Global State
- No module-level mutable variables
- No singletons outside the DI container
- All state must be passed through dependency injection

Bad:
```python
# module.py
_cache = {}  # Global state - NOT ALLOWED

def get_cached(key: str) -> Any:
    return _cache.get(key)
```

Good:
```python
class CacheService:
    def __init__(self, container: Container) -> None:
        self.container = container
        self.cache: dict[str, Any] = {}
    
    def get(self, key: str) -> Any:
        return self.cache.get(key)
```

## Configuration

### Configuration Flow

All configuration follows this chain:
```
.env file
    ↓
Settings() class
    ↓
Dependency Injection Container
    ↓
Engines / Services
```

### No Direct Environment Variable Access

**FORBIDDEN:**
```python
import os
DEBUG = os.getenv("DEBUG", False)  # ❌ NOT ALLOWED
```

**ALLOWED:**
```python
from infrastructure.config import Settings

settings = Settings()  # Loads from .env
debug = settings.debug  # Access through Settings object
```

### Loading Configuration

```python
from infrastructure.config import Settings, Container

# Load settings from .env
settings = Settings.from_env_file()

# Or use defaults and override
settings = Settings(debug=True, api_port=9000)

# Create DI container
container = Container(settings)
```

### Validation

Critical settings should be validated:
```python
settings.validate_critical_settings()  # Validates in production mode
```

## Dependency Injection

### Container Usage

```python
from infrastructure.config import Container, Engine

class EventEngine(Engine):
    def __init__(self, container: Container) -> None:
        super().__init__(
            name="event",
            container=container,
            organization=org_id,
            execution=exec_id,
        )
    
    def initialize(self) -> None:
        # Set up resources
        pass
    
    def shutdown(self) -> None:
        # Clean up resources
        pass
```

### Registering Dependencies

```python
container = Container(settings)

# Register a service factory
def create_event_service(c: Container) -> EventService:
    return EventService(c)

container.register("event_service", create_event_service)

# Use it
service = container.get("event_service")
```

## Logging

### JSON Format Only

Every log must be JSON with structured fields:

```json
{
  "timestamp": "2026-06-26T10:30:45.123456",
  "level": "INFO",
  "engine": "event",
  "operation": "append",
  "organization": "org-123",
  "execution": "exec-456",
  "message": "Event appended successfully",
  "extra": {}
}
```

### Using the Logger

```python
from infrastructure.logging import ContextLogger

logger = ContextLogger(
    engine="event",
    organization="org-123",
    execution="exec-456",
)

# Log with operation context
logger.info("Event appended", operation="append")

# Log with additional context
logger.error("Failed to append", operation="append", error_code="E001")
```

### Logger in Engines

```python
class EventEngine(Engine):
    def process(self) -> None:
        self.logger.info(
            "Processing event",
            operation="process",
            event_count=100,
        )
```

### No Print Statements
Never use `print()`. Always use the logger:

Bad:
```python
print("Event processed")  # ❌ NOT ALLOWED
```

Good:
```python
self.logger.info("Event processed", operation="process")
```

## Class Design

### Typed Classes

Every class must be fully typed:

```python
class EventStore:
    def __init__(
        self,
        database_url: str,
        max_retries: int = 3,
    ) -> None:
        self.database_url = database_url
        self.max_retries = max_retries
    
    def append(self, event_id: str, data: dict[str, Any]) -> None:
        """Append event to store."""
        pass
    
    def get(self, event_id: str) -> dict[str, Any] | None:
        """Retrieve event from store."""
        return None
```

### Docstrings

Use Google-style docstrings:

```python
def process_event(
    event: Event,
    context: ExecutionContext,
) -> ProcessResult:
    """Process an event in the given context.
    
    Args:
        event: The event to process.
        context: The execution context.
    
    Returns:
        The processing result.
    
    Raises:
        ProcessingError: If processing fails.
    """
    pass
```

## Code Organization

### Module Exports
Use `__all__` to define public API:

```python
# good_module.py
from __future__ import annotations

from .impl import MyClass, MyService

__all__ = ["MyClass", "MyService"]
```

### Imports Order
1. Future imports
2. Standard library
3. Third-party
4. Local imports

```python
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseSettings

from infrastructure.config import Settings
from domain.entities import Event
```

## Testing
- All tests must follow the same standards
- Use pytest
- Tests should be in `tests/` directory
- Mirror the source structure

## Static Analysis

Run these tools to enforce standards:

```bash
# Type checking
mypy --strict polis/

# Code formatting (max line length 100)
black --line-length 100 polis/

# Linting
pylint polis/

# Import sorting
isort polis/
```

## Summary Checklist

- [ ] File starts with `from __future__ import annotations`
- [ ] All functions/methods have parameter and return type hints
- [ ] No `Any` types without documentation
- [ ] No global mutable state
- [ ] All configuration via `.env` → `Settings()` → `Container`
- [ ] No direct `os.getenv()` calls
- [ ] All logs are JSON via `ContextLogger`
- [ ] No `print()` statements
- [ ] Max line length 100 characters
- [ ] Every module has `__init__.py`
- [ ] Classes are fully typed
- [ ] Comprehensive docstrings
