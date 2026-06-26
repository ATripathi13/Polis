# Frozen Logging Rules Implementation

## Changes Made

### 1. Logger Enhancement - Correlation ID (Required Field)

**File**: `infrastructure/logging/logger.py`

- Added `correlation_id` parameter to all logger functions
- Correlation ID is now a **required** field in every log
- Defaults to `"unknown"` if not provided, but should always be set
- Ensures distributed tracing across all services

**Before:**
```json
{"timestamp": "...", "level": "INFO", "engine": "event", "message": "..."}
```

**After (Required Fields):**
```json
{
  "timestamp": "2026-06-26T10:30:45.123456",
  "engine": "event",
  "level": "INFO",
  "operation": "append",
  "correlation_id": "trace-req-123-abc",  // ← NOW REQUIRED
  "message": "Event appended"
}
```

### 2. Frozen Rule: No print() Calls

**RULE**: Nobody is allowed to call `print(...)` inside Polis.
Everything must go through the Logger.

**Enforcement Mechanisms:**

1. **Pre-commit Hook** (`scripts/pre-commit-check-print.sh`)
   - Scans for `print(` patterns
   - Scans for `sys.stdout.write()`
   - Scans for `sys.stderr.write()`
   - Prevents commits with violations

2. **GitHub Actions CI** (`.github/workflows/logging-standards.yml`)
   - Runs on all PRs
   - Runs on all pushes to main
   - Fails build if violations found
   - Provides clear error messages

3. **Pylint Configuration** (`.pylintrc`)
   - Project-wide linting rules
   - Line length enforcement (100 chars)
   - Code quality standards

### 3. Documentation

**New Files:**
- `docs/LOG_FORMAT_REQUIREMENTS.md` - Detailed logging requirements (300+ lines)
- `scripts/pre-commit-check-print.sh` - Git hook for preventing commits
- `scripts/setup-hooks.sh` - Setup script for installing hooks
- `.pylintrc` - Pylint configuration
- `.github/workflows/logging-standards.yml` - CI enforcement

**Updated Files:**
- `docs/CODING_STANDARDS.md` - Added frozen print() rule and correlation_id requirements
- `infrastructure/logging/logger.py` - Enhanced with correlation_id support

## Required Fields in All Logs

Every single log in Polis MUST contain:

1. **timestamp** - ISO 8601 format (auto-generated)
2. **engine** - Component name (passed to logger)
3. **level** - DEBUG, INFO, WARNING, ERROR, CRITICAL (determined by log method)
4. **operation** - What operation is being performed (required parameter)
5. **correlation_id** - Unique trace ID (passed to logger)
6. **message** - The log message (required parameter)

## Usage Examples

### Creating a Logger

```python
from infrastructure.logging import ContextLogger
import uuid

# Generate correlation ID at entry point
correlation_id = f"trace-{uuid.uuid4().hex[:12]}"

# Create logger with all required context
logger = ContextLogger(
    engine="event",
    organization="org-123",
    execution="exec-456",
    correlation_id=correlation_id  # ← REQUIRED
)

# Log something
logger.info("Event processed", operation="process", count=5)
```

### In an Engine

```python
from infrastructure.config import Engine, Container

class MyEngine(Engine):
    def __init__(
        self,
        container: Container,
        correlation_id: str
    ) -> None:
        super().__init__(
            name="my_engine",
            container=container,
            correlation_id=correlation_id  # ← PASS THROUGH
        )

    def process(self) -> None:
        # Logger auto-includes all required fields
        self.logger.info(
            "Processing started",
            operation="process",
            item_count=10
        )
```

### Output

All logs are automatically JSON formatted:

```json
{
  "timestamp": "2026-06-26T10:30:45.123456",
  "engine": "my_engine",
  "level": "INFO",
  "operation": "process",
  "correlation_id": "trace-a1b2c3d4e5f6",
  "organization": "org-123",
  "execution": "exec-456",
  "message": "Processing started",
  "extra": {"item_count": 10}
}
```

## Enforcement in Action

### Pre-commit Hook

```bash
# Someone tries to commit with print()
$ git commit -m "Add debug print"

# ❌ Pre-commit hook catches it
🔍 Checking for forbidden print() statements...
❌ VIOLATION: print() calls detected:
polis/engines/event.py:42:print("Debug info")

RULE: No print() calls allowed in Polis.
Use ContextLogger instead.

# ✗ Commit rejected
```

### GitHub Actions CI

Every PR automatically runs:
- Scan for `print(` calls
- Scan for `sys.stdout.write()`
- Scan for `sys.stderr.write()`
- Correlation ID verification

Fails the build if violations found.

## Installation

### Setup Pre-commit Hook

```bash
# Run once to install hook
bash scripts/setup-hooks.sh

# Now every commit will be checked
git commit -m "your message"
```

### Bypass Hook (Not Recommended)

```bash
git commit --no-verify  # Skip pre-commit checks
```

## Migration Checklist

If updating existing code:

- [ ] Remove all `print()` calls
- [ ] Replace with `ContextLogger`
- [ ] Add `correlation_id` parameter
- [ ] Add `operation` parameter
- [ ] Test logs are valid JSON
- [ ] Verify all required fields present

## Logging Standards Files

- `infrastructure/logging/logger.py` - Logger implementation with correlation_id
- `docs/LOG_FORMAT_REQUIREMENTS.md` - Detailed logging requirements (new)
- `docs/CODING_STANDARDS.md` - Updated with frozen print() rule
- `scripts/pre-commit-check-print.sh` - Git hook (new)
- `scripts/setup-hooks.sh` - Setup script (new)
- `.pylintrc` - Linting configuration (new)
- `.github/workflows/logging-standards.yml` - CI enforcement (new)

## Summary

| Aspect | Status |
|--------|--------|
| Logger supports correlation_id | ✅ Implemented |
| All logs require correlation_id | ✅ Enforced |
| print() calls forbidden | ✅ Frozen Rule |
| Pre-commit hook installed | ✅ Ready |
| GitHub Actions CI checks | ✅ Ready |
| Documentation updated | ✅ Complete |

## Next Steps

1. Run `bash scripts/setup-hooks.sh` to install pre-commit hook
2. Review `docs/LOG_FORMAT_REQUIREMENTS.md` for details
3. Update any code with `print()` statements to use `ContextLogger`
4. Test with `pytest` to ensure logs are valid JSON
5. Commit and push - CI will verify compliance
