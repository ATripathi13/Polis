from domain.knowledge import (
    InMemoryKnowledgeRepository,
    KnowledgeCandidate,
    KnowledgeSubject,
)

from domain.reasoning import (
    Question,
    SimpleReasoningService,
)


def test_reasoning_from_memory():

    repository = InMemoryKnowledgeRepository()

    repository.save(
        KnowledgeCandidate(
            subject=KnowledgeSubject(
                kind="technology",
                identifier="database",
            ),
            summary="We use PostgreSQL.",
        )
    )

    reasoning = SimpleReasoningService(
        repository,
    )

    answer = reasoning.answer(
        Question(
            text="What database do we use?",
        )
    )

    assert (
        answer.text
        == "We use PostgreSQL."
    )

    assert answer.confidence == 1.0