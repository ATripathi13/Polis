from domain.reasoning import (
    ReasoningDecision,
    ReasoningService,
    ReasoningAction,
)

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)


class DummyReasoner(ReasoningService):

    def reason(
        self,
        communication: CommunicationEvent,
    ) -> ReasoningDecision:

        return ReasoningDecision(
            action=ReasoningAction.IGNORE,
            confidence=1.0,
            reason="Dummy implementation",
        )


def test_reasoning_service():

    reasoner = DummyReasoner()

    assert isinstance(
        reasoner,
        ReasoningService,
    )