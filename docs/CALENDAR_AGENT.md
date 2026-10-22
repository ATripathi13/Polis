# POLIS — Calendar Agent Specialist Architecture

## 1. Executive Summary

The **Calendar Agent** (`CalendarAgent`) is a dedicated specialist capability in POLIS responsible for scheduling and managing organizational activities, holidays, and announcements, selecting and resolving intended audiences (`individual`, `team`, `organization`), and reliably delivering automated Slack reminders **exactly 15 hours before the scheduled start** of each calendar entry.

In accordance with POLIS architectural principles:
- **POLIS is the single visible face/interface of the system.**
- **The Calendar Agent is a bounded specialist capability behind POLIS**, not a separate competing bot or user-facing personality.
- **POLIS intent routing and orchestration routes calendar commands and queries to the Calendar Agent.**
- **Existing personal reminders and the Organizational Event Engine remain intact.**
- **All configuration is centralized and validated**, with zero hardcoded identities or secrets.
- **Recurrence is explicitly out of scope** in this release to ensure complete reliability within the existing architecture.

---

## 2. Architectural Position

```text
                        ┌──────────────────────────────┐
                        │            POLIS             │
                        │       Orchestrator / UI      │
                        │     (Slack Socket Mode)      │
                        └──────────────┬───────────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    ▼                  ▼                  ▼
             Operations Agent   Governance Agent   Calendar Agent
                    │                  │                  │
                    │                  │                  ▼
                    │                  │           Calendar Service
                    │                  │                  │
                    │                  │         ┌────────┴────────┐
                    │                  │         ▼                 ▼
                    │                  │    PostgreSQL       Calendar Worker
                    │                  │   (Entries &       (Due Reminders)
                    │                  │    Deliveries)            │
                    │                  │                           ▼
                    │                  │                      Slack Client
                    │                  │                     (DMs/Channels)
                    ▼                  ▼
            Operational Core    Policy / Approvals
```

---

## 3. Supported Entry Types & Audience Semantics

### 3.1 Entry Types
The Calendar Agent supports three discrete domain entry types:

| Entry Type | Description |
|------------|-------------|
| `ACTIVITY` | Scheduled meetings, workshops, sprints, sessions, or operational tasks. |
| `HOLIDAY` | Public, organizational, team, or personal holidays and office closures. |
| `ANNOUNCEMENT` | Dated notices with a scheduled publication or effective start time. |

Every entry requires:
- `title`: Explicit non-empty summary.
- `creator_id`: Authenticated Slack user ID of the creator.
- `start_time`: Timezone-aware timestamp.
- `end_time`: Optional timezone-aware timestamp (must satisfy `end_time >= start_time`).
- `timezone`: Canonical IANA timezone string (e.g., `Asia/Kolkata`, `UTC`).
- `audience_type`: Scope of visibility and notifications (`individual`, `team`, `organization`).
- `audience_id`: Stable identifier of the target audience.
- `version`: Monotonically increasing revision counter for rescheduling.

### 3.2 Audience Model
The audience model supports three distinct scopes:

1. **`individual`**: Targets a specific person. Validated dynamically against the Slack workspace directory via `AudienceResolutionService` / `SlackIdentityService`. Reminders are delivered via Slack direct message (`dm`).
2. **`team`**: Targets a specific team or group (e.g., `engineering`, `product`). Resolved via the configured membership directory provider into constituent Slack member IDs. Each member receives a dedicated DM reminder.
3. **`organization`**: Targets the whole organization. If `CALENDAR_ORGANIZATION_CHANNEL` is configured, reminders are posted directly to the organization channel; otherwise, delivered via individual DMs to active workspace members.

---

## 4. Reminder Calculation & Exactly-Once Delivery

### 4.1 Exact 15-Hour Offset
For every valid calendar entry:
$$\text{Reminder Due Time} = \text{Scheduled Start Time} - 15\text{ hours}$$

- Represented through the configurable `CALENDAR_REMINDER_OFFSET_HOURS` setting (default: `15`), enforced by `CalendarReminderPolicy`.
- Non-positive offsets are rejected during validation.
- All timestamp calculations are strictly timezone-aware.

### 4.2 Durable Tracking & Idempotency
- Each delivery obligation is persisted in the `calendar_reminder_deliveries` table.
- A deterministic idempotency key is maintained:
  `cal-rem:{entry_id}:{recipient_id}:v{version}`
- The database enforces a `UNIQUE` constraint on `idempotency_key`, preventing duplicate records.

