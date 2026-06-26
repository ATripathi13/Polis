# 🔒 FROZEN RULES - Polis Project

These rules are **NON-NEGOTIABLE** and enforced at multiple levels.
Violations will block commits, fail CI, and be rejected in code review.

---

## RULE #1: No print() Calls EVER ❌

**FORBIDDEN:**
```python
print(...)
sys.stdout.write(...)
sys.stderr.write(...)
```

**REQUIRED:**
```python
logger.info("message", operation="operation_name")
```

### Enforcement

| Layer | Mechanism | Trigger |
|-------|-----------|---------|
| **Pre-commit** | Git hook scans for `print(` | Every commit |
| **CI/CD** | GitHub Actions workflow | All PRs & pushes to main |
| **Code Review** | Manual verification | Every PR |
| **Build** | Pylint static analysis | Local & CI |

### Setup

```bash
bash scripts/setup-hooks.sh
```

---

## RULE #2: Every Log Must Have Required Fields ✅

**ALL logs MUST contain:**

```json
{
  "timestamp": "2026-06-26T10:30:45.123456Z",
  "engine": "component_name",
  "level": "INFO",
  "operation": "what_operation",
  "correlation_id": "trace-unique-id",
  "message": "What happened"
}
```

### Required Fields Explained

| Field | Type | Purpose | Example |
|-------|------|---------|---------|
| **timestamp** | ISO 8601 | When it happened | `2026-06-26T10:30:45.123456Z` |
| **engine** | string | Which component | `"event"`, `"state"`, `"reasoning"` |
| **level** | string | Severity | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| **operation** | string | What operation | `"append"`, `"query"`, `"initialize"` |
| **correlation_id** | string | Trace ID for distributed tracing | `"trace-a1b2c3d4e5f6"` |
| **message** | string | Log message | `"Event processed successfully"` |

### Usage

```python
from infrastructure.logging import ContextLogger

# Create logger with correlation ID
logger = ContextLogger(
    engine="event",
    correlation_id="trace-req-789"  # ← REQUIRED
)

# All required fields automatically included
logger.info("Event appended", operation="append", count=5)
```

Output:
```json
{
  "timestamp": "2026-06-26T10:30:45.123456Z",
  "engine": "event",
  "level": "INFO",
  "operation": "append",
  "correlation_id": "trace-req-789",
  "message": "Event appended",
  "extra": {"count": 5}
}
```

---

## What These Rules Achieve

### Rule #1 (No print()) Ensures

- ✅ All output is captured and queryable
- ✅ All output is structured (JSON)
- ✅ No debug spam in production
- ✅ Consistency across entire codebase
- ✅ Automated monitoring and alerting

### Rule #2 (Required Fields) Enables

- ✅ Distributed tracing via correlation_id
- ✅ Filtering logs by operation
- ✅ Identifying which component produced log
- ✅ Automated log parsing and analysis
- ✅ APM integration (Application Performance Monitoring)
- ✅ Error tracking and debugging

---

## Violation Examples

### ❌ VIOLATIONS (Will be caught)

```python
# Pre-commit hook + GitHub Actions will catch:
print("Processing event")                    # ❌ print()
sys.stdout.write("Done")                     # ❌ stdout
sys.stderr.write("Error")                    # ❌ stderr

# Without correlation_id:
logger.info("Event processed")               # ❌ Missing correlation_id

# Without operation:
logger.info("Something happened")            # ❌ Missing operation
```

### ✅ CORRECT

```python
from infrastructure.logging import ContextLogger

# Create logger with correlation ID
logger = ContextLogger(
    engine="event",
    correlation_id="trace-req-789"
)

# All required fields present
logger.info("Event processed", operation="process")

# Output automatically includes all required fields
# {
#   "timestamp": "...",
#   "engine": "event",
#   "level": "INFO",
#   "operation": "process",
#   "correlation_id": "trace-req-789",
#   "message": "Event processed"
# }
```

---

