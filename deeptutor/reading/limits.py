"""Upload ceilings for Immersive Reading materials.

The three kinds are separated because they are different problems: a
document is parsed into text, an audio track is transcribed, and a video is
transcribed *and* played back. A lecture recording is routinely larger than
the document that accompanies it, so one shared ceiling would either refuse
ordinary videos or leave ordinary documents with no headroom.

The document ceiling is the same number the knowledge-base validator
enforces, so a document that passes the upload check cannot then be rejected
deeper in with a less helpful message — and the two surfaces cannot drift
apart.
"""

from __future__ import annotations

from pathlib import Path

from deeptutor.utils.document_validator import DocumentValidator

MAX_DOCUMENT_BYTES = DocumentValidator.MAX_FILE_SIZE
MAX_AUDIO_BYTES = 250 * 1024 * 1024
MAX_VIDEO_BYTES = 1024 * 1024 * 1024

AUDIO_EXTENSIONS = frozenset(
    {
        ".mp3",
        ".m4a",
        ".wav",
        ".aac",
        ".ogg",
        ".flac",
    }
)
VIDEO_EXTENSIONS = frozenset(
    {
        ".mp4",
        ".mov",
        ".mkv",
        ".webm",
        ".m4v",
    }
)
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


def material_size_limit(filename: str) -> int:
    """The upload ceiling for one material, by its extension.

    An extension the reader does not know is treated as a document: the
    smallest sensible cap, and the one a file is most likely to exceed.
    """
    suffix = Path(filename).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return MAX_VIDEO_BYTES
    if suffix in AUDIO_EXTENSIONS:
        return MAX_AUDIO_BYTES
    return MAX_DOCUMENT_BYTES


__all__ = [
    "AUDIO_EXTENSIONS",
    "MAX_AUDIO_BYTES",
    "MAX_DOCUMENT_BYTES",
    "MAX_VIDEO_BYTES",
    "MEDIA_EXTENSIONS",
    "VIDEO_EXTENSIONS",
    "material_size_limit",
]
