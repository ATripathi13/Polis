# POLIS — Governance Agent Specialist Architecture

## 1. Executive Summary

The **Governance Agent** (`GovernanceAgent`) is a dedicated specialist capability in POLIS responsible for interpreting organizational policy, evaluating compliance posture, processing governance events (`POLICY_VIOLATION`, `APPROVAL_GRANTED`), managing authorization lifecycles, maintaining deterministic idempotency and provenance, and coordinating with the `OperationsAgent` for corrective remediation.

In accordance with POLIS architectural principles:
- **POLIS is the single visible face/interface of the system.**
- **Specialist agents are bounded internal capabilities coordinated behind POLIS.**
- **POLIS / orchestration routes events and requests to specialists.**
- **Governance enforcement is deterministic** whenever explicit policy rules exist; LLM guesswork never overrides authoritative governance state.
- **Uncertainty is explicitly represented**; incomplete evidence produces `UNCERTAIN` results rather than unverified violations or false compliance assertions.

---

## 2. Architectural Position

```text
                         ┌──────────────────────────────┐
                         │            POLIS             │
                         │      Orchestrator / UI       │
                         └──────────────┬───────────────┘
                                        │
                                        ▼
                         ┌──────────────────────────────┐
                         │ Organizational Event Engine  │
                         │  (OrganizationEvent stream)  │
                         └──────────────┬───────────────┘
                                        │
              ┌─────────────────────────┼────────────────────────┐
              │                         │                        │
              ▼                         ▼                        ▼
       Knowledge Agent           Operations Agent         Governance Agent
              │                         │                        │
              ▼                         ▼                        ▼
        Knowledge Core          Operational Domain        Policy / Approvals
                                        │                        │
                         ┌──────────────┼──────────────┐         ▼
                         ▼              ▼              ▼    Compliance /
                       TASK          DECISION         RISK   Violations /
                         ▲                                     Approvals
                         │             Remediation Action
                         └───────────────────────────────────────┘
```

The Governance Agent is an event-driven specialist that operates from authoritative organizational events, explicit policy rules, and evidence.

---

## 3. Policy Domain Model

Policies are represented by the `Policy` entity (`src/domain/governance/entities/policy.py`):