## Enforcement in Action

### 1. Pre-commit Hook (Blocks Commit)

```bash
$ git commit -m "Add debug print"

🔍 Checking for forbidden print() statements...
❌ VIOLATION: print() calls detected:
   engines/event.py:42:print("Debug")

RULE: No print() calls allowed in Polis.
Use ContextLogger instead.

✗ Commit rejected
```

### 2. GitHub Actions CI (Fails Build)

```
Checking for print() violations...
❌ FAILED: Found 1 violation in engines/event.py:42

CI/CD Pipeline FAILED
PR checks: ❌ FAILED
```

### 3. Code Review

Reviewer comment:
```
❌ Line 42: print() not allowed in Polis
Use: logger.info("message", operation="op_name")
Reference: FROZEN_RULES.md
```

---

## Files Implementing These Rules

| File | Purpose |
|------|---------|
| `infrastructure/logging/logger.py` | Logger implementation with correlation_id |
| `scripts/pre-commit-check-print.sh` | Git hook detecting print() |
| `scripts/setup-hooks.sh` | Install pre-commit hook |
| `.pylintrc` | Linting rules |
| `.github/workflows/logging-standards.yml` | GitHub Actions enforcement |
| `docs/LOG_FORMAT_REQUIREMENTS.md` | Detailed logging requirements |
| `docs/FROZEN_LOGGING_RULES.md` | Implementation guide |
| `docs/CODING_STANDARDS.md` | Development standards |

---

## Setup Instructions

### 1. Install Pre-commit Hook

```bash
# Run once in repo root
bash scripts/setup-hooks.sh

# Now every commit will be checked
git commit -m "your message"
```

### 2. Create Logger Correctly

```python
from infrastructure.logging import ContextLogger
import uuid

# Generate correlation ID (typically at request entry point)
correlation_id = f"trace-{uuid.uuid4().hex[:12]}"

# Create logger
logger = ContextLogger(
    engine="my_component",
    correlation_id=correlation_id
)

# Use it
logger.info("Processing", operation="process")
```

### 3. In Engines

```python
from infrastructure.config import Engine, Container

class MyEngine(Engine):
    def __init__(self, container: Container, correlation_id: str) -> None:
        super().__init__(
            name="my_engine",
            container=container,
            correlation_id=correlation_id
        )
    
    def process(self) -> None:
        # logger and correlation_id already included
        self.logger.info("Processing", operation="process")
```

### 4. Update Existing Code

If migrating existing code:

- [ ] Find all `print()` calls
- [ ] Replace with `logger.info(..., operation="...")`
- [ ] Add `correlation_id` to logger creation
- [ ] Test logs are valid JSON
- [ ] Commit and push

---

## Why These Rules Exist

### Observability
Modern distributed systems need structured, queryable logs.
Unstructured print() statements break observability.

### Debugging
Correlation IDs let you trace a single request through all services.
Without them, debugging distributed systems is nearly impossible.

### Compliance
Many enterprise environments require structured logging for auditing.
JSON logs are automatable and parseable.

### Performance
Logger can batch, buffer, and filter.
print() always goes to stdout immediately.

---

## Questions?

See:
- [CONTAINER.md](docs/CONTAINER.md) - How the application is bootstrapped
- [CODING_STANDARDS.md](docs/CODING_STANDARDS.md) - All development standards
- [LOG_FORMAT_REQUIREMENTS.md](docs/LOG_FORMAT_REQUIREMENTS.md) - Detailed logging requirements
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - System design

---

## Summary

| Aspect | Status |
|--------|--------|
| Rule #1: No print() | 🔒 FROZEN |
| Rule #2: Required log fields | 🔒 FROZEN |
| Pre-commit enforcement | ✅ Active |
| GitHub Actions enforcement | ✅ Active |
| Code review enforcement | ✅ Active |
| Violation blocking | ✅ Enabled |

**These rules are project law. They cannot be bypassed (without explicit override review).**
