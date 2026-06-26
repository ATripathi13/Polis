# Polis

Autonomous agent platform with modular engines and strict coding standards.

## Quick Start

### Using Docker (Recommended)

```bash
# Start all services (PostgreSQL, Qdrant, MinIO)
# Windows:
.\docker.ps1 up

# macOS/Linux:
./docker.sh up

# Check service status
.\docker.ps1 status

# View logs
.\docker.ps1 logs

# Stop services
.\docker.ps1 down
```

### Manual Setup (Local Development)

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Run infrastructure services (requires Docker)
docker compose -f deployment/docker/docker-compose.yml up -d

# Run application
python -m uvicorn apps.api.main:app --reload
```

## Services

The system runs four core services:

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL | 5432 | Primary relational database |
| Qdrant | 6333 | Vector database for embeddings |
| MinIO API | 9000 | Object storage (S3 compatible) |
| MinIO Console | 9001 | MinIO web UI |

Access services:
- **PostgreSQL**: `psql -U polis -h localhost -d polis` (password: `polis_dev_password`)
- **Qdrant**: http://localhost:6333
- **MinIO Console**: http://localhost:9001 (user: `minioadmin`, password: `minioadmin_dev_password`)

See [deployment/docker/README.md](./deployment/docker/README.md) for detailed Docker documentation.

## Project Structure

```
polis/
├── apps/              # Application entry points (API, worker, scheduler, web)
├── engines/           # Core processing engines (event, reasoning, knowledge, etc.)
├── domain/            # Domain-driven design (entities, services, repositories)
├── infrastructure/    # Cross-cutting concerns (config, logging, database, auth)
├── sdk/               # Client SDKs
├── deployment/        # Docker and deployment configs
│   └── docker/        # Docker Compose configuration
├── docs/              # Documentation
├── tests/             # Test suites
├── scripts/           # Utility scripts
└── tools/             # Development tools
```

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) for complete architecture overview.

## Coding Standards

Every Python file must follow strict standards:

```python
from __future__ import annotations  # ← Mandatory

def process(event: Event) -> dict[str, Any]:
    """Process an event and return result.
    
    Args:
        event: The event to process.
    
    Returns:
        Processing result dictionary.
    """
    pass
```

**Key Rules:**
- Max line length: 100 characters
- Full type hints required (no `Any` unless necessary)
- No global state - use dependency injection
- All configuration via `.env` → `Settings()` → `Container`
- All logs are JSON format
- No direct environment variable access

Complete guide: [docs/CODING_STANDARDS.md](./docs/CODING_STANDARDS.md)

## Configuration

All configuration flows through a single path:

```
.env file
    ↓
Settings() class
    ↓
Dependency Injection Container
    ↓
Engines & Services
```

1. Copy environment template: `cp .env.example .env`
2. Edit `.env` as needed
3. Settings are loaded and validated on startup
4. Access via `self.settings.your_setting` in code

See [docs/CODING_STANDARDS.md](./docs/CODING_STANDARDS.md#configuration) for configuration details.

## Getting Started

### 1. Set Up Environment

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # macOS/Linux
# or
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
```

### 2. Start Services

```bash
# Using Docker (recommended)
# Windows:
.\docker.ps1 up

# macOS/Linux:
./docker.sh up

# Or manually:
docker compose -f deployment/docker/docker-compose.yml up -d
```

### 3. Verify Setup

```bash
# Check all services are running
.\docker.ps1 status    # Windows
./docker.sh status     # macOS/Linux

# Test services
.\docker.ps1 postgres-health    # Windows
./docker.sh postgres-health     # macOS/Linux
```

### 4. Create Your First Engine

