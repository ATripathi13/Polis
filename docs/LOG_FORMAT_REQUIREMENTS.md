# Log Format Requirements

## Rule: No print() Calls

**FROZEN RULE**: Nobody is allowed to call `print(...)` inside Polis.

Everything must go through the Logger.

### Why?

- Structured logging enables machine parsing and analysis
- Correlation IDs enable distributed tracing
- Consistent log format across all services
- Better debugging and monitoring

### Enforcement

This rule is enforced via:
1. **Pre-commit hook** - Scans for `print(` patterns
2. **Pylint rule** - Detects forbidden `print()` statements
3. **Code review** - Manual verification

### Invalid (FORBIDDEN)

```python
print("Processing event")  # ❌ NOT ALLOWED
sys.stdout.write("Done")   # ❌ NOT ALLOWED
```

### Valid (REQUIRED)

```python
from infrastructure.logging import ContextLogger

logger = ContextLogger("event", correlation_id="trace-123")
logger.info("Processing event", operation="append")
```

---

## Log Format Requirements

**FROZEN RULE**: Every log must contain:
1. **timestamp** - ISO 8601 format
2. **engine** - Component that produced the log
3. **level** - DEBUG, INFO, WARNING, ERROR, CRITICAL
4. **operation** - What operation was performed
5. **correlation_id** - Unique trace ID for distributed tracing
6. **message** - The actual log message

### Example Log Output

```json
{
  "timestamp": "2026-06-26T10:30:45.123456",
  "engine": "event",
  "level": "INFO",
  "operation": "append",
  "correlation_id": "trace-req-123-abc",
  "message": "Event appended successfully"
}
```

### Optional Fields

The following fields are optional and added when relevant:
- `organization` - Organization context
- `execution` - Execution/request ID
- `exception` - Exception traceback (if error)
- `extra` - Additional context fields

### Using ContextLogger

```python
from infrastructure.logging import ContextLogger

# Create logger with correlation ID (required for tracing)
logger = ContextLogger(
    engine="event",
    organization="org-123",
    execution="exec-456",
    correlation_id="trace-req-789"  # ← REQUIRED
)

# Log with operation (all required fields will be included)
logger.info("Event appended", operation="append", count=5)

# Output:
# {
#   "timestamp": "2026-06-26T10:30:45.123456",
#   "engine": "event",
#   "level": "INFO",
#   "operation": "append",
#   "correlation_id": "trace-req-789",
#   "organization": "org-123",
#   "execution": "exec-456",
#   "message": "Event appended",
#   "extra": {"count": 5}
# }
```

### In Engines

```python
from infrastructure.config import Engine, Container

class EventEngine(Engine):
    def __init__(self, container: Container, correlation_id: str) -> None:
        super().__init__(
            name="event",
            container=container,
            correlation_id=correlation_id  # ← Pass correlation ID
        )
        # logger already configured with correlation_id

    def append(self, event: Event) -> None:
        # Every log automatically includes all required fields
        self.logger.info(
            "Appending event",
            operation="append",
            event_id=event.id,
        )
```

### Correlation ID

The **correlation_id** is a unique trace ID that should:
- Be generated at the entry point (API request, worker job, etc.)
- Be passed through all service calls
- Enable end-to-end tracing of a single operation
- Be human-readable (e.g., `trace-req-123-abc-xyz`)

Example generation:
```python
import uuid

correlation_id = f"trace-{uuid.uuid4().hex[:12]}"
```

---

## Enforcement

### Pre-commit Hook

A pre-commit hook checks for forbidden patterns:

```bash
# Check for print() calls
grep -r "print(" polis/ --include="*.py" | grep -v "# print"

# Check for forbidden imports
grep -r "from builtins import print" polis/ --include="*.py"
```

### Pylint Rule

Configuration in `.pylintrc`:

```ini
[MESSAGES CONTROL]
disable=print-statement
```

### GitHub Actions / CI

CI pipeline includes:
- Grep scan for `print(` patterns
- Pylint analysis
- Code review gate

---

## Migration Checklist

If modifying existing code:

- [ ] Replace `print()` with `ContextLogger`
- [ ] Add `correlation_id` parameter where needed
- [ ] Use `operation` parameter to describe what's happening
- [ ] Add additional context via kwargs
- [ ] Test that logs are valid JSON
- [ ] Verify correlation IDs are present

---

## Violations

- **First offense**: Code review comment and fix
- **Pattern of violations**: Training on standards
- **Severe violations**: Escalation

---

## Questions?

Refer to:
- [docs/CODING_STANDARDS.md](../CODING_STANDARDS.md) - General standards
- [infrastructure/logging/logger.py](../infrastructure/logging/logger.py) - Logger implementation
- [engines/example_engine.py](../engines/example_engine.py) - Example usage
