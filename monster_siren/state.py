from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CompletedSong:
    album_cid: str
    album_name: str
    song_cid: str
    song_name: str
    output_path: Path | None
    lyric_path: Path | None
    lyrics_complete: bool
    prts_fingerprint: str | None
    prts_album_artists: bool
    prts_song_artists: bool


class DownloadState:
    """Thread-safe, atomic JSON state store keyed by album/song cid."""

    VERSION = 3

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {"version": self.VERSION, "albums": {}}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return

        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("albums"), dict):
                self._data = data
                self._data["version"] = self.VERSION
            else:
                raise ValueError("state root must contain an albums object")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            backup = self.path.with_name(f"{self.path.name}.broken-{time.time_ns()}")
            try:
                self.path.replace(backup)
                logging.warning("Invalid state moved to %s: %s", backup, exc)
            except OSError:
                logging.warning("Invalid state could not be backed up: %s", exc)

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=self.path.parent,
                delete=False,
            ) as temp:
                temp_path = Path(temp.name)
                json.dump(self._data, temp, ensure_ascii=False, indent=2)
                temp.flush()
                os.fsync(temp.fileno())
            temp_path.replace(self.path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def is_song_complete(
        self,
        album_cid: str,
        song_cid: str,
        *,
        expected_stem: Path,
        require_lyrics: bool,
    ) -> bool:
        with self._lock:
            albums = self._data.get("albums", {})
            if not isinstance(albums, dict):
                return False
            album = albums.get(album_cid, {})
            if not isinstance(album, dict):
                return False
            songs = album.get("songs", {})
            if not isinstance(songs, dict):
                return False
            song = songs.get(song_cid, {})
            if not isinstance(song, dict) or song.get("status") != "complete":
                return False

            output = self._resolve_output(song.get("output"))
            expected_parent = expected_stem.parent.resolve()
            if (
                output is None
                or output.parent != expected_parent
                or output.name
                not in {
                    f"{expected_stem.name}.mp3",
                    f"{expected_stem.name}.flac",
                }
                or not output.is_file()
                or output.stat().st_size <= 0
                or output.stat().st_size != song.get("size")
            ):
                return False

            if require_lyrics and song.get("lyrics"):
                lyric = self._resolve_output(song.get("lyrics"))
                return (
                    bool(song.get("lyrics_complete"))
                    and lyric is not None
                    and lyric.is_file()
                    and lyric.stat().st_size > 0
                    and lyric.stat().st_size == song.get("lyrics_size")
                )
            return not require_lyrics or bool(song.get("lyrics_complete"))

    def _resolve_output(self, value: object) -> Path | None:
        if not isinstance(value, str) or not value:
            return None
        root = self.path.parent.resolve()
        candidate = (root / value).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate

    def mark_song(
        self,
        album_cid: str,
        album_name: str,
        song_cid: str,
        song_name: str,
        status: str,
        *,
        error: str | None = None,
        output_path: Path | None = None,
        lyric_path: Path | None = None,
        lyrics_complete: bool = False,
        prts_fingerprint: str | None = None,
        prts_album_artists: bool = False,
        prts_song_artists: bool = False,
    ) -> None:
        with self._lock:
            albums = self._data.setdefault("albums", {})
            album = albums.setdefault(album_cid, {"name": album_name, "songs": {}})
            if not isinstance(album, dict):
                album = {"name": album_name, "songs": {}}
                albums[album_cid] = album
            album["name"] = album_name
            songs = album.setdefault("songs", {})
            if not isinstance(songs, dict):
                songs = {}
                album["songs"] = songs
            song = {
                "name": song_name,
                "status": status,
            }
            if error:
                song["error"] = error
            if output_path is not None:
                song["output"] = str(
                    output_path.resolve().relative_to(self.path.parent.resolve())
                )
                song["size"] = output_path.stat().st_size
            if lyric_path is not None:
                song["lyrics"] = str(
                    lyric_path.resolve().relative_to(self.path.parent.resolve())
                )
                song["lyrics_size"] = lyric_path.stat().st_size
            song["lyrics_complete"] = lyrics_complete
            if prts_fingerprint is not None:
                song["prtsMetadataFingerprint"] = prts_fingerprint
                song["prtsAlbumArtists"] = prts_album_artists
                song["prtsSongArtists"] = prts_song_artists
            songs[song_cid] = song
            if status != "complete":
                album.pop("status", None)
            self._save_locked()

    def completed_songs(self) -> list[CompletedSong]:
        with self._lock:
            result: list[CompletedSong] = []
            albums = self._data.get("albums", {})
            if not isinstance(albums, dict):
                return result
            for album_cid, album in albums.items():
                if not isinstance(album_cid, str) or not isinstance(album, dict):
                    continue
                songs = album.get("songs", {})
                if not isinstance(songs, dict):
                    continue
                for song_cid, song in songs.items():
                    if (
                        not isinstance(song_cid, str)
                        or not isinstance(song, dict)
                        or song.get("status") != "complete"
                    ):
                        continue
                    fingerprint = song.get("prtsMetadataFingerprint")
                    output_path = self._resolve_output(song.get("output"))
                    if output_path is None:
                        continue
                    result.append(
                        CompletedSong(
                            album_cid=album_cid,
                            album_name=str(album.get("name", "")),
                            song_cid=song_cid,
                            song_name=str(song.get("name", "")),
                            output_path=output_path,
                            lyric_path=self._resolve_output(song.get("lyrics")),
                            lyrics_complete=bool(song.get("lyrics_complete")),
                            prts_fingerprint=(
                                fingerprint if isinstance(fingerprint, str) else None
                            ),
                            prts_album_artists=bool(song.get("prtsAlbumArtists")),
                            prts_song_artists=bool(song.get("prtsSongArtists")),
                        )
                    )
            return result

    def song_metadata_fingerprint(self, album_cid: str, song_cid: str) -> str | None:
        with self._lock:
            song = self._song_record_locked(album_cid, song_cid)
            if song is None:
                return None
            fingerprint = song.get("prtsMetadataFingerprint")
            return fingerprint if isinstance(fingerprint, str) else None

    def mark_metadata_applied(
        self,
        album_cid: str,
        song_cid: str,
        output_path: Path,
        prts_fingerprint: str | None,
        *,
        prts_album_artists: bool | None = None,
        prts_song_artists: bool | None = None,
    ) -> None:
        with self._lock:
            song = self._song_record_locked(album_cid, song_cid)
            if song is None or song.get("status") != "complete":
                raise ValueError(f"Song is not complete in state: {song_cid}")
            recorded = self._resolve_output(song.get("output"))
            if recorded is None or recorded != output_path.resolve():
                raise ValueError(f"Song output does not match state: {song_cid}")
            song["size"] = output_path.stat().st_size
            if prts_fingerprint is not None:
                song["prtsMetadataFingerprint"] = prts_fingerprint
            if prts_album_artists is not None:
                song["prtsAlbumArtists"] = prts_album_artists
            if prts_song_artists is not None:
                song["prtsSongArtists"] = prts_song_artists
            self._save_locked()

    def _song_record_locked(
        self, album_cid: str, song_cid: str
    ) -> dict[str, Any] | None:
        albums = self._data.get("albums", {})
        if not isinstance(albums, dict):
            return None
        album = albums.get(album_cid, {})
        if not isinstance(album, dict):
            return None
        songs = album.get("songs", {})
        if not isinstance(songs, dict):
            return None
        song = songs.get(song_cid, {})
        return song if isinstance(song, dict) else None

    def mark_album_started(self, album_cid: str, album_name: str) -> None:
        with self._lock:
            album = self._data["albums"].setdefault(
                album_cid, {"name": album_name, "songs": {}}
            )
            album["name"] = album_name
            album["status"] = "in_progress"
            self._save_locked()

    def mark_album_failed(self, album_cid: str, album_name: str, error: str) -> None:
        with self._lock:
            album = self._data["albums"].setdefault(
                album_cid, {"name": album_name, "songs": {}}
            )
            album["name"] = album_name
            album["status"] = "failed"
            album["error"] = error
            self._save_locked()

    def mark_album_complete(self, album_cid: str, album_name: str) -> None:
        with self._lock:
            album = self._data["albums"].setdefault(
                album_cid, {"name": album_name, "songs": {}}
            )
            album["name"] = album_name
            album["status"] = "complete"
            album.pop("error", None)
            self._save_locked()
