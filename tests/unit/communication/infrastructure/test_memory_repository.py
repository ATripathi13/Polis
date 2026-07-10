from engines.communication.infrastructure.repositories import (
    InMemoryCommunicationRepository,
)


def test_create_memory_repository():

    repo = InMemoryCommunicationRepository()

    assert repo.events == []