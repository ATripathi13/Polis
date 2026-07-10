from domain.observation import (
    ObservationExtractor,
    Observation,
    ObservationType,
)

from engines.communication.domain.aggregates import (
    CommunicationEvent,
)


class DummyExtractor(
    ObservationExtractor,
):

    def extract(
        self,
        communication: CommunicationEvent,
    ) -> list[Observation]:

        return [
            Observation(
                observation_type=ObservationType.UNKNOWN,
                summary="Dummy observation",
            )
        ]


def test_observation_extractor():

    extractor = DummyExtractor()

    assert isinstance(
        extractor,
        ObservationExtractor,
    )