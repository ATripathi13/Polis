from domain.observation import (
    ObservationBundle,
    ObservationResult,
)


def test_create_observation_result():

    bundle = ObservationBundle(
        observations=[],
    )

    result = ObservationResult(
        bundle=bundle,
        extractor="RuleBasedObservationExtractor",
    )

    assert result.bundle is bundle

    assert (
        result.extractor
        == "RuleBasedObservationExtractor"
    )