- **`policy_id`**: Unique policy identifier (e.g., `SEC-001`, `DEP-001`, `DATA-001`, `FIN-001`).
- **`name`**: Descriptive human-readable policy title.
- **`description`**: Detailed policy specification and regulatory context.
- **`scope`**: Applicability domain (`SECURITY`, `OPERATIONS`, `DATA_PROTECTION`, `FINANCIAL`, `LEGAL`, `GENERAL`).
- **`severity`**: Default violation severity (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
- **`enforcement_mode`**: Enforcement stance (`ADVISORY`, `MANDATORY`, `BLOCKING`).
- **`condition_keywords`**: Explicit triggers and matching tokens for deterministic identification.
- **`authority`**: Governing body or authoritative source specification (e.g., `POLIS Security Council`, `SOC-2`).
- **`requires_approval`**: Boolean flag indicating if actions under this policy demand formal approval.
- **`effective_date`**: Optional timestamp defining when the policy becomes effective; the factory defaults it to the current UTC time.

---

## 4. Event Inputs and Governance Mapping

The Governance Agent deterministic event dispatcher processes the following organizational event types:

| Event Type | Operation | Behavior |
|------------|-----------|----------|
| `POLICY_VIOLATION` | `violation_registered` / `no_op` | Identifies affected policy, registers a `GovernanceFinding`, determines severity, captures source event ID, correlation ID, and evidence. Idempotent on replay. If remediation is needed, coordinates with `OperationsAgent` to file a remediation risk. |
| `APPROVAL_GRANTED` | `approval_granted` / `no_op` | Locates referenced approval request (or upserts directly if pre-authorized), validates lifecycle transition, transitions to `GRANTED`, records approver and granted timestamp. Idempotent on replay. |
| Non-governance events | `ignored` | Explicitly skipped with structured `ignored` result, avoiding unhandled side-effects. |

---

## 5. Lifecycle State Machines

The Governance Agent enforces explicit transition matrices, rejecting illegal transitions with `InvalidApprovalTransitionError` or `InvalidGovernanceTransitionError`:

### 5.1 Approval Lifecycle (`ApprovalStatus`)
```text
  ┌───────────┐    submit     ┌─────────┐    grant     ┌─────────┐
  │ REQUESTED │ ────────────> │ PENDING │ ───────────> │ GRANTED │
  └─────┬─────┘               └────┬────┘              └─────────┘
        │                          │
        │ reject                   │ reject
        ▼                          ▼
  ┌───────────┐              ┌───────────┐
  │ REJECTED  │              │ REJECTED  │
  └───────────┘              └───────────┘
```
- **Allowed Transitions**:
  - `REQUESTED` &rarr; `PENDING`, `GRANTED`, `REJECTED`, `CANCELLED`
  - `PENDING` &rarr; `GRANTED`, `REJECTED`, `CANCELLED`, `EXPIRED`
  - `GRANTED` &rarr; terminal
  - `REJECTED` &rarr; terminal
  - `CANCELLED` &rarr; terminal
  - `EXPIRED` &rarr; terminal

### 5.2 Violation Lifecycle (`ViolationStatus`)
```text
  ┌──────┐    triage    ┌─────────────┐    remediate    ┌──────────────────────┐
  │ OPEN │ ───────────> │ UNDER_REVIEW│ ──────────────> │ REMEDIATION_REQUIRED │
  └──────┘              └──────┬──────┘                 └──────────┬───────────┘
     │                         │                                   │ resolve
     │ close                   │ exempt                            ▼
     ▼                         ▼                            ┌────────────┐
┌──────────┐              ┌──────────┐                      │  RESOLVED  │
│  CLOSED  │              │  EXEMPT  │                      └────────────┘
└──────────┘              └──────────┘
```
- **Allowed Transitions**:
  - `OPEN` &rarr; `UNDER_REVIEW`, `REMEDIATION_REQUIRED`, `RESOLVED`, `CLOSED`, `EXEMPT`
  - `UNDER_REVIEW` &rarr; `REMEDIATION_REQUIRED`, `RESOLVED`, `CLOSED`, `EXEMPT`
  - `REMEDIATION_REQUIRED` &rarr; `RESOLVED`, `CLOSED`
  - `RESOLVED` &rarr; `CLOSED`, `OPEN` (reopen on regression)
  - `CLOSED` &rarr; `OPEN` (reopen)
  - `EXEMPT` &rarr; `CLOSED`, `OPEN`

---

## 6. Compliance and Policy Evaluation States

Evaluation results are strictly separated into typed enums to avoid binary false-equivalences:

- **`PolicyEvaluationStatus`**:
  - `COMPLIANT`: Evidence explicitly confirms full adherence to policy constraints.
  - `VIOLATION`: Explicit violation conditions or authoritative violation events detected.
  - `APPROVAL_REQUIRED`: Action is governed by a policy requiring prior sign-off and approval is not yet granted.
  - `DOES_NOT_APPLY`: Context or targets fall outside policy scope.
  - `UNCERTAIN`: Insufficient evidence to establish compliance or breach.

- **`ComplianceStatus`**:
  - `COMPLIANT`, `NON_COMPLIANT`, `UNDER_REVIEW`, `APPROVAL_REQUIRED`, `APPROVED`, `EXEMPT`, `UNKNOWN`.

---

## 7. Determinism, Evidence, and Uncertainty

Governance decisions are high-impact organizational decisions:
- **Rule Determinism**: Evaluations prioritize explicit keyword rules, structured metadata, and authoritative event semantics.
- **Evidence Preservation**: Every `GovernanceResult` and `GovernanceFinding` retains:
  - `policy_id` and `policy_name`
  - `source_event_id` and `source_type`
  - `correlation_id`
  - `evidence` (list of citation strings)
  - `confidence` (float 0.0 - 1.0)
  - `authority`
- **Structured Uncertainty**: When data is insufficient, `evaluation_status=UNCERTAIN` and `compliance_status=UNKNOWN` are returned with clarifying warnings. "No violation detected" is never conflated with "Compliance confirmed".

---

## 8. Idempotency, Provenance, and Correlation

1. **Replay Idempotency**:
   - `POLICY_VIOLATION` replay: When replayed with matching `source_event_id` or `correlation_id` and summary, returns the existing finding with `idempotent=True` and `operation="no_op"`.
   - `APPROVAL_GRANTED` replay: When an approval is already `GRANTED`, returns the existing record with `idempotent=True` and `operation="no_op"`.
2. **Provenance**:
   - Retains origin source event identifiers, timestamps, and causal chains.
3. **Correlation**:
   - Ties findings, approval requests, and remediation tasks together across specialists using `correlation_id`.

---

## 9. Inter-Specialist Integrations

### 9.1 Operations Agent Integration
- When a `POLICY_VIOLATION` mandates remediation (`remediation_required=True`):
  - Governance Agent emits an operational `RISK_IDENTIFIED` event to the `OperationsAgent`.
  - Operations Agent owns task, risk, and decision persistence.
  - Governance Agent **never** duplicates operational item tables or task tracking.

### 9.2 Knowledge Agent Integration
- Knowledge Base stores authoritative policy manuals and guidelines.
- Governance Agent references policy citations and uses Knowledge Base retrieval for context without confusing descriptive documentation with binding governance state.

### 9.3 Cognitive Engine Integration
- `SimpleCognitiveEngine` queries `GovernanceAgent.retrieve_evidence(question)` during unified POLIS question answering.
- Governance findings and pending approvals are synthesized into unified POLIS answers with full provenance citations.

### 9.4 Pipeline Integration
- `PolisPipeline` dispatches events directly to `governance_agent.process_event(...)` during pipeline execution when `enable_governance_engine` is active.

---

## 10. Configuration and Feature Flags

- **`ENABLE_GOVERNANCE_ENGINE`** (`settings.enable_governance_engine`):
  - Default: `True`.
  - When disabled (`False`), `process_event` returns structured disabled results (`operation="disabled"`), and the agent safely operates in pass-through mode without breaking pipeline execution.

---

## 11. API Surface

POLIS remains the orchestrator. Governance capabilities are exposed through POLIS ask and query endpoints:

- `POST /ask/governance`: Dedicated governance query endpoint returning structured `GovernanceResultResponse` with policy evaluation status, compliance posture, findings, approvals, and evidence citations.
- `POST /ask`: Unified question answering endpoint integrating governance evidence alongside knowledge and operational evidence.

---

## 12. Known Limitations

- Policy rules currently use deterministic keyword and metadata matching with seeded foundational policies.
- Governance policies, approval requests, and findings have PostgreSQL persistence through `PostgreSQLGovernanceRepository`. The in-memory repository remains available for tests and isolated usage.
