from __future__ import annotations

import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from monster_siren.downloader import Downloader, DownloaderConfig
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


if __name__ == "__main__":
    unittest.main()
