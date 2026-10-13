# POLIS Knowledge Agent — Technical Specification

## 1. Overview & Purpose

The **Knowledge Agent** is a production-grade specialist capability operating behind POLIS. While the **Knowledge Core** provides low-level ingestion, parsing, chunking, embeddings, PostgreSQL persistence, and Qdrant vector retrieval, the **Knowledge Agent** serves as the intelligence and decision layer for organizational knowledge.

```text
Slack / Meetings / Email / WhatsApp / Documents / Calendar / GitHub
                              ↓
                     Common Observations
                              ↓
                 Organizational Event Engine
                              ↓
        ┌─────────────────────┼─────────────────────┐
        ↓                     ↓                     ↓
 Knowledge Events       Operational Events    Organizational Intent
        ↓                     ↓                     ↓
 Knowledge Agent       Operations Agent       Future Agents
        ↓                     ↓                     ↓
                         POLIS
```

The Knowledge Agent enables POLIS to answer:
1. **What does the organization know?** (Authoritative, structured knowledge records and Knowledge Base document store).
2. **What is the authoritative information?** (Evaluates source authority metadata, e.g., verified policies vs casual chat).
3. **What knowledge was newly discovered?** (Idempotent handling of `KNOWLEDGE_DISCOVERED` events).
4. **What knowledge changed?** (Structured reasoning over `KNOWLEDGE_UPDATED` events preserving historical context).
5. **What existing knowledge conflicts with new information?** (Contradiction detection without blind overwrites).
6. **What knowledge is missing or uncertain?** (Explicit `UNCERTAIN` and `MISSING` statuses preventing hallucinations).
7. **What evidence supports a conclusion?** (Traceable source references, document names, and snippets).
8. **When should knowledge be updated?** (Authority verification ensuring informal updates do not corrupt official policies).
9. **When should conflicting knowledge be escalated?** (Structured contradiction models recommending resolution states).
10. **How should POLIS present the result to the user?** (Clean grounded text for end-users alongside diagnostic intelligence).

---

## 2. Architecture & Data Flow

```text
User Question / Canonical Event
                 ↓
           KnowledgeAgent
                 ↓
    ┌────────────┴────────────┐
    ↓                         ↓
Event Processor          Knowledge Retrieval
(KNOWLEDGE_DISCOVERED,   - KnowledgeBaseRetrievalService (Qdrant semantic search)
 KNOWLEDGE_UPDATED,      - KnowledgeRepository (Postgres/domain records)
 CONTRADICTION_DETECTED,      ↓
 QUESTION_ASKED)         Authority & Evidence Evaluation
    ↓                         ↓
Idempotency & Authority  Contradiction & Gap Detection
Evaluation                    ↓
    ↓                    Grounded Answer Generation
    └────────────┬────────────┘
                 ↓
          KnowledgeResult
    (status, answer, confidence,
     evidence, sources, contradictions,
     knowledge_changes, missing_aspects)
                 ↓
               POLIS
```

---

## 3. Knowledge Statuses & Domain Models

### KnowledgeStatus (`domain.knowledge.enums.KnowledgeStatus`)
- **`KNOWN`**: Factually established knowledge supported by clear evidence.
- **`UPDATED`**: Knowledge successfully superseded with new verified information.
- **`CONFLICTING`**: Mutual contradictions or conflicting claims detected between sources.
- **`UNCERTAIN`**: Preliminary, tentative, or insufficient evidence exists.
- **`MISSING`**: No relevant information found in organizational records.

### KnowledgeResult (`domain.knowledge.value_objects.KnowledgeResult`)
Immutable value object returned by the Knowledge Agent:
- `status`: `KnowledgeStatus`
- `answer`: Natural-language answer or summary
- `confidence`: Calibrated float in `[0.0, 1.0]`
- `evidence`: Contributing textual evidence strings
- `sources`: List of `KnowledgeSourceReference` objects
- `contradictions`: List of `KnowledgeContradiction` objects
- `knowledge_changes`: List of changelog entries (e.g. action, previous, new)
- `missing_aspects`: Specific query gaps identified
- `to_answer()`: Converts to canonical POLIS `Answer(text, confidence, evidence)`

### KnowledgeContradiction (`domain.knowledge.value_objects.KnowledgeContradiction`)
Captures conflicting intelligence:
- `existing_knowledge`: Prior authoritative claim
- `new_knowledge`: Contradictory claim
- `conflict_explanation`: Reason for conflict
- `supporting_evidence`: List of evidence strings
- `authority_info`: Provenance and authority levels
- `recommended_resolution`: `"escalate"` or `"needs_human_review"`

### KnowledgeSourceReference (`domain.knowledge.value_objects.KnowledgeSourceReference`)
Provides evidence provenance:
- `source_type`: `"knowledge_base"`, `"domain_knowledge"`, `"slack"`, `"teams"`
- `document_name`: Source file or subject identifier
- `source_event_id`: Upstream source message ID
- `authority`: Authority tier (e.g., `"current_policy"`, `"verified"`, `"unverified"`)
- `snippet`: Content snippet

---

## 4. Event Integration

The Knowledge Agent integrates directly into `PolisPipeline.process()`:

| OrganizationEventType | Handler | Semantics |
| :--- | :--- | :--- |
| `KNOWLEDGE_DISCOVERED` | `_handle_knowledge_discovered` | Evaluates if knowledge is genuinely new. Idempotent against duplicate messages. Adds to repository. |
| `KNOWLEDGE_UPDATED` | `_handle_knowledge_updated` | Verifies source authority. Prevents lower-authority overwrites of official policies. Records change history. |
| `CONTRADICTION_DETECTED` | `_handle_contradiction_detected` | Produces structured contradiction result without destroying authoritative baseline. |
| `QUESTION_ASKED` | `ask` | Runs grounded knowledge query. |

---

## 5. Application & API Integration

### `SimpleCognitiveEngine`
- Receives `KnowledgeAgent` during bootstrap.
- Unifies evidence from `KnowledgeAgent.retrieve_evidence()` alongside operational and communication evidence.
- Exposes `ask_knowledge()` for direct specialist access.

### API Endpoints
- **`POST /ask`**: Existing grounded question answering endpoint; returns `{"answer": ...}` preserving 100% backward compatibility.
- **`POST /ask/knowledge`**: Specialist Knowledge Agent endpoint; returns `KnowledgeResultResponse` including status, confidence, sources, evidence, contradictions, and missing aspects.

---

## 6. Testing & Quality Assurance

- **Unit Tests**:
  - `tests/unit/domain/knowledge/test_knowledge_agent_models.py`
  - `tests/unit/application/knowledge/test_knowledge_agent.py`
- **Integration Tests**:
  - `tests/integration/test_knowledge_agent_integration.py`
- **Regression Coverage**: Full test suite passes (265 tests).
