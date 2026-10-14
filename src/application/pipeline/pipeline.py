"""
POLIS cognitive execution pipeline.
"""

from __future__ import annotations
from domain.knowledge.enums import KnowledgeStatus
from domain.knowledge.validators import ValidationStatus


class PolisPipeline:

    def __init__(
        self,
        communication_service,
        observation_extractor,
        organization_builder,
        knowledge_builder,
        knowledge_validator,
        knowledge_acceptance_service,   # <-- NEW
        reasoning_service,
        operational_item_service=None,
        organization_event_repository=None,
        knowledge_agent=None,
        operations_agent=None,
        governance_agent=None,
    ):

        self._communication_service = communication_service

        self._observation_extractor = (
            observation_extractor
        )

        self._organization_builder = (
            organization_builder
        )

        self._knowledge_builder = (
            knowledge_builder
        )

        self._knowledge_validator = (
            knowledge_validator
        )

        self._reasoning_service = (
            reasoning_service
        )
        self._knowledge_acceptance_service = knowledge_acceptance_service
        self._operational_item_service = operational_item_service
        self._organization_event_repository = (
            organization_event_repository
        )
        self._knowledge_agent = knowledge_agent
        self._operations_agent = operations_agent
        self._governance_agent = governance_agent

    @property
    def governance_agent(self):
        return self._governance_agent

    @property
    def operations_agent(self):
        return self._operations_agent

    @property
    def knowledge_agent(self):
        return self._knowledge_agent

    def process(
        self,
        communication,
    ):
        """
        Execute the complete cognitive pipeline.
        """

        observations = (
            self._observation_extractor.extract(
                communication,
            )
        )

        organization_events = (
            self._organization_builder.build(
                observations,
            )
        )

        source_type = ""
        if hasattr(communication, "source") and communication.source is not None:
            source_type = (
                communication.source.value
                if hasattr(communication.source, "value")
                else str(communication.source)
            )

        canonical_source_event_id = None
        if hasattr(communication, "source_event_id") and communication.source_event_id:
            canonical_source_event_id = str(communication.source_event_id).strip()

        correlation_id = getattr(communication, "correlation_id", None)

        if self._organization_event_repository is not None:
            for event in organization_events:
                source_event_id = canonical_source_event_id
                if not source_event_id:
                    source_event_id = next(
                        (
                            evidence
                            for observation in event.observations
                            for evidence in observation.evidence
                            if evidence and evidence.strip()
                        ),
                        None,
                    )

                if source_event_id and source_type:
                    self._organization_event_repository.save(
                        event,
                        source_type=source_type,
                        source_event_id=source_event_id,
                        correlation_id=correlation_id,
                    )

        # Step 3
        validated = []

        for event in organization_events:
            source_event_id = canonical_source_event_id
            if not source_event_id:
                source_event_id = next(
                    (
                        evidence
                        for observation in event.observations
                        for evidence in observation.evidence
                        if evidence and evidence.strip()
                    ),
                    "",
                )

            # Operations specialist processing: priority to operations_agent
            if self._operations_agent is not None:
                self._operations_agent.process_event(
                    event,
                    source_type=source_type,
                    source_event_id=source_event_id,
                    correlation_id=correlation_id,
                )
            elif self._operational_item_service is not None:
                self._operational_item_service.process_event(
                    event,
                    source_type=source_type,
                    source_event_id=source_event_id,
                )

            # Governance specialist processing
            if self._governance_agent is not None:
                self._governance_agent.process_event(
                    event,
                    source_type=source_type,
                    source_event_id=source_event_id,
                    correlation_id=correlation_id,
                )

            if self._knowledge_agent is not None:
                knowledge_result = self._knowledge_agent.process_event(
                    event,
                    source_type=source_type,
                    source_event_id=source_event_id,
                    persist=False,
                )
                if (
                    knowledge_result is not None
                    and knowledge_result.status == KnowledgeStatus.CONFLICTING
                ):
                    continue

            candidates = (
                self._knowledge_builder.build(
                    event,
                )
            )
            for candidate in candidates:

                result = (
                    self._knowledge_validator.validate(
                        candidate,
                    )
                )

                validated.append(result)

                if result.status in (
                    ValidationStatus.ACCEPTED,
                    ValidationStatus.UPDATED,
                ):
                    self._knowledge_acceptance_service.accept(result)

        return validated
