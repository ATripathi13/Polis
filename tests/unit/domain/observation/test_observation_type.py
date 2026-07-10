from domain.observation import (
    ObservationType,
)


def test_observation_type():

    assert (
        ObservationType.TASK.value
        == "task"
    )

    assert (
        ObservationType.KNOWLEDGE.value
        == "knowledge"
    )
    