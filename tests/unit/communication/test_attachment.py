from dataclasses import FrozenInstanceError

import pytest

from engines.communication.domain.value_objects.attachment import Attachment


def test_create_attachment():

    attachment = Attachment(
        attachment_id="ATT-001",
        filename="report.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
    )

    assert attachment.filename == "report.pdf"


def test_optional_url():

    attachment = Attachment(
        attachment_id="ATT-001",
        filename="image.png",
        mime_type="image/png",
        size_bytes=2048,
        url="https://example.com/image.png",
    )

    assert attachment.url is not None


def test_negative_size():

    with pytest.raises(ValueError):
        Attachment(
            attachment_id="ATT-001",
            filename="file.txt",
            mime_type="text/plain",
            size_bytes=-1,
        )


def test_immutable():

    attachment = Attachment(
        attachment_id="ATT-001",
        filename="doc.pdf",
        mime_type="application/pdf",
        size_bytes=100,
    )

    with pytest.raises(FrozenInstanceError):
        attachment.filename = "new.pdf"