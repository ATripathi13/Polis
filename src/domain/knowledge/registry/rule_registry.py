"""
Registry for knowledge rules.
"""

from __future__ import annotations

from domain.knowledge.rules import (
    KnowledgeCandidateRule,
)


class KnowledgeRuleRegistry:
    """
    Stores knowledge rules
    ordered by priority.
    """

    def __init__(self) -> None:
        self._rules: list[
            KnowledgeCandidateRule
        ] = []

    def register(
        self,
        rule: KnowledgeCandidateRule,
    ) -> None:

        self._rules.append(rule)

        self._rules.sort(
            key=lambda r: r.priority,
        )

    @property
    def rules(
        self,
    ) -> list[KnowledgeCandidateRule]:

        return self._rules