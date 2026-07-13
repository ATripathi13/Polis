from domain.knowledge import (
    InMemoryKnowledgeRepository,
    KnowledgeCandidate,
    KnowledgeSubject,
)

from domain.reasoning import (
    Question,
    SimpleReasoningService,
)


def test_answer_question_from_repository():

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

    service = SimpleReasoningService(
        repository,
    )

    answer = service.answer(
        Question(
            text="What database do we use?",
        )
    )

    assert (
        answer.text
        == "We use PostgreSQL."
    )

    assert answer.confidence == 1.0