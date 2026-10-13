# POLIS — Operations Agent Specialist Architecture

## 1. Executive Summary

The **Operations Agent** (`OperationsAgent`) is a dedicated specialist capability in POLIS responsible for interpreting organizational operational intelligence, managing operational lifecycles (`TASK`, `DECISION`, `RISK`), enforcing strict domain state invariants, maintaining deterministic idempotency and provenance, and coordinating with the `ReminderService`.

In accordance with POLIS architectural principles:
- **POLIS is the single visible face/interface of the system.**
- **Specialist agents are bounded internal components behind POLIS.**
- **POLIS / orchestration routes events and requests to specialists.**
- **The Operations Agent does NOT replace or parallelize existing operational storage**; it builds directly upon the existing `OperationalItem` domain model, PostgreSQL / in-memory repositories, and `OperationalItemService`.

---

## 2. Architectural Position

```text
                    ┌──────────────────────────────┐
                    │            POLIS             │
                    │       Orchestrator / UI      │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ Organizational Event Engine  │
                    │   (OrganizationEvent stream) │
                    └──────────────┬───────────────┘
                                   │
             ┌─────────────────────┼─────────────────────┐
             │                     │                     │
             ▼                     ▼                     ▼
      Knowledge Agent       Operations Agent       Meeting Agent
             │                     │
             ▼                     ▼
       Knowledge Core      Operational Domain
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
                  TASK          DECISION         RISK
                    │              │              │
                    └──────────────┼──────────────┘
                                   ▼
                            Reminder Service
                              (when needed)
```

---

## 3. Event Inputs and Operational Mapping

The Operations Agent deterministic event dispatcher handles the following organizational event types:

| Event Type | Operation | Behavior |
|------------|-----------|----------|
| `TASK_CREATED` | `created` / `no_op` | Creates or upserts a `TASK` operational item. Idempotent on replay. Preserves assignee, priority, deadline, evidence, and correlation. |
| `TASK_UPDATED` | `updated` / `no_op` | Resolves existing task via `item_id`, `source_event_id`, or `correlation_id`. Updates summary, status, owner, priority, due date, and appends new evidence. |
| `TASK_COMPLETED` | `completed` / `no_op` | Transitions referenced task to `COMPLETED`. Validates lifecycle transition. Replay is idempotent. |
| `DECISION_MADE` | `created` / `no_op` | Represents architectural/organizational decisions. Can mark decisions as `OPEN` or `ACCEPTED` based on approval, or supersede older decisions via metadata. |
| `RISK_IDENTIFIED` | `created` / `transitioned` / `no_op` | Registers identified risk with severity/priority. Translates lifecycle events (`in_progress`, `mitigated`, `accepted`, `closed`). Avoids duplicate risk records. |
| Non-operational events | `ignored` | Explicitly skipped with structured `ignored` result, avoiding unhandled side-effects. |

---

## 4. Lifecycle State Machines

The Operations Agent enforces explicit transition matrices, rejecting illegal transitions with `InvalidLifecycleTransitionError`:

### 4.1 Task Lifecycle
```text
  ┌──────┐    start / update    ┌─────────────┐
  │ OPEN │ ───────────────────> │ IN_PROGRESS │
  └──────┘                      └──────┬──────┘
     │                                 │
     │ complete                        │ complete
     ▼                                 ▼
┌───────────┐    reopen          ┌───────────┐
│ CANCELLED │ <───────────────── │ COMPLETED │
└───────────┘                    └───────────┘
```
- **Allowed Transitions**:
  - `OPEN` &rarr; `IN_PROGRESS`, `COMPLETED`, `CANCELLED`
  - `IN_PROGRESS` &rarr; `COMPLETED`, `CANCELLED`, `OPEN`
  - `COMPLETED` &rarr; `OPEN` (reopening)
  - `CANCELLED` &rarr; `OPEN` (reopening)

### 4.2 Decision Lifecycle
```text
┌──────┐    approve / accept    ┌──────────┐    supersede    ┌────────────┐
│ OPEN │ ─────────────────────> │ ACCEPTED │ ──────────────> │ SUPERSEDED │
└──────┘                        └──────────┘                 └────────────┘
   │                                 │
   ▼                                 ▼
┌────────┐                      ┌────────┐
│ CLOSED │                      │ CLOSED │
└────────┘                      └────────┘
```
- **Allowed Transitions**:
  - `OPEN` &rarr; `ACCEPTED`, `SUPERSEDED`, `CLOSED`
  - `ACCEPTED` &rarr; `SUPERSEDED`, `CLOSED`
  - `SUPERSEDED` &rarr; `CLOSED`
  - `CLOSED` &rarr; `OPEN`

