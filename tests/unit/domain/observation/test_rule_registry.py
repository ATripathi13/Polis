from domain.observation import (
    Observation,
    ObservationRuleRegistry,
    ObservationType,
)

from domain.observation.rules import (
    ObservationRule,
)

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)


class DummyRule(ObservationRule):

    @property
    def priority(self):
        return 10

    def extract(
        self,
        communication: CommunicationEvent,
    ):
        return [
            Observation(
                observation_type=ObservationType.UNKNOWN,
                summary="Dummy",
            )
        ]


def test_register_rule():

    registry = ObservationRuleRegistry()

    registry.register(
        DummyRule(),
    )

    assert len(registry.rules) == 1