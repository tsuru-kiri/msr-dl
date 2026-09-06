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

    def test_metadata_update_preserves_song_record_and_updates_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            album = root / "Album [a1]"
            album.mkdir()
            audio = album / "01 - Song [s1].flac"
            lyric = album / "01 - Song [s1].lrc"
            audio.write_bytes(b"old")
            lyric.write_text("[00:00.00]lyric", encoding="utf-8")
            state_path = root / "download_state.json"
            state = DownloadState(state_path)
            state.mark_song(
                "a1",
                "Album",
                "s1",
                "Song",
                "complete",
                output_path=audio,
                lyric_path=lyric,
                lyrics_complete=True,
            )

            audio.write_bytes(b"new metadata")
            state.mark_metadata_applied(
                "a1",
                "s1",
                audio,
                "sha256:new",
                prts_album_artists=True,
                prts_song_artists=False,
            )

            saved = json.loads(state_path.read_text(encoding="utf-8"))
            song = saved["albums"]["a1"]["songs"]["s1"]
            self.assertEqual(saved["version"], 3)
            self.assertEqual(song["output"], "Album [a1]/01 - Song [s1].flac")
            self.assertEqual(song["lyrics"], "Album [a1]/01 - Song [s1].lrc")
            self.assertTrue(song["lyrics_complete"])
            self.assertEqual(song["size"], len(b"new metadata"))
            self.assertEqual(song["prtsMetadataFingerprint"], "sha256:new")
            self.assertTrue(song["prtsAlbumArtists"])
            self.assertFalse(song["prtsSongArtists"])
            self.assertEqual(state.song_metadata_fingerprint("a1", "s1"), "sha256:new")

    def test_completed_songs_include_safe_state_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            album = root / "Album [a1]"
            album.mkdir()
            audio = album / "01 - Song [s1].mp3"
            audio.write_bytes(b"audio")
            state = DownloadState(root / "download_state.json")
            state.mark_song(
                "a1",
                "Album",
                "s1",
                "Song",
                "complete",
                output_path=audio,
                lyrics_complete=False,
            )

            songs = state.completed_songs()

            self.assertEqual(len(songs), 1)
            self.assertEqual(songs[0].album_cid, "a1")
            self.assertEqual(songs[0].song_cid, "s1")
            self.assertEqual(songs[0].output_path, audio.resolve())
            self.assertIsNone(songs[0].lyric_path)

    def test_completed_songs_exclude_records_without_an_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "download_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "albums": {
                            "a1": {
                                "songs": {"s1": {"name": "Song", "status": "complete"}}
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(DownloadState(state_path).completed_songs(), [])


if __name__ == "__main__":
    unittest.main()
