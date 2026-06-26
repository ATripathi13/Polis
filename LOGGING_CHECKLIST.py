"""
COMPLIANCE CHECKLIST - Logging & Frozen Rules

Before you commit code, verify these items:
"""

# ============================================================================
# CHECKLIST: Logging Compliance
# ============================================================================

# ❌ DO NOT DO THIS:
print("Debug message")
sys.stdout.write("Something")
sys.stderr.write("Error")

# ✅ DO THIS INSTEAD:
from infrastructure.logging import ContextLogger

logger = ContextLogger(
    engine="my_component",
    correlation_id="trace-unique-id"  # ← REQUIRED
)

logger.info("Debug message", operation="my_operation")
logger.warning("Something", operation="process")
logger.error("Error", operation="process")


# ============================================================================
# RULE #1: No print() - FROZEN RULE
# ============================================================================

# ❌ FORBIDDEN - Will be caught by pre-commit hook
def process_event(event):
    print(f"Processing {event}")  # ← VIOLATION
    return event

# ✅ CORRECT - Uses logger
def process_event(event):
    logger.info("Processing event", operation="process", event_id=event.id)
    return event


# ============================================================================
# RULE #2: Required Log Fields - FROZEN RULE
# ============================================================================

# Every log MUST have these fields (auto-generated except operation & message):
# {
#   "timestamp": "2026-06-26T10:30:45.123456Z",  ← Auto
#   "engine": "my_component",                     ← From logger creation
#   "level": "INFO",                              ← Determined by method (info/error/etc)
#   "operation": "process",                       ← YOU provide
#   "correlation_id": "trace-abc123",             ← From logger creation
#   "message": "Processing event"                 ← From logger call
# }

# ❌ INCOMPLETE - Missing operation
logger.info("Event processed")

# ✅ COMPLETE - All required fields
logger.info("Event processed", operation="append_event")


# ============================================================================
# ENGINE EXAMPLE - Full Compliance
# ============================================================================

from infrastructure.config import Engine, Container

class EventEngine(Engine):
    def __init__(
        self,
        container: Container,
        correlation_id: str
    ) -> None:
        super().__init__(
            name="event",
            container=container,
            correlation_id=correlation_id  # ← Pass through
        )

    def initialize(self) -> None:
        # self.logger already includes engine, correlation_id
        self.logger.info(
            "EventEngine initializing",
            operation="initialize"
        )

    def process(self, data: dict) -> dict:
        self.logger.info(
            "Processing event data",
            operation="process",
            data_size=len(data)
        )
        # Do work...
        return result

    def shutdown(self) -> None:
        self.logger.info(
            "EventEngine shutting down",
            operation="shutdown"
        )


# ============================================================================
# FASTAPI INTEGRATION - Full Compliance
# ============================================================================

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
    logger = container.get_logger("api")

    logger.info(
        "Listing events",
        operation="list_events",
        repository="event"
    )

    events = repo.list_all()

    logger.info(
        "Events retrieved",
        operation="list_events",
        count=len(events)
    )

    return {"events": events}


# ============================================================================
# PRE-COMMIT COMPLIANCE CHECK
# ============================================================================

# Before you git commit, verify:
# 1. No print(...) calls
# 2. No sys.stdout.write(...) calls
# 3. No sys.stderr.write(...) calls
# 4. All loggers have correlation_id parameter
# 5. All logger calls have operation parameter
# 6. All logs go through ContextLogger or Engine.logger

# Run pre-commit hook:
# $ bash scripts/setup-hooks.sh
# $ git commit -m "your message"
#
# Hook will automatically check:
# - print() calls
# - sys.stdout.write() calls
# - sys.stderr.write() calls
#
# If violations found:
# ❌ Commit rejected - fix violations and try again


# ============================================================================
# QUICK REFERENCE
# ============================================================================

# CREATING A LOGGER:
logger = ContextLogger(
    engine="component_name",
    organization="org-id",        # Optional
    execution="exec-id",          # Optional
    correlation_id="trace-id"     # ← REQUIRED
)

# LOGGING:
logger.debug("msg", operation="op_name")
logger.info("msg", operation="op_name")
logger.warning("msg", operation="op_name")
logger.error("msg", operation="op_name")
logger.critical("msg", operation="op_name")

# IN AN ENGINE:
self.logger.info("msg", operation="op_name")  # Already has engine + correlation_id

# IN FASTAPI:
logger = container.get_logger("my_component")  # Returns logger with correlation_id

# ============================================================================
# FROZEN RULES SUMMARY
# ============================================================================

# RULE #1: No print()
# ├─ Reason: Need structured, queryable logs
# ├─ Enforcement: Pre-commit hook + GitHub Actions
# └─ Alternative: logger.info(..., operation="...")

# RULE #2: Required Log Fields
# ├─ timestamp: Auto-generated (ISO 8601)
# ├─ engine: From logger creation
# ├─ level: From method name (info, error, etc)
# ├─ operation: YOU provide
# ├─ correlation_id: From logger creation
# └─ message: From logger call

# See FROZEN_RULES.md for complete documentation
