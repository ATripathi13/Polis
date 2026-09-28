from domain.reasoning import (
    Question,
    SimpleReasoningService,
)

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


class FakeLLM:
    def generate(self, prompt: str) -> str:
        return "We use PostgreSQL."


def test_reasoning_from_memory():

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

    reasoning = SimpleReasoningService(
        repository=None,
        communication_repository=(
            communication_repository
        ),
        llm_client=FakeLLM(),
    )

    answer = reasoning.answer(
        Question(
            text="What database do we use?",
        )
    )

    assert answer.text == "We use PostgreSQL."
    assert answer.confidence == 0.8
    assert answer.evidence == [
        "We use PostgreSQL as our database."
    ]