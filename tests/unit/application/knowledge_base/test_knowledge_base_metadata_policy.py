from application.knowledge_base import KnowledgeBaseMetadataPolicy


def test_classifies_known_framework_source():
    metadata = KnowledgeBaseMetadataPolicy.classify(
        "03_maturity_code_AI_Strategy_Governance_Merged.md"
    )

    assert metadata == {
        "knowledge_type": "framework",
        "scope": "organization",
        "authority": "current_framework",
        "source_type": "internal",
    }


def test_classifies_known_polis_behavior_source():
    metadata = KnowledgeBaseMetadataPolicy.classify(
        "5 Chatbot_Behavior_nav_voice.md"
    )

    assert metadata == {
        "knowledge_type": "polis_behavior",
        "scope": "polis",
        "authority": "current_behavior_policy",
        "source_type": "internal",
    }


def test_classification_is_case_insensitive():
    metadata = KnowledgeBaseMetadataPolicy.classify(
        "03_MATURITY_CODE_AI_STRATEGY_GOVERNANCE_MERGED.MD"
    )

    assert metadata["knowledge_type"] == "framework"


def test_unknown_source_returns_empty_metadata():
    metadata = KnowledgeBaseMetadataPolicy.classify(
        "unknown-document.md"
    )

    assert metadata == {}


def test_returns_independent_metadata_copy():
    first = KnowledgeBaseMetadataPolicy.classify(
        "03_maturity_code_AI_Strategy_Governance_Merged.md"
    )
    first["knowledge_type"] = "changed"

    second = KnowledgeBaseMetadataPolicy.classify(
        "03_maturity_code_AI_Strategy_Governance_Merged.md"
    )

    assert second["knowledge_type"] == "framework"
