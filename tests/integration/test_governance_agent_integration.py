"""
Integration tests for GovernanceAgent in POLIS.

Tests end-to-end pipeline dispatch, cognitive engine evidence unification,
API route integration, container wiring, and coexistence with KnowledgeAgent
and OperationsAgent.
"""

import pytest
from fastapi.testclient import TestClient

from domain.common.identifier import Identifier
from domain.operations import (
    OperationalItem,
    OperationalItemType,
    OperationalItemStatus,
    InMemoryOperationalItemRepository,
)
from domain.governance import (
    Policy,
    PolicyScope,
    PolicySeverity,
    PolicyEvaluationStatus,
    ComplianceStatus,
    ApprovalStatus,
    ViolationStatus,
    InMemoryGovernanceRepository,
)
from domain.knowledge import (
    InMemoryKnowledgeRepository,
    KnowledgeRuleRegistry,
    KnowledgeDiscoveryRule,
    RuleBasedKnowledgeBuilder,
    SimpleKnowledgeValidator,
)
from domain.organization import (
    OrganizationEventRuleRegistry,
    RuleBasedOrganizationEventBuilder,
    OperationalOrganizationRule,
    KnowledgeOrganizationRule,
    OrganizationalIntentOrganizationRule,
)
from domain.observation import (
    ObservationRuleRegistry,
    RuleBasedObservationExtractor,
    OperationalObservationRule,
    KnowledgeObservationRule,
    OrganizationalIntentObservationRule,
)
from domain.reasoning import (
    Question,
    Answer,
    QuestionAnsweringService,
)
from engines.knowledge.infrastructure.indexing import NullKnowledgeIndexer
from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import EventSource
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    Content,
    CommunicationIdentity,
)
from application.pipeline.pipeline import PolisPipeline
from application.operations import OperationsAgent, OperationalItemService
from application.knowledge import KnowledgeAgent
from application.governance import GovernanceAgent
from application.cognitive import SimpleCognitiveEngine
from application.services.knowledge_acceptance_service import KnowledgeAcceptanceService
from interfaces.api.app import app
from interfaces.api.dependencies import get_governance_agent


class FakeOperationalUnderstanding:
    def analyze(self, text):
        if "deploy" in text.lower():
            return {
                "is_operational": True,
                "type": "task",
                "summary": "Deploy payment service to staging",
                "confidence": 0.95,
            }
        return {"is_operational": False}


class FakeKnowledgeUnderstanding:
    def analyze(self, text):
        if "policy port" in text.lower():
            return {
                "is_knowledge": True,
                "statement": "Service port policy is 8080",
                "confidence": 0.90,
            }
        return {"is_knowledge": False}


class FakeOrganizationalIntentUnderstanding:
    def analyze(self, text):
        lowered = text.lower()
        if "unauthorized" in lowered or "violation" in lowered:
            return {
                "is_intent": True,
                "type": "policy_violation",
                "summary": "Unauthorized production access detected",
                "confidence": 0.95,
            }
        if "approved" in lowered or "grant" in lowered:
            return {
                "is_intent": True,
                "type": "approval",
                "summary": "Production deployment authorization approved",
                "confidence": 0.95,
            }
        return {"is_intent": False, "type": "none"}


class DummyQuestionAnswering(QuestionAnsweringService):
    def answer(self, question: Question) -> Answer:
        return Answer(text="Default fallback answer")

    def retrieve_evidence(self, question: Question) -> list[str]:
        return ["Org communication evidence"]

    def answer_from_evidence(self, question, evidence, fallback_evidence=None) -> Answer:
        return Answer(text=f"Answered with {len(evidence)} evidence items")


@pytest.fixture
def gov_repo():
    return InMemoryGovernanceRepository(seed_default_policies=True)


@pytest.fixture
def op_repo():
    return InMemoryOperationalItemRepository()


@pytest.fixture
def op_agent(op_repo):
    service = OperationalItemService(op_repo)
    return OperationsAgent(repository=op_repo, operational_item_service=service)


@pytest.fixture
def kn_repo():
    return InMemoryKnowledgeRepository()


