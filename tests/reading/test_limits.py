"""Upload ceilings for Immersive Reading materials."""

from deeptutor.reading.limits import (
    MAX_AUDIO_BYTES,
    MAX_DOCUMENT_BYTES,
    MAX_VIDEO_BYTES,
    material_size_limit,
)
from deeptutor.utils.document_validator import DocumentValidator


def test_the_document_ceiling_is_the_knowledge_base_ceiling() -> None:
    """A document that fits here must fit in a knowledge base too."""
    assert MAX_DOCUMENT_BYTES == DocumentValidator.MAX_FILE_SIZE


def test_the_three_tiers_stay_ordered() -> None:
    assert MAX_AUDIO_BYTES < MAX_DOCUMENT_BYTES < MAX_VIDEO_BYTES


def test_the_ceiling_is_picked_by_extension() -> None:
    assert material_size_limit("lecture.mp4") == MAX_VIDEO_BYTES
    assert material_size_limit("track.MP3") == MAX_AUDIO_BYTES
    assert material_size_limit("notes.pdf") == MAX_DOCUMENT_BYTES


def test_an_unknown_extension_is_treated_as_a_document() -> None:
    assert material_size_limit("notes") == MAX_DOCUMENT_BYTES
    assert material_size_limit("notes.bin") == MAX_DOCUMENT_BYTES
