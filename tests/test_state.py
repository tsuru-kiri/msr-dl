from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from monster_siren.state import DownloadState


class StateTests(unittest.TestCase):
    def test_completion_requires_the_expected_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            album = root / "Album [a1]"
            album.mkdir()
            stem = album / "01 - Name.with.dot [s1]"
            audio = Path(f"{stem}.mp3")
            audio.write_bytes(b"audio")

            state = DownloadState(root / "download_state.json")
            state.mark_song(
                "a1",
                "Album",
                "s1",
                "Name.with.dot",
                "complete",
                output_path=audio,
                lyrics_complete=True,
            )

            self.assertTrue(
                state.is_song_complete(
                    "a1", "s1", expected_stem=stem, require_lyrics=True
                )
            )
            audio.write_bytes(b"truncated")
            self.assertFalse(
                state.is_song_complete(
                    "a1", "s1", expected_stem=stem, require_lyrics=False
                )
            )
            audio.unlink()
            self.assertFalse(
                state.is_song_complete(
                    "a1", "s1", expected_stem=stem, require_lyrics=False
                )
            )

    def test_version_one_completion_without_output_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "download_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "albums": {"a1": {"songs": {"s1": {"status": "complete"}}}},
                    }
                ),
                encoding="utf-8",
            )

            state = DownloadState(state_path)
            self.assertFalse(
                state.is_song_complete(
                    "a1",
                    "s1",
                    expected_stem=root / "Album" / "Song",
                    require_lyrics=False,
                )
            )

    def test_corrupt_state_is_backed_up(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "download_state.json"
            state_path.write_text("not json", encoding="utf-8")

            DownloadState(state_path)

            self.assertFalse(state_path.exists())
            self.assertEqual(len(list(root.glob("download_state.json.broken-*"))), 1)


if __name__ == "__main__":
    unittest.main()
