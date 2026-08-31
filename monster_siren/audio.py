from __future__ import annotations

from pathlib import Path

import pylrc
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, SYLT, Encoding
from pydub import AudioSegment
from PIL import Image


def convert_wav_to_flac(wav_path: Path) -> Path:
    flac_path = wav_path.with_suffix(".flac")
    partial = flac_path.with_name(flac_path.name + ".part")

    try:
        AudioSegment.from_wav(wav_path).export(partial, format="flac")
        partial.replace(flac_path)
        wav_path.unlink()
        return flac_path
    except Exception:
        partial.unlink(missing_ok=True)
        raise


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
        tags = EasyID3(audio_path)
        tags["album"] = album
        tags["title"] = title
        tags["albumartist"] = _artist_text(album_artists)
        tags["artist"] = _artist_text(artists)
        tags["tracknumber"] = str(track_number)
        tags.save()

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

    flac.save()
