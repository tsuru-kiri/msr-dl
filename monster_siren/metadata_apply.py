from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .api import MonsterSirenAPI
from .audio import (
    apply_prts_metadata,
    ensure_ffmpeg,
    validate_audio,
    write_metadata,
)
from .metadata import DEFAULT_SNAPSHOT_PATH, AlbumMetadata, MetadataSnapshot
from .state import CompletedSong, DownloadState
from .utils import is_valid_cover, normalize_album_name


@dataclass(frozen=True)
class MetadataApplyConfig:
    output_dir: Path
    metadata_snapshot: Path | None = None
    album_filters: tuple[str, ...] = ()
    album_cid: str | None = None
    song_cid: str | None = None
    apply_all: bool = False
    force: bool = False

    def __post_init__(self) -> None:
        targets = (self.album_filters, self.album_cid, self.song_cid)
        if sum(bool(value) for value in targets) > 1:
            raise ValueError("album filters and CID targets cannot be combined")


@dataclass
class MetadataApplyReport:
    albums: int = 0
    songs: int = 0
    msr_applied: int = 0
    prts_applied: int = 0
    prts_unchanged: int = 0
    missing: int = 0
    failed: int = 0


class MetadataApplier:
    def __init__(self, config: MetadataApplyConfig) -> None:
        self.config = config
        self.output_dir = config.output_dir.expanduser().resolve()
        ensure_ffmpeg()
        self.state = DownloadState(self.output_dir / "download_state.json")
        self.metadata = MetadataSnapshot.from_path(
            config.metadata_snapshot or DEFAULT_SNAPSHOT_PATH
        )

    def run(self) -> MetadataApplyReport:
        downloaded = self.state.completed_songs()
        report = MetadataApplyReport()
        if not downloaded and not self._has_explicit_target():
            return report

        with MonsterSirenAPI() as api:
            albums = api.get_albums()
            selected = self._select_albums(api, albums)
            downloaded_by_album = self._downloaded_by_album(downloaded)
            selected_downloads = [
                song
                for album in selected
                for song in downloaded_by_album.get(str(album["cid"]), [])
                if self.config.song_cid is None or song.song_cid == self.config.song_cid
            ]
            if self._has_explicit_target() and not selected_downloads:
                raise ValueError("Selected metadata target is not downloaded")

            report.albums = len({song.album_cid for song in selected_downloads})
            report.songs = len(selected_downloads)
            selected_by_cid = {str(album["cid"]): album for album in selected}
            detail_cache: dict[str, dict[str, Any]] = {}
            if self.config.album_cid is not None or self.config.album_filters:
                for album in selected:
                    album_cid = str(album["cid"])
                    detail = api.get_album_detail(album_cid)
                    detail_cache[album_cid] = detail
                    downloaded_cids = {
                        song.song_cid
                        for song in selected_downloads
                        if song.album_cid == album_cid
                    }
                    report.missing += sum(
                        song.get("cid") not in downloaded_cids
                        for song in detail.get("songs", [])
                    )
                if report.missing:
                    logging.warning(
                        "%d selected song(s) have not been downloaded.", report.missing
                    )
            for song in selected_downloads:
                try:
                    album = selected_by_cid[song.album_cid]
                    detail = detail_cache.get(song.album_cid)
                    if detail is None:
                        detail = api.get_album_detail(song.album_cid)
                        detail_cache[song.album_cid] = detail
                    self._apply_song(api, album, detail, song, report)
                except Exception:
                    report.failed += 1
                    logging.exception(
                        "Failed to apply metadata: %s / %s",
                        song.album_name,
                        song.song_name,
                    )
        return report

    def _has_explicit_target(self) -> bool:
        return bool(
            self.config.album_filters or self.config.album_cid or self.config.song_cid
        )

    def _select_albums(
        self,
        api: MonsterSirenAPI,
        albums: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if self.config.song_cid is not None:
            match: dict[str, Any] | None = None
            for album in albums:
                songs = api.get_album_detail(str(album["cid"]))["songs"]
                if any(song["cid"] == self.config.song_cid for song in songs):
                    if match is not None:
                        raise ValueError(
                            "Song CID appears in multiple albums: "
                            f"{self.config.song_cid}"
                        )
                    match = album
            if match is None:
                raise ValueError(f"Song CID not found: {self.config.song_cid}")
            return [match]

        if self.config.album_cid is not None:
            matches = [
                album for album in albums if album["cid"] == self.config.album_cid
            ]
            if not matches:
                raise ValueError(f"Album CID not found: {self.config.album_cid}")
            return matches

        if self.config.album_filters:
            needles = [value.casefold() for value in self.config.album_filters]
            return [
                album
                for album in albums
                if any(
                    needle in str(album.get("name", "")).casefold()
                    for needle in needles
                )
            ]

        downloaded_cids = {song.album_cid for song in self.state.completed_songs()}
        return [album for album in albums if album["cid"] in downloaded_cids]

    @staticmethod
    def _downloaded_by_album(
        songs: list[CompletedSong],
    ) -> dict[str, list[CompletedSong]]:
        result: dict[str, list[CompletedSong]] = {}
        for song in songs:
            result.setdefault(song.album_cid, []).append(song)
        return result

    def _apply_song(
        self,
        api: MonsterSirenAPI,
        album: dict[str, Any],
        detail: dict[str, Any],
        state_song: CompletedSong,
        report: MetadataApplyReport,
    ) -> None:
        output = state_song.output_path
        if output is None or not output.is_file():
            raise FileNotFoundError(
                f"Downloaded audio is missing: {state_song.song_cid}"
            )
        if output.suffix.lower() not in {".mp3", ".flac"}:
            raise ValueError(f"Unsupported output type: {output.suffix}")

        song_rows = list(detail.get("songs", []))
        song_row = next(
            (song for song in song_rows if song.get("cid") == state_song.song_cid),
            None,
        )
        if song_row is None:
            raise ValueError(f"Song CID not found in album: {state_song.song_cid}")

        prts = self.metadata.album(state_song.album_cid)
        apply_prts = prts is not None and (
            self.config.force or state_song.prts_fingerprint != prts.fingerprint
        )
        if not self.config.apply_all and not apply_prts:
            if prts is not None:
                report.prts_unchanged += 1
            return

        album_artists = _string_list(album.get("artistes"))
        summary_artists = _string_list(song_row.get("artistes"))
        detail_artists: list[str] = []
        if not summary_artists:
            detail_artists = _string_list(
                api.get_song_detail(state_song.song_cid).get("artists")
            )
        msr_song_artists = summary_artists or detail_artists

        if self.config.apply_all:
            prts_album_artists, prts_song_artists = self._apply_all(
                output,
                album,
                detail,
                song_row,
                state_song,
                prts,
                apply_prts,
                album_artists,
                msr_song_artists,
            )
            report.msr_applied += 1
        else:
            assert prts is not None
            prts_album_artists, prts_song_artists = self._replace_with_prts(
                output,
                prts,
                state_song,
                album_artists,
                msr_song_artists,
            )

        if apply_prts:
            report.prts_applied += 1
        else:
            report.prts_unchanged += 1
        self.state.mark_metadata_applied(
            state_song.album_cid,
            state_song.song_cid,
            output,
            prts.fingerprint if apply_prts and prts is not None else None,
            prts_album_artists=prts_album_artists,
            prts_song_artists=prts_song_artists,
        )

    def _replace_with_prts(
        self,
        output: Path,
        prts: AlbumMetadata,
        state_song: CompletedSong,
        album_artists: list[str],
        song_artists: list[str],
    ) -> tuple[bool, bool]:
        album_value = (
            list(prts.artists)
            if not album_artists
            else album_artists
            if state_song.prts_album_artists
            else None
        )
        song_value = (
            list(prts.artists)
            if not song_artists
            else song_artists
            if state_song.prts_song_artists
            else None
        )
        self._atomic_update(
            output,
            lambda staged: apply_prts_metadata(
                staged,
                release_date=prts.release_date,
                album_artists=album_value,
                artists=song_value,
            ),
        )
        return not album_artists, not song_artists

    def _apply_all(
        self,
        output: Path,
        album: dict[str, Any],
        detail: dict[str, Any],
        song: dict[str, Any],
        state_song: CompletedSong,
        prts: AlbumMetadata | None,
        apply_prts: bool,
        album_artists: list[str],
        song_artists: list[str],
    ) -> tuple[bool, bool]:
        cover_path = output.parent / "cover.png"
        if not is_valid_cover(cover_path):
            raise ValueError(f"Album cover is missing or invalid: {cover_path}")
        lyric_path = state_song.lyric_path
        if lyric_path is not None and not lyric_path.is_file():
            raise FileNotFoundError(f"Lyrics are missing: {lyric_path}")
        track_number = next(
            index
            for index, row in enumerate(detail["songs"], start=1)
            if row.get("cid") == state_song.song_cid
        )
        if album_artists:
            resolved_album_artists: list[str] | None = album_artists
            prts_album_artists = False
        elif apply_prts and prts is not None:
            resolved_album_artists = list(prts.artists)
            prts_album_artists = True
        elif state_song.prts_album_artists:
            resolved_album_artists = None
            prts_album_artists = True
        else:
            resolved_album_artists = []
            prts_album_artists = False

        if song_artists:
            resolved_song_artists: list[str] | None = song_artists
            prts_song_artists = False
        elif apply_prts and prts is not None:
            resolved_song_artists = list(prts.artists)
            prts_song_artists = True
        elif state_song.prts_song_artists:
            resolved_song_artists = None
            prts_song_artists = True
        else:
            resolved_song_artists = []
            prts_song_artists = False
        self._atomic_update(
            output,
            lambda staged: write_metadata(
                staged,
                album=normalize_album_name(str(album["name"])),
                title=str(song["name"]),
                album_artists=resolved_album_artists,
                artists=resolved_song_artists,
                track_number=track_number,
                cover_path=cover_path,
                lyric_path=lyric_path,
                release_date=(
                    prts.release_date if apply_prts and prts is not None else None
                ),
                preserve_date=not apply_prts,
            ),
        )
        return prts_album_artists, prts_song_artists

    @staticmethod
    def _atomic_update(output: Path, writer: Callable[[Path], None]) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{output.stem}.",
                suffix=output.suffix,
                dir=output.parent,
                delete=False,
            ) as temp:
                temporary = Path(temp.name)
            shutil.copy2(output, temporary)
            writer(temporary)
            validate_audio(temporary)
            temporary.replace(output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]
