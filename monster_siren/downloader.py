from __future__ import annotations

import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .api import MAX_COVER_BYTES, MAX_LYRIC_BYTES, MonsterSirenAPI
from .audio import (
    convert_wav_to_flac,
    detect_audio_type,
    ensure_ffmpeg,
    validate_audio,
    write_metadata,
)
from .metadata import (
    AlbumMetadata,
    load_metadata_snapshot,
)
from .metadata_apply import MetadataApplier, MetadataApplyConfig
from .state import DownloadState
from .utils import (
    album_directory_name,
    is_valid_cover,
    normalize_album_name,
    save_cover_as_png,
    song_stem,
)


@dataclass(frozen=True)
class DownloaderConfig:
    output_dir: Path
    workers: int = 4
    album_filters: tuple[str, ...] = ()
    album_cid: str | None = None
    song_cid: str | None = None
    force: bool = False
    download_lyrics: bool = True
    metadata_snapshot: Path | None = None

    def __post_init__(self) -> None:
        if self.workers < 1:
            raise ValueError("workers must be at least 1")
        if self.album_cid is not None and not self.album_cid:
            raise ValueError("album CID must not be empty")
        if self.song_cid is not None and not self.song_cid:
            raise ValueError("song CID must not be empty")
        targets = (self.album_filters, self.album_cid, self.song_cid)
        if sum(bool(value) for value in targets) > 1:
            raise ValueError("album filters and CID targets cannot be combined")


@dataclass
class DownloadReport:
    albums: int = 0
    songs: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    failed_albums: int = 0

    def add(self, other: DownloadReport) -> None:
        self.songs += other.songs
        self.downloaded += other.downloaded
        self.skipped += other.skipped
        self.failed += other.failed
        self.failed_albums += other.failed_albums


