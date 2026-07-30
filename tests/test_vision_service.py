from __future__ import annotations

import base64

import pytest

from personalai.core.errors import UserFacingError
from personalai.services import vision_service


def test_encode_image_base64_round_trips(tmp_path):
    path = tmp_path / "pic.png"
    data = b"not a real png but bytes are bytes"
    path.write_bytes(data)
    encoded = vision_service.encode_image_base64(path)
    assert base64.b64decode(encoded) == data


def test_missing_image_raises(tmp_path):
    with pytest.raises(UserFacingError, match="not found"):
        vision_service.encode_image_base64(tmp_path / "nope.png")


def test_unsupported_extension_raises(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(UserFacingError, match="Unsupported image type"):
        vision_service.encode_image_base64(path)


@pytest.mark.parametrize("ext", [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"])
def test_all_supported_extensions_accepted(tmp_path, ext):
    path = tmp_path / f"pic{ext}"
    path.write_bytes(b"data")
    vision_service.encode_image_base64(path)  # must not raise
