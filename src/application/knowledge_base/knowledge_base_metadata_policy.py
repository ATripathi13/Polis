from __future__ import annotations

from pathlib import Path


class KnowledgeBaseMetadataPolicy:
    """
    Provides deterministic metadata for known POLIS Knowledge Base sources.
    """

    _SOURCE_METADATA: dict[str, dict[str, str]] = {
        "01_nav_thethi_profile.md": {
            "knowledge_type": "leadership_profile",
            "scope": "organization",
            "authority": "current_leadership_profile",
            "source_type": "internal",
        },
        "02_tnt4_company (2).md": {
            "knowledge_type": "organization",
            "scope": "organization",
            "authority": "current_company_profile",
            "source_type": "internal",
        },
        "03_maturity_code_ai_strategy_governance_merged.md": {
            "knowledge_type": "framework",
            "scope": "organization",
            "authority": "current_framework",
            "source_type": "internal",
        },
        "04 digital_transformation.md": {
            "knowledge_type": "strategy",
            "scope": "organization",
            "authority": "current_strategy",
            "source_type": "internal",
        },
        "10 media_content.md": {
            "knowledge_type": "published_content",
            "scope": "organization",
            "authority": "published_source",
            "source_type": "external",
        },
        "12 smaf_5x5_with_piller.md.txt": {
            "knowledge_type": "framework",
            "scope": "organization",
            "authority": "current_framework",
            "source_type": "internal",
        },
        "5 chatbot_behavior_nav_voice.md": {
            "knowledge_type": "polis_behavior",
            "scope": "polis",
            "authority": "current_behavior_policy",
            "source_type": "internal",
        },
        "6 decision_engine.md": {
            "knowledge_type": "reasoning_framework",
            "scope": "polis",
            "authority": "current_reasoning_policy",
            "source_type": "internal",
        },
        "8 website.md": {
            "knowledge_type": "published_content",
            "scope": "organization",
            "authority": "published_source",
            "source_type": "external",
        },
        "9 podcasts.md": {
            "knowledge_type": "published_content",
            "scope": "organization",
            "authority": "published_source",
            "source_type": "external",
        },
    }

    @classmethod
    def classify(
        cls,
        name: str | Path,
    ) -> dict[str, str]:
        """
        Return metadata for a known Knowledge Base source.

        Unknown sources intentionally return an empty dictionary.
        """
        filename = Path(name).name.lower()

        metadata = cls._SOURCE_METADATA.get(filename)

        if metadata is None:
            return {}

        return dict(metadata)
