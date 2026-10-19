"""
POLIS cognitive execution pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

from domain.knowledge.enums import KnowledgeStatus
from domain.knowledge.validators import ValidationStatus
from domain.organization.identity import derive_source_event_id

logger = logging.getLogger(__name__)


def _format_correlation_id(correlation_id: Any) -> str | None:
    if correlation_id is None:
        return None
    if hasattr(correlation_id, "business_id") and correlation_id.business_id:
        return str(correlation_id.business_id)
    if hasattr(correlation_id, "graph_id") and correlation_id.graph_id:
        return str(correlation_id.graph_id)
    return str(correlation_id)


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

        correlation_id = getattr(communication, "correlation_id", None)
        corr_id_str = _format_correlation_id(correlation_id)

        if self._organization_event_repository is not None:
            for event in organization_events:
                source_event_id = derive_source_event_id(
                    event,
                    source_type=source_type,
                    correlation_id=correlation_id,
                    communication=communication,
                )

                event_type_name = (
                    event.event_type.value
                    if hasattr(event.event_type, "value")
                    else str(event.event_type)
                )

                if not source_event_id:
                    logger.warning(
                        "Skipping organization event persistence: insufficient identity "
                        "to derive source_event_id for event '%s'",
                        event_type_name,
                        extra={
                            "event": "organization_event_missing_identity",
                            "operation": "persist_event",
                            "event_type": event_type_name,
                            "summary": event.summary[:100],
                            "correlation_id": corr_id_str,
                        },
                    )
                    continue

                if source_type:
                    self._organization_event_repository.save(
                        event,
                        source_type=source_type,
                        source_event_id=source_event_id,
                        correlation_id=correlation_id,
                    )

        # Step 3
        validated = []

        for event in organization_events:
            source_event_id = derive_source_event_id(
                event,
                source_type=source_type,
                correlation_id=correlation_id,
                communication=communication,
            )

            event_type_name = (
                event.event_type.value
                if hasattr(event.event_type, "value")
                else str(event.event_type)
            )

            if not source_event_id:
                logger.warning(
                    "Skipping specialist processing for event '%s': "
                    "insufficient source event identity",
                    event_type_name,
                    extra={
                        "event": "specialist_skipped_missing_identity",
                        "operation": "dispatch_specialists",
                        "event_type": event_type_name,
                        "summary": event.summary[:100],
                        "correlation_id": corr_id_str,
                    },
                )
                continue

            # Operations specialist processing: priority to operations_agent
            if self._operations_agent is not None:
                try:
                    self._operations_agent.process_event(
                        event,
                        source_type=source_type,
                        source_event_id=source_event_id,
                        correlation_id=correlation_id,
                    )
                except Exception:
                    logger.exception(
                        "Specialist 'operations_agent' failed processing event '%s' "
                        "(source_type=%s, source_event_id=%s)",
                        event_type_name,
                        source_type,
                        source_event_id,
                        extra={
                            "specialist": "operations_agent",
                            "event_type": event_type_name,
                            "source_type": source_type,
                            "source_event_id": source_event_id,
                            "correlation_id": corr_id_str,
                        },
                    )
            elif self._operational_item_service is not None:
                try:
                    self._operational_item_service.process_event(
                        event,
                        source_type=source_type,
                        source_event_id=source_event_id,
                    )
                except Exception:
                    logger.exception(
                        "Specialist 'operational_item_service' failed processing event '%s' "
                        "(source_type=%s, source_event_id=%s)",
                        event_type_name,
                        source_type,
                        source_event_id,
                        extra={
                            "specialist": "operational_item_service",
                            "event_type": event_type_name,
                            "source_type": source_type,
                            "source_event_id": source_event_id,
                            "correlation_id": corr_id_str,
                        },
                    )

            # Governance specialist processing
            if self._governance_agent is not None:
                try:
                    self._governance_agent.process_event(
                        event,
                        source_type=source_type,
                        source_event_id=source_event_id,
                        correlation_id=correlation_id,
                    )
                except Exception:
                    logger.exception(
                        "Specialist 'governance_agent' failed processing event '%s' "
                        "(source_type=%s, source_event_id=%s)",
                        event_type_name,
                        source_type,
                        source_event_id,
                        extra={
                            "specialist": "governance_agent",
                            "event_type": event_type_name,
                            "source_type": source_type,
                            "source_event_id": source_event_id,
                            "correlation_id": corr_id_str,
                        },
                    )

            # Knowledge specialist processing
            knowledge_result = None
            if self._knowledge_agent is not None:
                try:
                    knowledge_result = self._knowledge_agent.process_event(
                        event,
                        source_type=source_type,
                        source_event_id=source_event_id,
                        persist=False,
                    )
                except Exception:
                    logger.exception(
                        "Specialist 'knowledge_agent' failed processing event '%s' "
                        "(source_type=%s, source_event_id=%s)",
                        event_type_name,
                        source_type,
                        source_event_id,
                        extra={
                            "specialist": "knowledge_agent",
                            "event_type": event_type_name,
                            "source_type": source_type,
                            "source_event_id": source_event_id,
                            "correlation_id": corr_id_str,
                        },
                    )

            if (
                knowledge_result is not None
                and knowledge_result.status == KnowledgeStatus.CONFLICTING
            ):
                continue

            try:
                candidates = self._knowledge_builder.build(event)
            except Exception:
                logger.exception(
                    "Specialist 'knowledge_builder' failed processing event '%s' "
                    "(source_type=%s, source_event_id=%s)",
                    event_type_name,
                    source_type,
                    source_event_id,
                    extra={
                        "specialist": "knowledge_builder",
                        "event_type": event_type_name,
                        "source_type": source_type,
                        "source_event_id": source_event_id,
                        "correlation_id": corr_id_str,
                    },
                )
                continue

            for candidate in candidates:
                try:
                    result = self._knowledge_validator.validate(candidate)
                    validated.append(result)

                    if result.status in (
                        ValidationStatus.ACCEPTED,
                        ValidationStatus.UPDATED,
                    ):
                        self._knowledge_acceptance_service.accept(result)
                except Exception:
                    logger.exception(
                        "Specialist 'knowledge_candidate' failed processing event '%s' "
                        "(source_type=%s, source_event_id=%s)",
                        event_type_name,
                        source_type,
                        source_event_id,
                        extra={
                            "specialist": "knowledge_candidate",
                            "event_type": event_type_name,
                            "source_type": source_type,
                            "source_event_id": source_event_id,
                            "correlation_id": corr_id_str,
                        },
                    )

        return validated
