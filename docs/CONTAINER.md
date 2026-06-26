# Container: Heart of the Application

The `ApplicationContainer` is the central dependency injection hub of Polis. Everything is registered and created here.

**Nobody manually creates services. The container does.**

## Architecture

```
.env
  ↓
Settings (Pydantic configuration)
  ↓
ApplicationContainer
  ↓
┌─────────────────────────────────────┐
│ Logger                              │
│ Database Connection                 │
│ Vector Store (Qdrant)               │
│ Object Store (MinIO)                │
│ Repositories                        │
│ Engines                             │
│ Services                            │
└─────────────────────────────────────┘
```

## Key Features

### 1. Single Source of Truth

All dependencies flow through the container. No scattered initialization code.

```python
# ✅ CORRECT
container = ApplicationContainer.bootstrap()
event_engine = container.get_engine("event")
state_engine = container.get_engine("state")

# ❌ WRONG
event_engine = EventEngine()  # Don't do this
state_engine = StateEngine()  # Don't do this
```

### 2. Configuration → Dependency Injection

Settings from `.env` automatically flow to all components.

```python
# Settings loaded from .env
# No component needs to read environment directly
container = ApplicationContainer()

# All components get settings via DI
settings = container.get_settings()
print(settings.database_url)  # From DATABASE_URL in .env
print(settings.log_level)     # From LOG_LEVEL in .env
```

### 3. Automatic Lifecycle Management

Initialize all engines at startup, shutdown at exit.

```python
container = ApplicationContainer.bootstrap()

# Initialize all engines and services
container.initialize_all()

# Use your application...
event_engine = container.get_engine("event")

# Clean shutdown
container.shutdown_all()
```

### 4. Correlation ID Propagation

Every log includes the application's correlation ID for distributed tracing.

```python
container = ApplicationContainer()
print(container.get_correlation_id())
# Output: app-a1b2c3d4e5f6

# All loggers created from container include this
logger = container.get_logger("my_engine")
# Logs will have: "correlation_id": "app-a1b2c3d4e5f6"
```

## Usage

### Initialize the Container

```python
from infrastructure import ApplicationContainer

# Bootstrap with settings from .env
container = ApplicationContainer.bootstrap()

# Get settings
settings = container.get_settings()

# Get logger
logger = container.get_logger("my_engine")
```

### Register Dependencies

```python
# Register a repository
def create_event_repository(c: ApplicationContainer):
    return EventRepository(c.get_database_connection())

container.register_repository("event", create_event_repository)

# Register an engine
def create_event_engine(c: ApplicationContainer):
    return EventEngine(c)

container.register_engine("event", create_event_engine)
```

### Get Dependencies

```python
# Get a repository
event_repo = container.get_repository("event")

# Get an engine (returns singleton on subsequent calls)
event_engine = container.get_engine("event")
state_engine = container.get_engine("state")
```

### Lifecycle Management

```python
# Initialize all engines (calls initialize() on each)
container.initialize_all()

# Use your application...
event_engine = container.get_engine("event")
result = event_engine.process(data)

# Shutdown all engines (calls shutdown() on each)
container.shutdown_all()
```

## FastAPI Integration

### Application Startup

```python
from fastapi import FastAPI
from infrastructure import ApplicationContainer

app = FastAPI()
container: ApplicationContainer | None = None

@app.on_event("startup")
async def startup():
    global container
    container = ApplicationContainer.bootstrap()
    container.initialize_all()

@app.on_event("shutdown")
async def shutdown():
    if container:
        container.shutdown_all()

@app.get("/events")
async def list_events():
    repo = container.get_repository("event")
    return repo.list_all()
```

### Dependency Injection in Routes

```python
from fastapi import FastAPI, Depends

def get_container() -> ApplicationContainer:
    return container

@app.get("/events")
async def list_events(c: ApplicationContainer = Depends(get_container)):
    repo = c.get_repository("event")
    return repo.list_all()
```

## External Services

The container provides methods to get external service configurations:

```python
# Qdrant (vector store)
qdrant_url = container.get_vector_store_url()
qdrant_key = container.get_vector_store_api_key()

# MinIO (object storage)
minio_endpoint = container.get_minio_endpoint()
minio_creds = container.get_minio_credentials()

# PostgreSQL (relational database)
db_url = container.get_database_url()
db_conn = container.get_database_connection()
```

## Testing

### Create a Test Container

```python
import pytest
from infrastructure import ApplicationContainer
from infrastructure.config import Settings

@pytest.fixture
def container():
    # Create with test settings
    test_settings = Settings(
        environment="test",
        database_url="sqlite:///:memory:",
        debug=True,
    )
    return ApplicationContainer(test_settings)

def test_event_engine(container):
    engine = container.get_engine("event")
    result = engine.process({})
    assert result is not None
```

### Reset for Each Test

```python
@pytest.fixture(autouse=True)
def reset_container(container):
    yield
    # Clear singletons between tests
    container.reset()
```

## Flow Diagram

```
Application Start
        ↓
    .env file
        ↓
Settings.from_env_file()
        ↓
ApplicationContainer.__init__()
        ↓
├─ Load Settings
├─ Setup Logging
├─ Generate Correlation ID
└─ Prepare DI system
        ↓
ApplicationContainer.bootstrap()
        ↓
├─ Register Repositories
├─ Register Engines
├─ Register Services
└─ Log bootstrap complete
        ↓
container.initialize_all()
        ↓
├─ Call engine.initialize() for each engine
└─ Log initialization complete
        ↓
    Application Running
        ↓
container.shutdown_all()
        ↓
├─ Call engine.shutdown() for each engine
└─ Log shutdown complete
        ↓
Application Stop
```

## Rules

1. **Everything through the container** - Don't create services manually
2. **Settings from .env only** - All configuration flows through Settings
3. **Logger from container** - All components use container.get_logger()
4. **Correlation ID propagated** - Passed to all logs for distributed tracing
5. **Initialize before use** - Call container.initialize_all() at startup
6. **Shutdown gracefully** - Call container.shutdown_all() at exit

## Files

- `infrastructure/container.py` - Main ApplicationContainer class
- `infrastructure/config/dependency_injection.py` - Base Container and Engine classes
- `infrastructure/config/settings.py` - Settings loaded from .env
- `infrastructure/logging/logger.py` - ContextLogger for structured logging