See [docs/QUICKSTART.md](./docs/QUICKSTART.md#creating-your-first-engine) for a tutorial.

## Development Tools

### Code Quality

```bash
# Type checking
mypy --strict polis/

# Code formatting (100 char line length)
black --line-length 100 polis/

# Import sorting
isort polis/

# Linting
pylint polis/
```

### Testing

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest --cov=polis tests/

# Watch mode
pytest-watch tests/
```

### Docker Commands

```bash
# Windows:
.\docker.ps1 up              # Start services
.\docker.ps1 down            # Stop services
.\docker.ps1 logs            # View logs
.\docker.ps1 psql            # Access PostgreSQL
.\docker.ps1 clean           # Remove everything

# macOS/Linux:
./docker.sh up               # Start services
./docker.sh down             # Stop services
./docker.sh logs             # View logs
./docker.sh psql             # Access PostgreSQL
./docker.sh clean            # Remove everything
```

## Documentation

- **[QUICKSTART.md](./docs/QUICKSTART.md)** - Setup and getting started
- **[CODING_STANDARDS.md](./docs/CODING_STANDARDS.md)** - Coding rules and patterns
- **[ARCHITECTURE.md](./docs/ARCHITECTURE.md)** - System design
- **[deployment/docker/README.md](./deployment/docker/README.md)** - Docker guide
- **[IMPLEMENTATION_SUMMARY.md](./docs/IMPLEMENTATION_SUMMARY.md)** - What's been set up

## Architecture Highlights

### Dependency Injection
All dependencies are managed through a central `Container`:

```python
from infrastructure.config import Container, Settings

settings = Settings.from_env_file()
container = Container(settings)

# Engine receives container, not individual dependencies
engine = MyEngine(container)
```

### Logging
Every log is JSON with structured fields:

```json
{
  "timestamp": "2026-06-26T10:30:45.123456",
  "level": "INFO",
  "engine": "event",
  "operation": "append",
  "organization": "org-123",
  "execution": "exec-456",
  "message": "Event appended successfully"
}
```

### Engine Pattern
All engines follow the same pattern:

```python
from infrastructure.config import Engine, Container

class MyEngine(Engine):
    def __init__(self, container: Container) -> None:
        super().__init__("my_engine", container)
    
    def initialize(self) -> None:
        """Set up engine resources."""
        pass
    
    def shutdown(self) -> None:
        """Clean up resources."""
        pass
```

## Key Design Decisions

1. **No Global State** - Everything via dependency injection
2. **Configuration First** - All settings from environment
3. **Type Safety** - Strict type hints throughout
4. **Structured Logging** - JSON format for machine parsing
5. **Domain-Driven Design** - Clear separation of concerns
6. **Modular Engines** - Independent, composable services

## Production Checklist

Before deploying to production:

- [ ] Change all default passwords in `.env`
- [ ] Set `ENVIRONMENT=production` and `DEBUG=false`
- [ ] Update `JWT_SECRET` to a strong random value
- [ ] Configure production database
- [ ] Set up proper backup strategy
- [ ] Review security considerations
- [ ] Enable proper monitoring and logging
- [ ] Set resource limits for containers
- [ ] Implement secrets management

## Troubleshooting

### Docker Services Won't Start

```bash
# Check Docker is running
docker ps

# View service logs
.\docker.ps1 logs    # Windows
./docker.sh logs     # macOS/Linux

# Restart services
.\docker.ps1 restart
./docker.sh restart
```

### Import Errors

Ensure you're in the virtual environment and all `__init__.py` files exist.

### Connection Issues

Services use internal Docker network names (`postgres`, `qdrant`, `minio`). 
When accessing from the host, use `localhost`.

See [deployment/docker/README.md](./deployment/docker/README.md#troubleshooting) for more.

## Contributing

1. Read [docs/CODING_STANDARDS.md](./docs/CODING_STANDARDS.md)
2. Follow the architecture patterns in [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)
3. Run code quality tools before committing
4. Test your changes with pytest
5. Update documentation as needed

## License

[Add your license here]

## Support

- **Documentation**: See `/docs` folder
- **Issues**: [GitHub Issues](https://github.com/yourorg/polis/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourorg/polis/discussions)
