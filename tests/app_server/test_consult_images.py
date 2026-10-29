from __future__ import annotations

from pathlib import Path

import pytest

from vibe.app_server._provided_tools import _consult_images


def test_consult_reads_a_workspace_image(tmp_path: Path) -> None:
    image = tmp_path / "screen.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\npayload")

    [attachment] = _consult_images([str(image)])

    assert attachment.alias == "consult-1"
    assert attachment.mime_type == "image/png"


def test_consult_rejects_a_missing_image(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Not a file"):
        _consult_images([str(tmp_path / "missing.png")])


def test_consult_bounds_the_number_of_images(tmp_path: Path) -> None:
    image = tmp_path / "screen.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\npayload")

    with pytest.raises(ValueError, match="at most 4"):
        _consult_images([str(image)] * 5)
