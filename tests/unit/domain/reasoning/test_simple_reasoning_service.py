from engines.communication.domain.aggregates import (
    CommunicationEvent,
)
from engines.communication.domain.enums import (
    EventSource,
)
from engines.communication.domain.value_objects import (
    Actor,
    Channel,
    CommunicationIdentity,
    Content,
)
from engines.communication.infrastructure.repositories import (
    InMemoryCommunicationRepository,
)
from domain.common.identifier import Identifier
from domain.reasoning import (
    Question,
    SimpleReasoningService,
)


class FakeLLM:
    def generate(self, prompt: str) -> str:
        return "We use PostgreSQL."


def test_answer_question_from_communication_memory():

    communication_repository = (
        InMemoryCommunicationRepository()
    )

    communication = CommunicationEvent.create(
        correlation_id=Identifier(),
        source=EventSource.SLACK,
        source_event_id="test-1",
        actor=Actor(
            identity=CommunicationIdentity(
                internal_id="USER-001",
            ),
            display_name="John Doe",
        ),
        channel=Channel(
            identity=CommunicationIdentity(
                internal_id="CHANNEL-001",
            ),
            name="general",
            channel_type="public",
        ),
        content=Content(
            body="We use PostgreSQL as our database.",
        ),
    )

    communication_repository.save(
        communication
    )

    service = SimpleReasoningService(
        repository=None,
        communication_repository=(
            communication_repository
        ),
        llm_client=FakeLLM(),
    )

    answer = service.answer(
        Question(
            text="What database do we use?",
        )
    )

    assert answer.text == "We use PostgreSQL."
    assert answer.confidence == 0.8
    assert answer.evidence == [
        "We use PostgreSQL as our database."
    ]