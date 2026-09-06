from __future__ import annotations

import hashlib
import io
import re
import tempfile
import unicodedata
from pathlib import Path

from PIL import Image

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
MAX_COVER_PIXELS = 40_000_000


def normalize_album_name(name: str) -> str:
    return name.strip(" ")


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def safe_filename(name: str, *, max_bytes: int = 120) -> str:
    """Create a portable filename while keeping Unicode and readable spaces."""
    cleaned = _INVALID.sub("_", unicodedata.normalize("NFC", name)).strip().rstrip(". ")
    if cleaned.upper() in _WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    cleaned = _truncate_utf8(cleaned, max_bytes).rstrip(". ")
    return cleaned or "_"


def _safe_cid(cid: str) -> str:
    value = str(cid)
    if value.isascii() and value.isdigit() and len(value) <= 64:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{safe_filename(value, max_bytes=48)}-{digest}"


def album_directory_name(name: str, cid: str) -> str:
    safe_cid = _safe_cid(cid)
    suffix = f" [{safe_cid}]"
    name_bytes = 240 - len(suffix.encode("utf-8"))
    return f"{safe_filename(name, max_bytes=max(1, name_bytes))}{suffix}"


def song_stem(name: str, cid: str, track_number: int, width: int = 2) -> str:
    safe_cid = _safe_cid(cid)
    prefix = f"{track_number:0{width}d} - "
    suffix = f" [{safe_cid}]"
    name_bytes = 230 - len((prefix + suffix).encode("utf-8"))
    return f"{prefix}{safe_filename(name, max_bytes=max(1, name_bytes))}{suffix}"


def is_valid_cover(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        with Image.open(path) as image:
            _validate_cover_dimensions(image)
            image.verify()
        return True
    except (OSError, SyntaxError, ValueError):
        return False


def _validate_cover_dimensions(image: Image.Image) -> None:
    width, height = image.size
    if width <= 0 or height <= 0 or width * height > MAX_COVER_PIXELS:
        raise ValueError(f"Cover dimensions are too large: {width}x{height}")


def save_cover_as_png(jpeg_or_image_bytes: bytes, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with Image.open(io.BytesIO(jpeg_or_image_bytes)) as image:
            _validate_cover_dimensions(image)
            image.verify()
        with Image.open(io.BytesIO(jpeg_or_image_bytes)) as image:
            _validate_cover_dimensions(image)
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as temp:
                temp_path = Path(temp.name)
                image.convert("RGB").save(temp, format="PNG")
                temp.flush()
            temp_path.replace(destination)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