### 4.3 Risk Lifecycle
```text
┌──────┐    action taken    ┌─────────────┐    mitigate    ┌───────────┐
│ OPEN │ ─────────────────> │ IN_PROGRESS │ ─────────────> │ MITIGATED │
└──────┘                    └─────────────┘                └─────┬─────┘
   │                               │                             │
   │ accept                        │ accept                      │ close
   ▼                               ▼                             ▼
┌──────────┐ ────────────────> ┌────────┐ <──────────────────────┘
│ ACCEPTED │                   │ CLOSED │
└──────────┘                   └────────┘
```
- **Allowed Transitions**:
  - `OPEN` &rarr; `IN_PROGRESS`, `MITIGATED`, `ACCEPTED`, `CLOSED`
  - `IN_PROGRESS` &rarr; `MITIGATED`, `ACCEPTED`, `CLOSED`, `OPEN`
  - `MITIGATED` &rarr; `CLOSED`, `OPEN` (re-emergence)
  - `ACCEPTED` &rarr; `CLOSED`, `OPEN`
  - `CLOSED` &rarr; `OPEN` (reopening)

---

## 5. Idempotency & Provenance Strategy

### 5.1 Deterministic Deduplication
1. **Source Event Match**: `repository.find_by_source_event(source_type, source_event_id, item_type)` prevents duplicate items created from the same message/event.
2. **Correlation ID Match**: `repository.find_by_correlation(correlation_id, item_type)` links related updates across events (e.g. `TASK_CREATED` &rarr; `TASK_UPDATED` &rarr; `TASK_COMPLETED`) to the identical operational record.
3. **Explicit Item ID Hint**: Event observation metadata specifying `item_id`, `task_id`, `risk_id`, or `decision_id` is queried directly.
4. **Content Invariance**: If an incoming event carries identical status, summary, and priority to the existing record, an idempotent `no_op` result is returned with `idempotent=True`.

### 5.2 Source Traceability & Provenance
Every `OperationalItem` persists:
- `source_event_id` and `source_type` (e.g. Slack ts, Teams message ID, GitHub issue number).
- `metadata["correlation_id"]` for multi-event business workflows.
- `evidence`: Cumulative list of raw evidence snippets and observation markers preserved across all lifecycle updates.
- `occurred_at` / `updated_at`: Timestamps preserving audit trails.

---

## 6. Persistence Authority & Pipeline Integration

### 6.1 Single Persistence Authority
To eliminate duplicate saves between the pipeline, cognitive engine, and specialist agents:
- In `PolisPipeline.process(...)`, if `self._operations_agent is not None`, the event is dispatched exclusively to `self._operations_agent.process_event(...)`.
- `self._operational_item_service` serves as a fallback only when `operations_agent` is unconfigured (guaranteeing 100% backward compatibility).
- Direct database writes occur solely through the injected `OperationalItemRepository` (`PostgreSQLOperationalItemRepository` in production, `InMemoryOperationalItemRepository` in unit testing).

### 6.2 Relationship with Other Subsystems
- **Organizational Event Engine**: Authoritative upstream producer of normalized events.
- **Knowledge Agent**: Operates concurrently on `KNOWLEDGE_DISCOVERED` / `KNOWLEDGE_UPDATED` events without conflating knowledge statements and operational state.
- **Meeting Agent**: Produces meeting intelligence and transcripts, which the Event Engine normalizes into operational events consumed by the Operations Agent.
- **Reminder Service**: Explicitly triggered via `agent.schedule_task_reminder(...)` or when events carry explicit reminder triggers, avoiding reminder spam.
- **Cognitive Engine**: Queries `agent.retrieve_evidence(question)` and provides `engine.ask_operations(question)` for direct operational intelligence.

---

## 7. API Surface

The Operations Agent is accessed through the POLIS unified API:
- `POST /ask/operations`: Structured operational queries returning evidence snippets, open task counts, overdue counts, active risks, and open decisions.
- `POST /ask`: Unified question answering combining organizational communications, knowledge base documents, and operational item evidence.
