from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class DownloadState:
    """Thread-safe, atomic JSON state store keyed by album/song cid."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {"version": 1, "albums": {}}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return

        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("albums"), dict):
                self._data = data
        except (OSError, json.JSONDecodeError):
            # Do not destroy a broken file; start with empty in-memory state.
            pass

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
            f.flush()
        temp.replace(self.path)

    def is_song_complete(self, album_cid: str, song_cid: str) -> bool:
        with self._lock:
            album = self._data["albums"].get(album_cid, {})
            song = album.get("songs", {}).get(song_cid, {})
            return song.get("status") == "complete"

    def mark_song(
        self,
        album_cid: str,
        album_name: str,
        song_cid: str,
        song_name: str,
        status: str,
        *,
        error: str | None = None,
    ) -> None:
        with self._lock:
            album = self._data["albums"].setdefault(
                album_cid, {"name": album_name, "songs": {}}
            )
            album["name"] = album_name
            song = {
                "name": song_name,
                "status": status,
            }
            if error:
                song["error"] = error
            album["songs"][song_cid] = song
            self._save_locked()

    def mark_album_complete(self, album_cid: str, album_name: str) -> None:
        with self._lock:
            album = self._data["albums"].setdefault(
                album_cid, {"name": album_name, "songs": {}}
            )
            album["name"] = album_name
            album["status"] = "complete"
            self._save_locked()
