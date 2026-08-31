from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from shutil import which

import pylrc
from mutagen import File as MutagenFile
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, SYLT, Encoding, ID3NoHeaderError
from mutagen.mp3 import MP3
from mutagen.wave import WAVE
from PIL import Image

FFMPEG_TIMEOUT = 10 * 60


def ensure_ffmpeg() -> None:
    if which("ffmpeg") is None:
        raise RuntimeError("FFmpeg is required but was not found on PATH")


def convert_wav_to_flac(wav_path: Path) -> Path:
    flac_path = wav_path.with_suffix(".flac")
    partial: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{flac_path.stem}.",
            suffix=".flac",
            dir=flac_path.parent,
            delete=False,
        ) as temp:
            partial = Path(temp.name)
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-y",
                "-i",
                str(wav_path),
                str(partial),
            ],
            check=True,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT,
        )
        FLAC(partial)
        partial.replace(flac_path)
        wav_path.unlink()
        return flac_path
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)


def detect_audio_type(path: Path) -> str:
    audio = MutagenFile(path)
    if isinstance(audio, MP3):
        return "mp3"
    if isinstance(audio, WAVE):
        return "wav"
    if isinstance(audio, FLAC):
        return "flac"
    raise ValueError("Downloaded file is not a supported MP3, WAV, or FLAC")


def validate_audio(path: Path) -> None:
    expected = path.suffix.lower().lstrip(".")
    actual = detect_audio_type(path)
    if actual != expected:
        raise ValueError(f"Expected {expected} audio, found {actual}")
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(path),
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=FFMPEG_TIMEOUT,
    )


def parse_synced_lyrics(path: Path) -> list[tuple[str, int]]:
    text = path.read_text(encoding="utf-8")
    subtitles = pylrc.parse(text)
    return [(sub.text, int(sub.time * 1000)) for sub in subtitles]


def _artist_text(values: list[str]) -> str:
    return ", ".join(value for value in values if value)


def write_metadata(
    audio_path: Path,
    *,
    album: str,
    title: str,
    album_artists: list[str],
    artists: list[str],
    track_number: int,
    cover_path: Path,
    lyric_path: Path | None,
) -> None:
    suffix = audio_path.suffix.lower()

    if suffix == ".mp3":
        try:
            tags = EasyID3(audio_path)
        except ID3NoHeaderError:
            tags = EasyID3()
        tags["album"] = album
        tags["title"] = title
        tags["albumartist"] = _artist_text(album_artists)
        tags["artist"] = _artist_text(artists)
        tags["tracknumber"] = str(track_number)
        tags.save(audio_path)

        id3 = ID3(audio_path)
        id3.delall("APIC")
        id3.add(
            APIC(
                mime="image/png",
                type=3,
                desc="Cover",
                data=cover_path.read_bytes(),
            )
        )

        id3.delall("SYLT")
        if lyric_path is not None:
            id3.setall(
                "SYLT",
                [
                    SYLT(
                        encoding=Encoding.UTF8,
                        lang="eng",
                        format=2,
                        type=1,
                        text=parse_synced_lyrics(lyric_path),
                    )
                ],
            )
        id3.save()
        return

    if suffix != ".flac":
        raise ValueError(f"Unsupported output type: {suffix}")

    flac = FLAC(audio_path)
    flac["album"] = album
    flac["title"] = title
    flac["albumartist"] = _artist_text(album_artists)
    flac["artist"] = _artist_text(artists)
    flac["tracknumber"] = str(track_number)

    flac.clear_pictures()
    picture = Picture()
    picture.type = 3
    picture.desc = "Cover"
    picture.mime = "image/png"
    picture.data = cover_path.read_bytes()
    with Image.open(cover_path) as image:
        picture.width, picture.height = image.size
    picture.depth = 24
    flac.add_picture(picture)

    if lyric_path is not None:
        flac["lyrics"] = lyric_path.read_text(encoding="utf-8")
    elif "lyrics" in flac:
        del flac["lyrics"]

    flac.save()
