from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .api import MonsterSirenAPI
from .audio import convert_wav_to_flac, write_metadata
from .state import DownloadState
from .utils import safe_filename, save_cover_as_png


@dataclass(frozen=True)
class DownloaderConfig:
    output_dir: Path
    workers: int = 4
    album_filters: tuple[str, ...] = ()
    force: bool = False
    download_lyrics: bool = True


class Downloader:
    def __init__(self, config: DownloaderConfig) -> None:
        self.config = config
        self.output_dir = config.output_dir.expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state = DownloadState(self.output_dir / "download_state.json")

    def run(self) -> int:
        with MonsterSirenAPI() as api:
            albums = api.get_albums()

        albums = self._filter_albums(albums)
        logging.info("Selected %d album(s).", len(albums))

        failures = 0
        with ThreadPoolExecutor(max_workers=self.config.workers) as pool:
            futures = [pool.submit(self._download_album, album) for album in albums]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    failures += 1
                    logging.exception("Album worker failed.")

        return failures

    def _filter_albums(self, albums: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.config.album_filters:
            return albums

        needles = [item.casefold() for item in self.config.album_filters]
        return [
            album
            for album in albums
            if any(needle in album.get("name", "").casefold() for needle in needles)
        ]

    def _download_album(self, album: dict[str, Any]) -> None:
        album_cid = album["cid"]
        album_name = album["name"]
        album_artists = album.get("artistes") or []
        album_dir = self.output_dir / safe_filename(album_name)
        album_dir.mkdir(parents=True, exist_ok=True)

        logging.info("Album: %s", album_name)

        # One Session per worker thread: no cross-thread Session sharing.
        with MonsterSirenAPI() as api:
            cover_path = album_dir / "cover.png"
            if self.config.force or not cover_path.exists():
                cover_bytes = api.download_bytes(album["coverUrl"])
                save_cover_as_png(cover_bytes, cover_path)

            detail = api.get_album_detail(album_cid)
            songs = detail.get("songs") or []

            album_failed = False
            for track_number, song in enumerate(songs, start=1):
                try:
                    self._download_song(
                        api=api,
                        album_cid=album_cid,
                        album_name=album_name,
                        album_artists=album_artists,
                        album_dir=album_dir,
                        cover_path=cover_path,
                        song=song,
                        track_number=track_number,
                    )
                except Exception as exc:
                    album_failed = True
                    song_cid = song.get("cid", "unknown")
                    song_name = song.get("name", "unknown")
                    self.state.mark_song(
                        album_cid,
                        album_name,
                        song_cid,
                        song_name,
                        "failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    logging.exception("Failed: %s / %s", album_name, song_name)

            if album_failed:
                raise RuntimeError(f"One or more songs failed in {album_name}")

            self.state.mark_album_complete(album_cid, album_name)
            logging.info("Completed album: %s", album_name)

    def _download_song(
        self,
        *,
        api: MonsterSirenAPI,
        album_cid: str,
        album_name: str,
        album_artists: list[str],
        album_dir: Path,
        cover_path: Path,
        song: dict[str, Any],
        track_number: int,
    ) -> None:
        song_cid = song["cid"]
        song_name = song["name"]

        if not self.config.force and self.state.is_song_complete(album_cid, song_cid):
            logging.info("Skip completed: %s / %s", album_name, song_name)
            return

        detail = api.get_song_detail(song_cid)
        source_url = detail["sourceUrl"]
        lyric_url = detail.get("lyricUrl")

        stem = safe_filename(song_name)
        lyric_path: Path | None = None

        if self.config.download_lyrics and lyric_url:
            lyric_path = album_dir / f"{stem}.lrc"
            lyric_data = api.download_bytes(lyric_url)
            lyric_path.write_bytes(lyric_data)

        # Download to a neutral temporary extension first; content-type decides final type.
        raw_path = album_dir / f"{stem}.download"
        content_type = api.stream_to_file(source_url, raw_path)

        if content_type == "audio/mpeg":
            audio_path = raw_path.with_suffix(".mp3")
            raw_path.replace(audio_path)
        elif content_type in {
            "audio/wav",
            "audio/x-wav",
            "audio/wave",
            "audio/vnd.wave",
            "application/octet-stream",
            "",
        }:
            wav_path = raw_path.with_suffix(".wav")
            raw_path.replace(wav_path)
            audio_path = convert_wav_to_flac(wav_path)
        else:
            raw_path.unlink(missing_ok=True)
            raise ValueError(f"Unsupported Content-Type: {content_type!r}")

        try:
            write_metadata(
                audio_path,
                album=album_name,
                title=song_name,
                album_artists=album_artists,
                artists=song.get("artistes") or [],
                track_number=track_number,
                cover_path=cover_path,
                lyric_path=lyric_path,
            )
        except Exception:
            # A file without correct metadata is not considered complete.
            raise

        self.state.mark_song(
            album_cid,
            album_name,
            song_cid,
            song_name,
            "complete",
        )
        logging.info("Completed: %s / %s", album_name, song_name)
