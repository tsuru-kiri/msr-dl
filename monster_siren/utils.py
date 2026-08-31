from __future__ import annotations

import re
from pathlib import Path

from PIL import Image


_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str) -> str:
    """Create a portable filename while keeping Unicode and readable spaces."""
    cleaned = _INVALID.sub("_", name).strip().rstrip(". ")
    return cleaned or "_"


def save_cover_as_png(jpeg_or_image_bytes: bytes, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_source = destination.with_name(destination.name + ".source.tmp")
    temp_png = destination.with_name(destination.name + ".tmp")

    try:
        temp_source.write_bytes(jpeg_or_image_bytes)
        with Image.open(temp_source) as image:
            image.convert("RGB").save(temp_png, format="PNG")
        temp_png.replace(destination)
    finally:
        temp_source.unlink(missing_ok=True)
        temp_png.unlink(missing_ok=True)
