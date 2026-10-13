# Organizational Event Engine Technical Specification

## Overview

The Organizational Event Engine is the shared canonical intelligence layer of POLIS. It bridges upstream observations (perceived from normalized communication across Slack, Microsoft Teams, and Meetings) to downstream intelligence consumers (Knowledge Base, Operations, Reasoning, and Specialist Agents).

```text
Source (Slack, Teams, Meetings)
  ↓
Communication / Source normalization (CommunicationEvent)
  ↓
Observation Engine (Observation)
  ↓
Organizational Event Engine (OrganizationEvent)
  ↓
Knowledge / Operations / Reasoning / Specialist Agents
```

---

## 1. Observation → OrganizationEvent Mapping

Every supported `ObservationType` maps to a canonical `OrganizationEventType`:

| ObservationType | OrganizationEventType | Rule | Priority |
| :--- | :--- | :--- | :--- |
| `QUESTION` | `QUESTION_ASKED` | `QuestionOrganizationRule` | 20 |
| `APPROVAL` | `APPROVAL_GRANTED` | `OrganizationalIntentOrganizationRule` | 30 |
| `CONTRADICTION` | `CONTRADICTION_DETECTED` | `OrganizationalIntentOrganizationRule` | 30 |
| `ALERT` | `POLICY_VIOLATION` | `OrganizationalIntentOrganizationRule` | 30 |
| `SUMMARY_REQUEST` | `SUMMARY_REQUESTED` | `OrganizationalIntentOrganizationRule` | 30 |
| `DECISION` | `DECISION_MADE` | `OperationalOrganizationRule` | 40 |
| `RISK` | `RISK_IDENTIFIED` | `OperationalOrganizationRule` | 40 |
| `TASK` | `TASK_CREATED` / `TASK_UPDATED` / `TASK_COMPLETED` | `OperationalOrganizationRule` | 40 |
| `KNOWLEDGE` | `KNOWLEDGE_DISCOVERED` / `KNOWLEDGE_UPDATED` | `KnowledgeOrganizationRule` | 50 |
| `UNKNOWN` | *Intentionally unmapped* (no event generated) | — | — |

`UNKNOWN` observations produce no events to prevent noise and uncanonical state from polluting the downstream layers.

---

## 2. Event Identity, Provenance, and Correlation

### Event Identity
`OrganizationEvent` is an immutable domain `ValueObject`. It contains:
- `event_type`: Canonical `OrganizationEventType`
- `summary`: Non-empty description of the business event
- `observations`: Contributing `Observation` instances
- `confidence`: Calibrated confidence in `[0.0, 1.0]`
- `correlation_id`: Optional `Identifier` linking the event to its organizational thread or context
- `occurred_at`: Source occurrence timestamp (distinguished from processing/persistence time)

### Provenance
Persistence and storage idempotency rely on canonical source identity:
```text
(source_type, source_event_id, event_type)
```
- `source_type`: Canonical communication source (e.g., `"slack"`, `"microsoft_teams"`).
- `source_event_id`: Canonical event identifier from the source message (e.g., Slack timestamp `ts`, Teams transcript segment ID), with fallback to observation evidence.
- `evidence`: The raw source evidence references are retained inside the observations within the event.

### Correlation
The Event Engine preserves the boundary between:
1. **Source Event Identity** (`source_type`, `source_event_id`): Identifies the specific point of origin (message, turn, segment).
2. **Organizational Correlation Identity** (`correlation_id`): Identifies the overarching conversation thread, channel, or meeting (`Identifier.business_id`).

Multiple distinct organizational events (such as a task and a decision) originating from the same source message share the same source identity and correlation identity while remaining uniquely identifiable by `event_type`.

---

## 3. Lifecycle Semantics

### Task Lifecycle
`OperationalOrganizationRule` classifies `ObservationType.TASK` into:
1. **`TASK_COMPLETED`**:
   - Explicit metadata status/action: `"completed"`, `"complete"`, `"done"`, `"finished"`, `"closed"`, `"resolved"`
   - Textual semantics in summary: `"task completed"`, `"completed the task"`, `"is done"`, `"finished task"`, `"resolved the task"`, etc.
2. **`TASK_UPDATED`**:
   - Explicit metadata status/action: `"in_progress"`, `"updated"`, `"rescheduled"`, `"reassigned"`, etc.
   - Textual semantics in summary: `"task updated"`, `"in progress"`, `"task rescheduled"`, `"deadline changed"`, etc.
3. **`TASK_CREATED`**:
   - Default for newly identified tasks and open work items.

Downstream, `OperationalItemService` updates existing operational items or initializes new items with corresponding statuses (`COMPLETED`, `IN_PROGRESS`, `OPEN`).

### Knowledge Lifecycle
`KnowledgeOrganizationRule` classifies `ObservationType.KNOWLEDGE` into:
1. **`KNOWLEDGE_UPDATED`**:
   - Metadata flags: `is_update=True`, `lifecycle="updated"`
   - Textual semantics: `"updated:"`, `"no longer use"`, `"deprecated"`, `"replaced by"`, `"migrated from"`
2. **`KNOWLEDGE_DISCOVERED`**:
   - Default for newly documented facts, processes, and systems.

---

## 4. Temporal Correctness (Event Time vs. Persistence Time)

The system distinguishes when an organizational event actually happened from when POLIS persisted it:
- **`occurred_at`**: Set on `Observation` and `OrganizationEvent` from the source communication timestamp (`communication.created_at`).
- **`created_at`**: Set on `OrganizationEventModel` by the repository at the moment the record is committed to storage.

---

## 5. Deduplication and Rule Ordering

### Rule Ordering
`OrganizationEventRuleRegistry` maintains execution order sorted deterministically by:
```python
key = lambda r: (r.priority, r.__class__.__name__)
```
Rules execute in priority order:
1. `QuestionOrganizationRule` (priority 20)
2. `OrganizationalIntentOrganizationRule` (priority 30)
3. `OperationalOrganizationRule` (priority 40)
4. `KnowledgeOrganizationRule` (priority 50)

Duplicate registrations of the exact same rule instance are ignored.

### Deduplication
The system enforces dual-layer deduplication:
1. **In-Memory Deduplication (`RuleBasedOrganizationEventBuilder`)**:
   Deduplicates events produced by multiple rules or duplicate observations by checking:
   ```python
   key = (event.event_type, event.summary.strip().lower(), evidence_tuple)
   ```
   Preserves the highest-priority rule's event.
2. **Repository Deduplication (`PostgreSQLOrganizationEventRepository`, `InMemoryOrganizationEventRepository`)**:
   Enforces idempotency on:
   ```text
   (source_type, source_event_id, event_type)
   ```
   Ensuring duplicate submissions of the same source event do not create duplicate database records.