class Downloader:
    def __init__(self, config: DownloaderConfig) -> None:
        self.config = config
        self.output_dir = config.output_dir.expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        ensure_ffmpeg()
        self.state = DownloadState(self.output_dir / "download_state.json")
        self.metadata = load_metadata_snapshot(config.metadata_snapshot)

    def run(self) -> DownloadReport:
        with MonsterSirenAPI() as api:
            albums = api.get_albums()
            if self.config.song_cid is not None:
                album = self._find_song_album(api, albums, self.config.song_cid)
                targets = [(album, self.config.song_cid)]
            else:
                targets = [(album, None) for album in self._filter_albums(albums)]

        logging.info("Selected %d album(s).", len(targets))

        report = DownloadReport(albums=len(targets))
        with ThreadPoolExecutor(max_workers=self.config.workers) as pool:
            futures = [
                pool.submit(self._download_album, album, song_cid)
                for album, song_cid in targets
            ]
            for future in as_completed(futures):
                try:
                    report.add(future.result())
                except Exception:
                    report.failed_albums += 1
                    logging.exception("Album worker failed.")

        if report.downloaded or report.skipped:
            try:
                metadata_report = MetadataApplier(
                    MetadataApplyConfig(
                        output_dir=self.config.output_dir,
                        metadata_snapshot=self.config.metadata_snapshot,
                        album_filters=self.config.album_filters,
                        album_cid=self.config.album_cid,
                        song_cid=self.config.song_cid,
                    ),
                    metadata=self.metadata,
                ).run()
                report.failed += metadata_report.failed
            except Exception:
                report.failed += 1
                logging.exception("Could not reconcile metadata after download.")
        return report

    def _filter_albums(self, albums: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.config.album_cid is not None:
            matches = [
                album for album in albums if album["cid"] == self.config.album_cid
            ]
            if not matches:
                raise ValueError(f"Album CID not found: {self.config.album_cid}")
            return matches
        if not self.config.album_filters:
            return albums

        needles = [item.casefold() for item in self.config.album_filters]
        return [
            album
            for album in albums
            if any(needle in album.get("name", "").casefold() for needle in needles)
        ]

    @staticmethod
    def _find_song_album(
        api: MonsterSirenAPI, albums: list[dict[str, Any]], song_cid: str
    ) -> dict[str, Any]:
        match: dict[str, Any] | None = None
        for album in albums:
            songs = api.get_album_detail(album["cid"])["songs"]
            if any(song["cid"] == song_cid for song in songs):
                if match is not None:
                    raise ValueError(f"Song CID appears in multiple albums: {song_cid}")
                match = album
        if match is None:
            raise ValueError(f"Song CID not found: {song_cid}")
        return match

    def _download_album(
        self, album: dict[str, Any], song_cid: str | None = None
    ) -> DownloadReport:
        report = DownloadReport()
        album_cid = album["cid"]
        album_name = normalize_album_name(album["name"])
        album_metadata = self.metadata.album(album_cid)
        msr_album_artists = self._string_list(album.get("artistes"))
        album_artists = self._resolve_album_artists(msr_album_artists, album_metadata)
        song_artist_fallback = (
            list(album_metadata.artists)
            if album_metadata is not None
            else album_artists
        )
        release_date = (
            album_metadata.release_date if album_metadata is not None else None
        )
        album_dir = self.output_dir / album_directory_name(album_name, album_cid)
        album_dir.mkdir(parents=True, exist_ok=True)
        if song_cid is None:
            self.state.mark_album_started(album_cid, album_name)

        logging.info("Album: %s", album_name)

        try:
            # A session belongs to one album task and is never shared across threads.
            with MonsterSirenAPI() as api:
                cover_path = album_dir / "cover.png"
                if self.config.force or not is_valid_cover(cover_path):
                    cover_url = album.get("coverUrl")
                    if not isinstance(cover_url, str):
                        raise ValueError(f"Album {album_cid} has no cover URL")
                    cover_bytes = api.download_bytes(
                        cover_url, max_bytes=MAX_COVER_BYTES
                    )
                    save_cover_as_png(cover_bytes, cover_path)

                detail = api.get_album_detail(album_cid)
                songs = detail["songs"]
                track_width = max(2, len(str(len(songs))))

                album_failed = False
                for track_number, song in enumerate(songs, start=1):
                    if song_cid is not None and song["cid"] != song_cid:
                        continue
                    report.songs += 1
                    try:
                        downloaded = self._download_song(
                            api=api,
                            album_cid=album_cid,
                            album_name=album_name,
                            album_artists=album_artists,
                            song_artist_fallback=song_artist_fallback,
                            album_dir=album_dir,
                            cover_path=cover_path,
                            song=song,
                            track_number=track_number,
                            track_width=track_width,
                            release_date=release_date,
                            prts_fingerprint=(
                                album_metadata.fingerprint
                                if album_metadata is not None
                                else None
                            ),
                            prts_album_artists=(
                                not msr_album_artists and album_metadata is not None
                            ),
                        )
                        if downloaded:
                            report.downloaded += 1
                        else:
                            report.skipped += 1
                    except Exception as exc:
                        album_failed = True
                        report.failed += 1
                        failed_song_cid = str(song.get("cid", "unknown"))
                        song_name = str(song.get("name", "unknown"))
                        self.state.mark_song(
                            album_cid,
                            album_name,
                            failed_song_cid,
                            song_name,
                            "failed",
                            error=f"{type(exc).__name__}: {exc}",
                        )
                        logging.exception("Failed: %s / %s", album_name, song_name)

                if album_failed:
                    raise RuntimeError(f"One or more songs failed in {album_name}")

                if song_cid is None:
                    self.state.mark_album_complete(album_cid, album_name)
                logging.info("Completed album: %s", album_name)
                return report
        except Exception as exc:
            report.failed_albums = 1
            self.state.mark_album_failed(
                album_cid, album_name, f"{type(exc).__name__}: {exc}"
            )
            logging.exception("Album worker failed: %s", album_name)
            return report

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
        track_width: int,
        song_artist_fallback: list[str] | None = None,
        release_date: str | None = None,
        prts_fingerprint: str | None = None,
        prts_album_artists: bool = False,
    ) -> bool:
        song_cid = song["cid"]
        song_name = song["name"]

        stem = song_stem(song_name, song_cid, track_number, track_width)
        expected_stem = album_dir / stem
        if not self.config.force and self.state.is_song_complete(
            album_cid,
            song_cid,
            expected_stem=expected_stem,
            require_lyrics=self.config.download_lyrics,
        ):
            logging.info("Skip completed: %s / %s", album_name, song_name)
            return False

        self.state.mark_song(
            album_cid,
            album_name,
            song_cid,
            song_name,
            "in_progress",
        )

        detail = api.get_song_detail(song_cid)
        source_url = detail["sourceUrl"]
        lyric_url = detail.get("lyricUrl")
        summary_artists = self._string_list(song.get("artistes"))
        detail_artists = self._string_list(detail.get("artists"))
        artists = self._resolve_song_artists(
            summary_artists,
            detail_artists,
            song_artist_fallback if song_artist_fallback is not None else album_artists,
        )

        if lyric_url is not None and not isinstance(lyric_url, str):
            raise ValueError(f"Song {song_cid} has an invalid lyric URL")

        final_lyric_path: Path | None = None
        with tempfile.TemporaryDirectory(
            prefix=".song-", dir=album_dir
        ) as work_dir_name:
            work_dir = Path(work_dir_name)
            staged_lyric: Path | None = None
            if self.config.download_lyrics and lyric_url:
                lyric_data = api.download_bytes(lyric_url, max_bytes=MAX_LYRIC_BYTES)
                lyric_data.decode("utf-8")
                staged_lyric = work_dir / "lyrics.lrc"
                staged_lyric.write_bytes(lyric_data)

            raw_path = work_dir / "audio.download"
            content_type = api.stream_to_file(source_url, raw_path)
            audio_type = detect_audio_type(raw_path)
            logging.debug(
                "Detected %s for %s (Content-Type: %s)",
                audio_type,
                song_name,
                content_type or "missing",
            )

            if audio_type == "wav":
                wav_path = work_dir / "audio.wav"
                raw_path.replace(wav_path)
                staged_audio = convert_wav_to_flac(wav_path)
            else:
                staged_audio = work_dir / f"audio.{audio_type}"
                raw_path.replace(staged_audio)

            write_metadata(
                staged_audio,
                album=album_name,
                title=song_name,
                album_artists=album_artists,
                artists=artists,
                track_number=track_number,
                cover_path=cover_path,
                lyric_path=staged_lyric,
                release_date=release_date,
            )
            validate_audio(staged_audio)

            audio_path = Path(f"{expected_stem}{staged_audio.suffix}")
            if staged_lyric is not None:
                final_lyric_path = Path(f"{expected_stem}.lrc")
                staged_lyric.replace(final_lyric_path)
            staged_audio.replace(audio_path)

        obsolete_suffix = ".flac" if audio_path.suffix == ".mp3" else ".mp3"
        Path(f"{expected_stem}{obsolete_suffix}").unlink(missing_ok=True)
        if not self.config.download_lyrics:
            Path(f"{expected_stem}.lrc").unlink(missing_ok=True)

        self.state.mark_song(
            album_cid,
            album_name,
            song_cid,
            song_name,
            "complete",
            output_path=audio_path,
            lyric_path=final_lyric_path,
            lyrics_complete=self.config.download_lyrics,
            prts_fingerprint=prts_fingerprint,
            prts_album_artists=prts_album_artists,
            prts_song_artists=(
                prts_fingerprint is not None
                and not summary_artists
                and not detail_artists
            ),
        )
        logging.info("Completed: %s / %s", album_name, song_name)
        return True

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str) and item]

    @staticmethod
    def _resolve_album_artists(
        msr_artists: list[str], prts: AlbumMetadata | None
    ) -> list[str]:
        if msr_artists or prts is None:
            return msr_artists
        return list(prts.artists)

    @staticmethod
    def _resolve_song_artists(
        summary_artists: list[str],
        detail_artists: list[str],
        album_artists: list[str],
    ) -> list[str]:
        return summary_artists or detail_artists or album_artists
