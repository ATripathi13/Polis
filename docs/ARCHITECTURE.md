# Polis Architecture Guide

## Overview

Polis is built on a modular, engine-based architecture with strict coding standards and centralized configuration management.

## Configuration Architecture

```
.env (Environment Variables)
  ↓
Settings() (Pydantic BaseSettings)
  ↓
Container (Dependency Injection)
  ↓
Engines & Services
```

### Why This Matters

- **Single Source of Truth**: All configuration comes from `.env`
- **Type Safety**: Settings are validated with Pydantic
- **Testability**: Easy to mock configuration in tests
- **Security**: No scattered environment variable access

## Directory Structure

### `/apps`
Application entry points and servers.

- **api**: REST/GraphQL API server (FastAPI)
- **worker**: Background job processor
- **scheduler**: Task scheduling and cron jobs
- **web**: Frontend server (if applicable)

### `/engines`
Core processing engines for specific domains.

- **observation**: Input observation and perception
- **event**: Event ingestion and processing
- **graph**: Graph database and relationships
- **knowledge**: Knowledge graph and semantic storage
- **state**: State management and persistence
- **governance**: Rules, policies, and governance
- **capability**: Capability management and composition
- **execution**: Execution planning and coordination
- **memory**: Short/long-term memory systems
- **reasoning**: Reasoning and inference engines
- **search**: Search and retrieval systems

### `/domain`
Domain-driven design components.

- **entities**: Core business entities (with IDs and lifecycle)
- **relationships**: Entity relationships and links
- **events**: Domain events and event sourcing
- **value_objects**: Immutable value types
- **repositories**: Data access abstractions
- **services**: Domain services and logic

### `/infrastructure`
Cross-cutting concerns and technical infrastructure.

- **config**: Settings and dependency injection
- **logging**: Structured JSON logging
- **database**: Database connections and migrations
- **vector**: Vector database and embeddings
- **storage**: File storage and object storage
- **auth**: Authentication and authorization
- **messaging**: Event bus and message queues

### `/sdk`
Client SDKs for different languages/platforms.

### `/deployment`
Docker, Kubernetes, and cloud deployment configs.

### `/docs`
Documentation and guides.

### `/tests`
Test suites organized by module.

### `/scripts`
Utility and operational scripts.

### `/tools`
Development tools and utilities.

## Coding Standards Summary

### Every Python File

```python
from __future__ import annotations  # ← MANDATORY
```

### Rules

- **Max line length**: 100 characters
- **Type hints**: Required on all functions and classes
- **No `Any`**: Unless absolutely necessary
- **No global state**: Use dependency injection
- **No direct env access**: Use `Settings()` class
- **JSON logging only**: Use `ContextLogger`
- **Module `__init__.py`**: Required in every directory

See [CODING_STANDARDS.md](./CODING_STANDARDS.md) for complete guide.

## Configuration

### Load Settings

```python
from infrastructure.config import Settings

# Load from .env
settings = Settings.from_env_file()

# Or create directly
settings = Settings(
    debug=True,
    api_port=8000,
)
```

### Create Dependency Container

```python
from infrastructure.config import Container

container = Container(settings)
```

### Access in Services/Engines

```python
from infrastructure.config import Engine

class MyEngine(Engine):
    def __init__(self, container: Container) -> None:
        super().__init__("my_engine", container)
        # Access settings via self.settings
        debug_mode = self.settings.debug
```

## Logging

### Basic Usage

```python
from infrastructure.logging import ContextLogger

logger = ContextLogger(
    engine="event",
    organization="org-123",
    execution="exec-456",
)

logger.info("Event processed", operation="append")
```

### Output Format

```json
{
  "timestamp": "2026-06-26T10:30:45.123456",
  "level": "INFO",
  "engine": "event",
  "operation": "append",
  "organization": "org-123",
  "execution": "exec-456",
  "message": "Event processed"
}
```

## Engine Pattern

Every engine follows this pattern:

```python
from __future__ import annotations

from infrastructure.config import Container, Engine

class MyEngine(Engine):
    def __init__(
        self,
        container: Container,
        organization: str | None = None,
        execution: str | None = None,
    ) -> None:
        super().__init__(
            name="my_engine",
            container=container,
            organization=organization,
            execution=execution,
        )
    
    def initialize(self) -> None:
        """Set up engine resources."""
        self.logger.info("Initializing", operation="initialize")
    
    def shutdown(self) -> None:
        """Clean up engine resources."""
        self.logger.info("Shutting down", operation="shutdown")
```

## Dependency Injection

### Register a Service

```python
def create_event_service(container: Container) -> EventService:
    return EventService(container)

container.register("event_service", create_event_service)
```

### Get a Dependency

```python
service = container.get("event_service")

# Or get as singleton (reused)
service = container.get_singleton("event_service")
```

## Development Workflow

### 1. Setup

```bash
# Copy environment template
cp .env.example .env

# Install dependencies
pip install -r requirements.txt

# Or with dev tools
pip install -r requirements.txt[dev]
```

### 2. Type Checking

```bash
mypy --strict polis/
```

### 3. Code Formatting

```bash
black --line-length 100 polis/
isort polis/
```

### 4. Linting

```bash
pylint polis/
```

### 5. Testing

```bash
pytest tests/
pytest --cov=polis tests/
```

## Key Design Decisions

1. **No Global State**: All state is managed via dependency injection
2. **Configuration First**: Everything configurable via `.env`
3. **Structured Logging**: All logs are JSON for machine parsing
4. **Type Safety**: Strict type hints throughout
5. **Engine Architecture**: Modular, independently deployable
6. **Domain-Driven Design**: Clear separation of domain logic

## Environment Variables

See `.env.example` for all available configuration options.

Critical settings for production:
- `ENVIRONMENT=production`
- `JWT_SECRET`: Must be set (not "dev-secret")
- `DEBUG=false`
- `DATABASE_URL`: Production database
- `VECTOR_STORE_URL`: Production vector store

## Next Steps

1. Read [CODING_STANDARDS.md](./CODING_STANDARDS.md)
2. Review the example engine in `engines/example_engine.py`
3. Check out the infrastructure modules in `infrastructure/`
4. Look at domain layer patterns in `domain/`