@pytest.fixture
def kn_agent(kn_repo):
    return KnowledgeAgent(knowledge_repository=kn_repo)


@pytest.fixture
def gov_agent(gov_repo, op_agent, kn_agent):
    return GovernanceAgent(
        repository=gov_repo,
        operations_agent=op_agent,
        knowledge_agent=kn_agent,
        enabled=True,
    )


@pytest.fixture
def full_pipeline(op_repo, op_agent, kn_repo, kn_agent, gov_repo, gov_agent):
    obs_reg = ObservationRuleRegistry()
    obs_reg.register(OperationalObservationRule(FakeOperationalUnderstanding()))
    obs_reg.register(KnowledgeObservationRule(FakeKnowledgeUnderstanding()))
    obs_reg.register(OrganizationalIntentObservationRule(FakeOrganizationalIntentUnderstanding()))
    obs_extractor = RuleBasedObservationExtractor(obs_reg)

    org_reg = OrganizationEventRuleRegistry()
    org_reg.register(OperationalOrganizationRule())
    org_reg.register(KnowledgeOrganizationRule())
    org_reg.register(OrganizationalIntentOrganizationRule())
    org_builder = RuleBasedOrganizationEventBuilder(org_reg)

    kn_reg = KnowledgeRuleRegistry()
    kn_reg.register(KnowledgeDiscoveryRule())
    kn_builder = RuleBasedKnowledgeBuilder(kn_reg)
    validator = SimpleKnowledgeValidator(kn_repo, NullKnowledgeIndexer())
    acceptance = KnowledgeAcceptanceService(kn_repo)
    reasoning = DummyQuestionAnswering()

    return PolisPipeline(
        communication_service=None,
        observation_extractor=obs_extractor,
        organization_builder=org_builder,
        knowledge_builder=kn_builder,
        knowledge_validator=validator,
        knowledge_acceptance_service=acceptance,
        reasoning_service=reasoning,
        knowledge_agent=kn_agent,
        operations_agent=op_agent,
        governance_agent=gov_agent,
    )


def _create_communication(source_event_id: str, body: str) -> CommunicationEvent:
    return CommunicationEvent.create(
        correlation_id=Identifier(business_id="corr-gov-test"),
        source=EventSource.SLACK,
        source_event_id=source_event_id,
        actor=Actor(
            identity=CommunicationIdentity(internal_id="alice"),
            display_name="Alice",
        ),
        channel=Channel(
            identity=CommunicationIdentity(internal_id="sec-ops"),
            name="sec-ops",
            channel_type="slack",
        ),
        content=Content(body=body),
    )


# -----------------------------------------------------------------------------
# 1. Pipeline Dispatch to GovernanceAgent for POLICY_VIOLATION
# -----------------------------------------------------------------------------

def test_pipeline_dispatches_policy_violation(full_pipeline, gov_repo):
    comm = _create_communication("msg-viol-1", "Security alert: unauthorized access to database.")

    full_pipeline.process(comm)

    findings = gov_repo.list_findings()
    assert len(findings) == 1
    assert "Unauthorized production access" in findings[0].summary
    assert findings[0].compliance_status == ComplianceStatus.NON_COMPLIANT
    assert findings[0].source_event_id == "msg-viol-1"


# -----------------------------------------------------------------------------
# 2. Pipeline Dispatch to GovernanceAgent for APPROVAL_GRANTED
# -----------------------------------------------------------------------------

def test_pipeline_dispatches_approval_granted(full_pipeline, gov_repo):
    comm = _create_communication("msg-appr-1", "The change is approved by security lead.")

    full_pipeline.process(comm)

    pending = gov_repo.list_pending_approvals()
    assert len(pending) == 0  # Should be granted directly, not pending

    approvals = list(gov_repo._approvals.values())
    assert len(approvals) == 1
    assert approvals[0].status == ApprovalStatus.GRANTED
    assert approvals[0].source_event_id == "msg-appr-1"


# -----------------------------------------------------------------------------
# 3. Pipeline Replay Idempotency
# -----------------------------------------------------------------------------

