from domain.observation import (
    Observation,
    ObservationType,
)


def test_create_observation():

    observation = Observation(
        observation_type=ObservationType.KNOWLEDGE,
        summary="Database is PostgreSQL.",
    )

    assert observation.observation_type == ObservationType.KNOWLEDGE

    assert observation.summary == "Database is PostgreSQL."

    assert observation.confidence == 1.0

    assert observation.evidence == []