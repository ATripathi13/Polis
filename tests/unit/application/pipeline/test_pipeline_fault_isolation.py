"""
Unit tests for PolisPipeline fault isolation across specialist dispatch boundaries.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from application.pipeline.pipeline import PolisPipeline
from domain.common.identifier import Identifier
from domain.knowledge.enums import KnowledgeStatus
from domain.knowledge.validators import ValidationResult, ValidationStatus
from domain.observation import Observation, ObservationType
from domain.organization import OrganizationEvent, OrganizationEventType
from engines.communication.domain.aggregates import CommunicationEvent
from engines.communication.domain.enums import EventSource
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
)


def _create_communication(
    source_event_id: str = "comm-msg-1",
    body: str = "Test communication body",
) -> CommunicationEvent:
    return CommunicationEvent.create(
        correlation_id=Identifier(business_id="corr-test-pipeline"),
        source=EventSource.SLACK,
        source_event_id=source_event_id,
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id="alice",
                external_ids={"slack": "U12345"},
            ),
            display_name="Alice",
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id="general",
                external_ids={"slack": "C12345"},
            ),
            name="general",
            channel_type="slack",
        ),
        content=Content(body=body),
    )


def _create_org_event(
    event_type: OrganizationEventType = OrganizationEventType.TASK_CREATED,
    summary: str = "Test event summary",
    evidence: str = "comm-msg-1",
) -> OrganizationEvent:
    return OrganizationEvent(
        event_type=event_type,
        summary=summary,
        observations=[
            Observation(
                observation_type=ObservationType.TASK,
                summary=summary,
                confidence=0.9,
                evidence=[evidence],
            )
        ],
        confidence=0.9,
    )


def _setup_pipeline(
    organization_events: list[OrganizationEvent],
    operations_agent=None,
    governance_agent=None,
    knowledge_agent=None,
    operational_item_service=None,
    organization_event_repository=None,
):
    obs_extractor = MagicMock()
    obs_extractor.extract.return_value = []

    org_builder = MagicMock()
    org_builder.build.return_value = organization_events

    knowledge_builder = MagicMock()
    knowledge_candidate = MagicMock()
    knowledge_builder.build.return_value = [knowledge_candidate]

    knowledge_validator = MagicMock()
    validation_res = ValidationResult(
        status=ValidationStatus.ACCEPTED,
        knowledge=knowledge_candidate,
    )
    knowledge_validator.validate.return_value = validation_res

    knowledge_acceptance = MagicMock()

    pipeline = PolisPipeline(
        communication_service=None,
        observation_extractor=obs_extractor,
        organization_builder=org_builder,
        knowledge_builder=knowledge_builder,
        knowledge_validator=knowledge_validator,
        knowledge_acceptance_service=knowledge_acceptance,
        reasoning_service=None,
        operational_item_service=operational_item_service,
        organization_event_repository=organization_event_repository,
        knowledge_agent=knowledge_agent,
        operations_agent=operations_agent,
        governance_agent=governance_agent,
    )

    return pipeline, knowledge_acceptance, validation_res


def test_operations_agent_failure_does_not_block_governance_or_knowledge(caplog):
    """
    1. An operations-agent failure does not prevent independent governance
       or knowledge dispatch from continuing and producing valid results.
    """
    event = _create_org_event()
    operations_agent = MagicMock()
    operations_agent.process_event.side_effect = RuntimeError("Simulated operations error")

    governance_agent = MagicMock()
    knowledge_agent = MagicMock()
    knowledge_agent.process_event.return_value = MagicMock(status=KnowledgeStatus.KNOWN)

    pipeline, acceptance, val_res = _setup_pipeline(
        [event],
        operations_agent=operations_agent,
        governance_agent=governance_agent,
        knowledge_agent=knowledge_agent,
    )

    comm = _create_communication()
    with caplog.at_level(logging.ERROR):
        results = pipeline.process(comm)

    # Operations failed
    operations_agent.process_event.assert_called_once()

    # Governance was still dispatched
    governance_agent.process_event.assert_called_once()

    # Knowledge was still dispatched
    knowledge_agent.process_event.assert_called_once()

    # Knowledge acceptance completed normally
    acceptance.accept.assert_called_once_with(val_res)
    assert len(results) == 1
    assert results[0] == val_res

    # Check error logging
    assert any("Specialist 'operations_agent' failed" in record.getMessage() for record in caplog.records)


def test_failure_on_first_event_does_not_block_subsequent_event():
    """
    2. A failure processing one canonical event does not prevent a subsequent
       independent event from being processed when safe.
    """
    event1 = _create_org_event(
        event_type=OrganizationEventType.TASK_CREATED,
        summary="Event 1",
        evidence="ev-1",
    )
    event2 = _create_org_event(
        event_type=OrganizationEventType.POLICY_VIOLATION,
        summary="Event 2",
        evidence="ev-2",
    )

    operations_agent = MagicMock()
    # Fails on event 1, succeeds on event 2
    def op_side_effect(ev, **kwargs):
        if ev.summary == "Event 1":
            raise RuntimeError("Event 1 processing failure")
        return MagicMock()

    operations_agent.process_event.side_effect = op_side_effect

    governance_agent = MagicMock()
    knowledge_agent = MagicMock()
    knowledge_agent.process_event.return_value = MagicMock(status=KnowledgeStatus.KNOWN)

    pipeline, acceptance, val_res = _setup_pipeline(
        [event1, event2],
        operations_agent=operations_agent,
        governance_agent=governance_agent,
        knowledge_agent=knowledge_agent,
    )

    comm = _create_communication()
    results = pipeline.process(comm)

    # Operations was called for both events
    assert operations_agent.process_event.call_count == 2

    # Governance was called for both events
    assert governance_agent.process_event.call_count == 2

    # Knowledge was called for both events
    assert knowledge_agent.process_event.call_count == 2

    # Knowledge candidates for both events were accepted
    assert acceptance.accept.call_count == 2
    assert len(results) == 2


def test_failed_specialist_is_identified_in_structured_logs(caplog):
    """
    3. The failed specialist is identified in structured logs with event metadata,
       without leaking sensitive communication message content.
    """
    event = _create_org_event(
        event_type=OrganizationEventType.POLICY_VIOLATION,
        summary="Policy check",
        evidence="sec-evidence-99",
    )
    governance_agent = MagicMock()
    governance_agent.process_event.side_effect = ValueError("Governance evaluation failure")

    pipeline, _, _ = _setup_pipeline(
        [event],
        governance_agent=governance_agent,
    )

    sensitive_text = "CLASSIFIED_CREDENTIAL_KEY_xyz987"
    comm = _create_communication(source_event_id="sec-evidence-99", body=sensitive_text)

    with caplog.at_level(logging.ERROR):
        pipeline.process(comm)

    error_records = [
        rec for rec in caplog.records
        if "governance_agent" in rec.getMessage()
    ]
    assert len(error_records) == 1
    rec = error_records[0]

    # Specialist name in message and structured extra
    assert "governance_agent" in rec.getMessage()
    assert getattr(rec, "specialist", None) == "governance_agent"
    assert getattr(rec, "event_type", None) == "policy_violation"
    assert getattr(rec, "source_type", None) == "slack"
    assert getattr(rec, "source_event_id", None) == "sec-evidence-99"

    # Sensitive message body must NOT be logged in the error message
    assert sensitive_text not in rec.getMessage()


def test_successful_specialists_continue_to_produce_normal_results():
    """
    4. Successful specialists continue to produce their normal results
       even when another specialist fails.
    """
    event = _create_org_event()

    operations_agent = MagicMock()
    # Governance fails
    governance_agent = MagicMock()
    governance_agent.process_event.side_effect = RuntimeError("Governance crash")

    knowledge_agent = MagicMock()
    knowledge_agent.process_event.return_value = MagicMock(status=KnowledgeStatus.KNOWN)

    pipeline, acceptance, val_res = _setup_pipeline(
        [event],
        operations_agent=operations_agent,
        governance_agent=governance_agent,
        knowledge_agent=knowledge_agent,
    )

    comm = _create_communication()
    results = pipeline.process(comm)

    # Operations succeeded normally
    operations_agent.process_event.assert_called_once()

    # Knowledge agent succeeded normally
    knowledge_agent.process_event.assert_called_once()

    # Acceptance service received the validated knowledge result
    acceptance.accept.assert_called_once_with(val_res)
    assert results == [val_res]


def test_fatal_persistence_failure_propagates():
    """
    5. Fatal persistence or transaction failures on the event repository
       must propagate appropriately rather than being silently swallowed.
    """
    event = _create_org_event()

    repo = MagicMock()
    repo.save.side_effect = ConnectionError("PostgreSQL connection lost")

    pipeline, acceptance, _ = _setup_pipeline(
        [event],
        organization_event_repository=repo,
    )

    comm = _create_communication()
    with pytest.raises(ConnectionError) as exc_info:
        pipeline.process(comm)

    assert "PostgreSQL connection lost" in str(exc_info.value)
    # Downstream acceptance must not have been reached
    acceptance.accept.assert_not_called()


def test_existing_pipeline_behavior_unchanged_when_no_exceptions():
    """
    6. Existing pipeline behavior remains completely unchanged when no
       exceptions occur across any specialist.
    """
    event = _create_org_event()

    operations_agent = MagicMock()
    governance_agent = MagicMock()
    knowledge_agent = MagicMock()
    knowledge_agent.process_event.return_value = MagicMock(status=KnowledgeStatus.KNOWN)
    repo = MagicMock()

    pipeline, acceptance, val_res = _setup_pipeline(
        [event],
        operations_agent=operations_agent,
        governance_agent=governance_agent,
        knowledge_agent=knowledge_agent,
        organization_event_repository=repo,
    )

    comm = _create_communication()
    results = pipeline.process(comm)

    repo.save.assert_called_once()
    operations_agent.process_event.assert_called_once()
    governance_agent.process_event.assert_called_once()
    knowledge_agent.process_event.assert_called_once()
    acceptance.accept.assert_called_once_with(val_res)
    assert results == [val_res]

def test_one_knowledge_candidate_failure_does_not_block_later_candidates(
    caplog,
):
    event = _create_org_event()
    pipeline, acceptance, _ = _setup_pipeline([event])

    first_candidate = MagicMock(name="first_candidate")
    second_candidate = MagicMock(name="second_candidate")
    pipeline._knowledge_builder.build.return_value = [
        first_candidate,
        second_candidate,
    ]

    first_result = ValidationResult(
        status=ValidationStatus.ACCEPTED,
        knowledge=first_candidate,
    )
    second_result = ValidationResult(
        status=ValidationStatus.ACCEPTED,
        knowledge=second_candidate,
    )

    pipeline._knowledge_validator.validate.side_effect = [
        RuntimeError("First candidate validation failed"),
        second_result,
    ]

    with caplog.at_level(logging.ERROR):
        results = pipeline.process(_create_communication())

    assert pipeline._knowledge_validator.validate.call_count == 2
    acceptance.accept.assert_called_once_with(second_result)
    assert results == [second_result]
    assert any(
        "First candidate validation failed" in record.getMessage()
        or (
            record.exc_info
            and "First candidate validation failed"
            in str(record.exc_info[1])
        )
        for record in caplog.records
    )