def test_pipeline_governance_replay_is_idempotent(full_pipeline, gov_repo):
    comm = _create_communication("msg-viol-replay", "Security alert: unauthorized access detected.")

    full_pipeline.process(comm)
    full_pipeline.process(comm)

    findings = gov_repo.list_findings()
    assert len(findings) == 1


# -----------------------------------------------------------------------------
# 4. SimpleCognitiveEngine Unified Evidence with GovernanceAgent
# -----------------------------------------------------------------------------

def test_cognitive_engine_unifies_governance_evidence(full_pipeline, gov_agent, gov_repo):
    # Register a finding
    from domain.governance.entities.finding import GovernanceFinding
    finding = GovernanceFinding.create(
        policy_id="SEC-001",
        policy_name="Production Access Control",
        summary="Unauthenticated SSH access on host prod-1",
        severity=PolicySeverity.CRITICAL,
    )
    gov_repo.save_finding(finding)

    qa = DummyQuestionAnswering()
    engine = SimpleCognitiveEngine(
        pipeline=full_pipeline,
        question_answering=qa,
        governance_agent=gov_agent,
    )

    q = Question(text="What compliance violation occurred on SEC-001?")
    answer = engine.ask(q)

    assert answer is not None
    assert "Answered with" in answer.text

    # Direct ask_governance delegation
    gov_answer = engine.ask_governance(q)
    assert gov_answer is not None
    assert gov_answer["question"] == q.text
    assert any("SEC-001" in ev for ev in gov_answer["evidence"])
    assert gov_answer["governance_state"]["open_violations_count"] >= 1


# -----------------------------------------------------------------------------
# 5. API Route Integration (/ask/governance)
# -----------------------------------------------------------------------------

def test_api_ask_governance_endpoint(gov_agent, gov_repo):
    client = TestClient(app)
    app.dependency_overrides[get_governance_agent] = lambda: gov_agent

    try:
        response = client.post(
            "/ask/governance",
            json={"question": "What is our Production Access Control policy?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "Production Access Control" in str(data["evidence"])
        assert "policy_count" in data["governance_state"]
    finally:
        app.dependency_overrides.clear()


# -----------------------------------------------------------------------------
# 6. ApplicationContainer Wiring
# -----------------------------------------------------------------------------

def test_application_container_governance_agent_wiring(gov_agent):
    from application.bootstrap.container import ApplicationContainer
    from unittest.mock import MagicMock

    container = ApplicationContainer(
        engine=MagicMock(),
        knowledge_base_ingestion_service=MagicMock(),
        repository=MagicMock(),
        activity_service=MagicMock(),
        activity_processor=MagicMock(),
        activity_question_service=MagicMock(),
        meeting_transcript_service=MagicMock(),
        meeting_intelligence_service=MagicMock(),
        meeting_transcript_provider=MagicMock(),
        meeting_recording_provider=MagicMock(),
        teams_subscription_repository=MagicMock(),
        teams_subscription_service=MagicMock(),
        teams_recording_subscription_service=MagicMock(),
        reminder_repository=MagicMock(),
        reminder_service=MagicMock(),
        governance_agent=gov_agent,
    )
    assert container.governance_agent is gov_agent


# -----------------------------------------------------------------------------
# 7. Multi-Specialist Coexistence (Knowledge + Operations + Governance)
# -----------------------------------------------------------------------------

def test_multi_specialist_coexistence(full_pipeline, op_repo, kn_repo, gov_repo):
    # A single communication that triggers task, knowledge, and policy violation
    comm = _create_communication(
        "msg-all-specialists",
        "Policy port is 8080. Please deploy payment service. Alert: unauthorized access on host."
    )

    validated = full_pipeline.process(comm)

    # 1. Knowledge processed
    assert len(validated) >= 1

    # 2. Operations processed
    open_tasks = op_repo.find_open(item_type=OperationalItemType.TASK)
    assert len(open_tasks) >= 1

    # 3. Governance processed
    findings = gov_repo.list_findings()
    assert len(findings) >= 1
