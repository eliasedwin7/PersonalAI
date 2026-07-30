"""Image loading/encoding for the vision (image captioning/description)
task.

Kept as its own module rather than folded into chat_service: "turn a
file on disk into what Ollama's vision API needs" is one clear
responsibility, and keeping it separate is what makes this genuinely
independent of any specific project's own tagging pipeline (this never
touches WD14/JoyCaption or anything Dune-specific - it's a generic "ask
a local vision model about any image" tool, usable from any project).
"""

from __future__ import annotations

import base64
from pathlib import Path

from personalai.core.errors import UserFacingError

SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
DEFAULT_INSTRUCTION = "Describe this image in detail."


def encode_image_base64(path: Path) -> str:
    if not path.exists():
        raise UserFacingError(f"Image not found: {path}")
    if path.suffix.lower() not in SUPPORTED_IMAGE_EXTS:
        raise UserFacingError(
            f"Unsupported image type '{path.suffix}' (supported: "
            f"{', '.join(sorted(SUPPORTED_IMAGE_EXTS))})"
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise UserFacingError(f"Could not read {path}: {exc}") from exc
    return base64.b64encode(data).decode("ascii")
