# Quick Start Guide

## Prerequisites

- Python 3.10+
- pip or uv for package management

## Initial Setup

### 1. Clone and Setup Environment

```bash
cd polis
cp .env.example .env
```

### 2. Create Virtual Environment

```bash
python -m venv venv

# On Windows
venv\Scripts\activate

# On macOS/Linux
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Verify Installation

```python
# test_setup.py
from infrastructure.config import Settings, Container
from infrastructure.logging import ContextLogger

# Load settings
settings = Settings.from_env_file()
print(f"Environment: {settings.environment}")

# Create container
container = Container(settings)

# Create logger
logger = ContextLogger("test", settings=settings)
logger.info("Setup successful", operation="verify")
```

Run it:
```bash
python test_setup.py
```

Expected output:
```json
{"timestamp": "...", "level": "INFO", "engine": "test", "operation": "verify", "message": "Setup successful"}
```

## Creating Your First Engine

### 1. Create Engine File

```bash
# engines/my_engine/engine.py
```

### 2. Implement Engine

```python
from __future__ import annotations

from infrastructure.config import Container, Engine

class MyEngine(Engine):
    def __init__(self, container: Container) -> None:
        super().__init__("my_engine", container)
    
    def initialize(self) -> None:
        self.logger.info("Initialized", operation="initialize")
    
    def shutdown(self) -> None:
        self.logger.info("Shutdown", operation="shutdown")
    
    def process(self, data: dict[str, str]) -> dict[str, int]:
        self.logger.info("Processing", operation="process")
        return {k: len(v) for k, v in data.items()}
```

### 3. Use Your Engine

```python
from infrastructure.config import Settings, Container
from engines.my_engine.engine import MyEngine

settings = Settings.from_env_file()
container = Container(settings)

engine = MyEngine(container)
engine.initialize()

result = engine.process({"hello": "world"})
print(result)

engine.shutdown()
```

## Running Tests

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest --cov=polis tests/

# Run specific test file
pytest tests/engines/test_event.py

# Run in watch mode
pytest-watch tests/
```

## Code Quality Tools

### Type Checking

```bash
# Check entire project
mypy --strict polis/

# Check specific file
mypy --strict polis/engines/my_engine/engine.py
```

### Code Formatting

```bash
# Format code
black --line-length 100 polis/

# Check formatting without changes
black --check --line-length 100 polis/
```

### Import Sorting

```bash
# Sort imports
isort polis/

# Check imports without changes
isort --check-only polis/
```

### Linting

```bash
# Lint code
pylint polis/

# Lint specific file
pylint polis/engines/my_engine/engine.py
```

### All Checks Combined

```bash
# Run all checks
bash scripts/lint.sh
```

## Common Tasks

### Add a New Configuration Setting

1. Add to `.env.example`:
   ```
   MY_SETTING=default_value
   ```

2. Add to `infrastructure/config/settings.py`:
   ```python
   my_setting: str = Field(default="default_value", env="MY_SETTING")
   ```

3. Use in your code:
   ```python
   value = self.settings.my_setting
   ```

### Create a New Service

1. Create `domain/services/my_service.py`:
   ```python
   from __future__ import annotations
   
   from infrastructure.config import Service, Container
   
   class MyService(Service):
       def __init__(self, container: Container) -> None:
           super().__init__(container)
       
       def do_something(self) -> str:
           return "Done"
   ```

2. Register in DI container:
   ```python
   def create_my_service(c: Container) -> MyService:
       return MyService(c)
   
   container.register("my_service", create_my_service)
   ```

3. Use in engine:
   ```python
   service = self.container.get("my_service")
   result = service.do_something()
   ```

### Debug Logging

Increase log level in `.env`:
```
LOG_LEVEL=DEBUG
```

### Check Configuration

```python
from infrastructure.config import Settings

settings = Settings.from_env_file()
print(settings.to_json())  # Pretty print all settings
```

## Troubleshooting

### Import Errors

If you get import errors, ensure:
1. You're in the virtual environment
2. All `__init__.py` files exist in modules
3. Run `pip install -e .` to install in editable mode

### Missing Dependencies

```bash
pip install -r requirements.txt
```

### Configuration Issues

Check your `.env` file:
```bash
python -c "from infrastructure.config import Settings; print(Settings.from_env_file().to_json())"
```

### Type Checking Failures

```bash
mypy --strict --show-error-codes polis/
```

## Next Steps

1. Read [CODING_STANDARDS.md](./CODING_STANDARDS.md)
2. Read [ARCHITECTURE.md](./ARCHITECTURE.md)
3. Review example engine: `engines/example_engine.py`
4. Create your first engine
5. Run tests and check code quality
