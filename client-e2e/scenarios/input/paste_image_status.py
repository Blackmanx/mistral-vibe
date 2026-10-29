"""Pasted image files insert placeholders and a compact staged-image row."""

from __future__ import annotations

import struct
from pathlib import Path
import zlib

from e2e.app_server.events import paste
from e2e.app_server.scenario import Timeline

_DIR = Path("/tmp/vibe_e2e_fixtures")
_IMAGE = _DIR / "preview.png"


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _png() -> bytes:
    width = height = 16
    raw = b"".join(
        b"\x00"
        + b"".join(bytes((x * 17, y * 17, 128)) for x in range(width))
        for y in range(height)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


_DIR.mkdir(parents=True, exist_ok=True)
_IMAGE.write_bytes(_png())

capture_startup = False
screen_contains = ("🖼 2 images", "[Image #1]", "[Image #2]")

timeline: Timeline = [paste(str(_IMAGE)), paste(str(_IMAGE))]
