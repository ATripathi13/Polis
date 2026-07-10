from domain.organization import (
    OrganizationEventType,
)


def test_organization_event_type():

    assert (
        OrganizationEventType.TASK_CREATED.value
        == "task_created"
    )

    assert (
        OrganizationEventType.DECISION_MADE.value
        == "decision_made"
    )

    assert (
        OrganizationEventType.KNOWLEDGE_DISCOVERED.value
        == "knowledge_discovered"
    )