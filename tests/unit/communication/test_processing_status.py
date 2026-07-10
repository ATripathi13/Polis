from engines.communication.domain.enums import ProcessingStatus


def test_processing_status_values():
    assert ProcessingStatus.RECEIVED.value == "received"
    assert ProcessingStatus.NORMALIZED.value == "normalized"
    assert ProcessingStatus.PUBLISHED.value == "published"