"""
POLIS cognitive execution pipeline.
"""

from __future__ import annotations


class PolisPipeline:

    def __init__(
        self,
        communication_service,
        observation_extractor,
        organization_builder,
        knowledge_builder,
        knowledge_validator,
        reasoning_service,
    ) -> None:

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

        # Step 3
        validated = []

        for event in organization_events:

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

        return validated