### 4.3 Atomic Claim & Multi-Instance Safety
When multiple background worker instances poll for due reminders (`due_at <= now` and `status = 'pending'`):
- The worker executes an atomic optimistic-locking update:
  ```sql
  UPDATE calendar_reminder_deliveries
  SET status = 'processing', last_attempt_at = :claim_time, attempt_count = attempt_count + 1
  WHERE id = :delivery_id AND status = 'pending';
  ```
- Exactly one worker receives `rowcount == 1` and proceeds with Slack delivery. Other workers receive `rowcount == 0` and safely skip.
- Deliveries transition to `sent` only after Slack API reports success.
- If a delivery fails, it is marked `failed` with the error message and retried up to `CALENDAR_MAX_RETRY_ATTEMPTS`.
- Failure of one recipient never halts delivery to other recipients.

### 4.4 Rescheduling & Cancellation Policy
- **Rescheduling**: Updating an entry's `start_time` increments `version`, cancels prior pending deliveries, and creates new delivery obligations matching the new scheduled time.
- **Cancellation**: Cancelling an entry immediately transitions all associated pending deliveries to `cancelled`, preventing stale reminders from firing.

---

## 5. Conversational Interaction Examples

POLIS accepts natural language calendar requests:

### 5.1 Scheduling
- `@POLIS schedule activity 'Sprint Planning' on 2026-11-20 10:00 for the team dev`
- `@POLIS schedule a holiday 'Diwali' on 2026-11-01 09:00 for the organization`
- `@POLIS create announcement 'Office Relocation' on 2026-11-15 11:00 for @alice`

### 5.2 Conversational Clarification
If required information is missing, POLIS asks conversationally instead of guessing:
- *User:* `@POLIS schedule activity 'Quarterly Review'`
- *POLIS:* `I have the title 'Quarterly Review'. When is this scheduled to take place? Please provide a date and time (e.g., '2026-10-25 14:00').`

### 5.3 Viewing & Querying
- `@POLIS what is on the calendar?`
- `@POLIS what are upcoming holidays?`
- `@POLIS who is the event <id> intended for?`
- `@POLIS reminder status for <id>`

### 5.4 Rescheduling & Cancelling
- `@POLIS reschedule event <id> 2026-11-22 15:00`
- `@POLIS cancel event <id>`

---

## 6. Configuration & Environment Variables

All settings use the central `Settings` class (`src/infrastructure/config/settings.py`):

| Environment Variable | Type | Default | Description |
|----------------------|------|---------|-------------|
| `CALENDAR_REMINDER_OFFSET_HOURS` | int | `15` | Hours prior to start time when reminders are due. |
| `CALENDAR_WORKER_POLL_INTERVAL_SECONDS` | int | `30` | Polling interval for the background reminder worker. |
| `CALENDAR_ORGANIZATION_CHANNEL` | str | `""` | Optional Slack channel ID for organization-wide announcements. |
| `CALENDAR_DEFAULT_TIMEZONE` | str | `Asia/Kolkata` | Default timezone for calendar operations. |
| `CALENDAR_MAX_RETRY_ATTEMPTS` | int | `3` | Maximum retry attempts for transient Slack delivery failures. |

---

## 7. Database Migration

The migration extends current head `a7c4e91d2f60`:
- **Revision ID:** `b4f8c92e1a35`
- **Parent Revision:** `a7c4e91d2f60`
- **File:** `alembic/versions/b4f8c92e1a35_create_calendar_tables.py`
- **Tables created:**
  - `calendar_entries`: Primary entry records with indexes on type, creator, times, audience, status.
  - `calendar_reminder_deliveries`: Delivery tracking with foreign key cascade, unique idempotency key, and status indexes.

To execute migration:
```bash
alembic upgrade head
```

To rollback:
```bash
alembic downgrade -1
```

---

## 8. Required Slack Permissions & Scopes

The Calendar Agent uses the existing Slack Bot token (`SLACK_BOT_TOKEN`) and requires the following standard scopes:
- `chat:write`: Deliver reminder notifications to channels and direct messages.
- `im:write`: Open direct message conversations with individuals.
- `users:read`: Resolve workspace members and display names dynamically.
- `channels:read`: Verify channel identity if an organization channel is configured.

---

## 9. Verification & Test Commands

Run the full calendar test suite:
```bash
# Domain and Application tests
.venv/bin/pytest tests/unit/domain/calendar tests/unit/application/calendar -v

# Regression suite across all specialists
.venv/bin/pytest tests/unit/application/governance tests/unit/application/operations tests/unit/connectors/slack tests/unit/domain/calendar tests/unit/application/calendar -q
```
