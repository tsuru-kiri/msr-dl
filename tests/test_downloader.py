from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from monster_siren.downloader import Downloader, DownloaderConfig
from monster_siren.metadata import AlbumMetadata
from monster_siren.utils import album_directory_name, song_stem


class FakeAPI:
    def __init__(self, source: Path, song_cid: str) -> None:
        self.source = source
        self.song_cid = song_cid

    def get_song_detail(self, cid: str) -> dict[str, object]:
        self.song_cid = cid
        return {"sourceUrl": "https://web.hycdn.cn/audio.wav", "lyricUrl": None}

    def stream_to_file(self, url: str, destination: Path) -> str:
        shutil.copyfile(self.source, destination)
        return "application/octet-stream"


class DownloaderTests(unittest.TestCase):
    def test_same_song_names_produce_distinct_cid_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.wav"
            with wave.open(str(source), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8000)
                output.writeframes(b"\x00\x00" * 800)

            downloader = Downloader(
                DownloaderConfig(root / "output", workers=1, download_lyrics=False)
            )
            album_dir = downloader.output_dir / album_directory_name("Album", "a1")
            album_dir.mkdir()
            cover = album_dir / "cover.png"
            Image.new("RGB", (2, 2), "black").save(cover)

            for track, cid in enumerate(("s1", "s2"), start=1):
                downloader._download_song(
                    api=FakeAPI(source, cid),
                    album_cid="a1",
                    album_name="Album",
                    album_artists=["Artist"],
                    album_dir=album_dir,
                    cover_path=cover,
                    song={"cid": cid, "name": "Same", "artistes": ["Artist"]},
                    track_number=track,
                    track_width=2,
                )

            first = Path(f"{album_dir / song_stem('Same', 's1', 1)}.flac")
            second = Path(f"{album_dir / song_stem('Same', 's2', 2)}.flac")
            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())
            self.assertNotEqual(first, second)

    def test_metadata_failure_preserves_existing_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.wav"
            with wave.open(str(source), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8000)
                output.writeframes(b"\x00\x00" * 800)

            downloader = Downloader(
                DownloaderConfig(
                    root / "output",
                    workers=1,
                    force=True,
                    download_lyrics=False,
                )
            )
            album_dir = downloader.output_dir / album_directory_name("Album", "a1")
            album_dir.mkdir()
            cover = album_dir / "cover.png"
            Image.new("RGB", (2, 2), "black").save(cover)
            final_path = Path(f"{album_dir / song_stem('Song', 's1', 1)}.flac")
            final_path.write_bytes(b"existing-good-file")

            with patch(
                "monster_siren.downloader.write_metadata",
                side_effect=RuntimeError("tag failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "tag failure"):
                    downloader._download_song(
                        api=FakeAPI(source, "s1"),
                        album_cid="a1",
                        album_name="Album",
                        album_artists=["Artist"],
                        album_dir=album_dir,
                        cover_path=cover,
                        song={"cid": "s1", "name": "Song", "artistes": []},
                        track_number=1,
                        track_width=2,
                    )

            self.assertEqual(final_path.read_bytes(), b"existing-good-file")

    def test_worker_count_is_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 1"):
            DownloaderConfig(Path("output"), workers=0)

    def test_album_artists_only_use_prts_when_msr_is_empty(self) -> None:
        prts = AlbumMetadata("2023-11-25", ("塞壬唱片-MSR", "kiyo"))

        self.assertEqual(
            Downloader._resolve_album_artists(["塞壬唱片-MSR"], prts),
            ["塞壬唱片-MSR"],
        )
        self.assertEqual(
            Downloader._resolve_album_artists([], prts),
            ["塞壬唱片-MSR", "kiyo"],
        )

    def test_song_artist_priority_ends_with_prts_album_fallback(self) -> None:
        fallback = ["塞壬唱片-MSR", "kiyo"]

        self.assertEqual(
            Downloader._resolve_song_artists(["Summary"], ["Detail"], fallback),
            ["Summary"],
        )
        self.assertEqual(
            Downloader._resolve_song_artists([], ["Detail"], fallback), ["Detail"]
        )
        self.assertEqual(Downloader._resolve_song_artists([], [], fallback), fallback)

    def test_album_download_passes_snapshot_metadata_to_song(self) -> None:
        class AlbumAPI:
            def __enter__(self) -> AlbumAPI:
                return self

            def __exit__(self, *exc_info: object) -> None:
                pass

            def get_album_detail(self, cid: str) -> dict[str, object]:
                return {"songs": [{"cid": "s1", "name": "Song", "artistes": []}]}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "metadata.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "generatedAt": "now",
                        "albums": {
                            "a1": {
                                "msrName": "Album",
                                "prtsTitle": "Album",
                                "releaseDate": "2023-11-25",
                                "artists": ["塞壬唱片-MSR", "kiyo"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            downloader = Downloader(
                DownloaderConfig(root / "output", workers=1, metadata_snapshot=snapshot)
            )
            downloader._download_song = Mock()

            with (
                patch("monster_siren.downloader.MonsterSirenAPI", AlbumAPI),
                patch("monster_siren.downloader.is_valid_cover", return_value=True),
            ):
                downloader._download_album(
                    {"cid": "a1", "name": " Album ", "artistes": []}
                )

            kwargs = downloader._download_song.call_args.kwargs
            self.assertEqual(kwargs["album_name"], "Album")
            self.assertEqual(
                kwargs["album_dir"].name, album_directory_name("Album", "a1")
            )
            self.assertEqual(kwargs["album_artists"], ["塞壬唱片-MSR", "kiyo"])
            self.assertEqual(kwargs["song_artist_fallback"], ["塞壬唱片-MSR", "kiyo"])
            self.assertEqual(kwargs["release_date"], "2023-11-25")
            self.assertEqual(
                kwargs["prts_fingerprint"],
                downloader.metadata.album("a1").fingerprint,
            )
            self.assertTrue(kwargs["prts_album_artists"])
            state = json.loads(
                (root / "output" / "download_state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["albums"]["a1"]["name"], "Album")

    def test_prts_song_fallback_is_kept_when_msr_album_artist_exists(self) -> None:
        class AlbumAPI:
            def __enter__(self) -> AlbumAPI:
                return self

            def __exit__(self, *exc_info: object) -> None:
                pass

            def get_album_detail(self, cid: str) -> dict[str, object]:
                return {"songs": [{"cid": "s1", "name": "Song", "artistes": []}]}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "metadata.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "generatedAt": "now",
                        "albums": {
                            "0242": {
                                "msrName": "Album",
                                "prtsTitle": "Album",
                                "releaseDate": "2023-11-25",
                                "artists": ["塞壬唱片-MSR", "kiyo"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            downloader = Downloader(
                DownloaderConfig(root / "output", metadata_snapshot=snapshot)
            )
            downloader._download_song = Mock()

            with (
                patch("monster_siren.downloader.MonsterSirenAPI", AlbumAPI),
                patch("monster_siren.downloader.is_valid_cover", return_value=True),
            ):
                downloader._download_album(
                    {
                        "cid": "0242",
                        "name": "Album",
                        "artistes": ["塞壬唱片-MSR"],
                    }
                )

            kwargs = downloader._download_song.call_args.kwargs
            self.assertEqual(kwargs["album_artists"], ["塞壬唱片-MSR"])
            self.assertEqual(kwargs["song_artist_fallback"], ["塞壬唱片-MSR", "kiyo"])

    def test_album_cid_selects_only_the_matching_album(self) -> None:
        downloader = object.__new__(Downloader)
        downloader.config = DownloaderConfig(Path("output"), album_cid="a2")
        albums = [{"cid": "a1", "name": "First"}, {"cid": "a2", "name": "Second"}]

        self.assertEqual(downloader._filter_albums(albums), [albums[1]])

    def test_song_cid_lookup_returns_its_album(self) -> None:
        class CatalogAPI:
            def get_album_detail(self, cid: str) -> dict[str, object]:
                songs = {"a1": [{"cid": "s1"}], "a2": [{"cid": "s2"}]}
                return {"songs": songs[cid]}

        albums = [{"cid": "a1", "name": "First"}, {"cid": "a2", "name": "Second"}]

        self.assertEqual(
            Downloader._find_song_album(CatalogAPI(), albums, "s2"), albums[1]
        )

    def test_song_cid_run_downloads_only_the_target_song(self) -> None:
        class CatalogAPI:
            def __enter__(self) -> CatalogAPI:
                return self

            def __exit__(self, *exc_info: object) -> None:
                pass

            def get_albums(self) -> list[dict[str, object]]:
                return [
                    {"cid": "a1", "name": "First"},
                    {"cid": "a2", "name": "Second"},
                ]

            def get_album_detail(self, cid: str) -> dict[str, object]:
                songs = {"a1": [{"cid": "s1"}], "a2": [{"cid": "s2"}]}
                return {"songs": songs[cid]}

        downloader = object.__new__(Downloader)
        downloader.config = DownloaderConfig(Path("output"), song_cid="s2")
        downloader._download_album = Mock()

        with patch("monster_siren.downloader.MonsterSirenAPI", CatalogAPI):
            self.assertEqual(downloader.run(), 0)

        downloader._download_album.assert_called_once_with(
            {"cid": "a2", "name": "Second"}, "s2"
        )


if __name__ == "__main__":
    unittest.main()
