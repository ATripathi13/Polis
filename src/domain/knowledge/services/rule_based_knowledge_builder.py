"""
Rule-based knowledge builder.
"""

from __future__ import annotations

from domain.organization.value_objects import (
    OrganizationEvent,
)

from domain.knowledge.registry import (
    KnowledgeRuleRegistry,
)

from .knowledge_builder import (
    KnowledgeBuilder,
)

from ..value_objects import (
    KnowledgeCandidate,
)


class RuleBasedKnowledgeBuilder(
    KnowledgeBuilder,
):
    """
    Executes all registered
    knowledge rules.
    """

    def __init__(
        self,
        registry: KnowledgeRuleRegistry,
    ) -> None:

        self._registry = registry

    def build(
        self,
        event: OrganizationEvent,
    ) -> list[KnowledgeCandidate]:

        candidates: list[KnowledgeCandidate] = []

        for rule in self._registry.rules:

            candidates.extend(
                rule.build(event)
            )

        return candidates