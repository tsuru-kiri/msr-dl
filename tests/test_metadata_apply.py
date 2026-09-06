from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from monster_siren.metadata import MetadataSnapshot
from monster_siren.metadata_apply import MetadataApplier, MetadataApplyConfig
from monster_siren.state import DownloadState


class FakeAPI:
    def __enter__(self) -> FakeAPI:
        return self

    def __exit__(self, *exc_info: object) -> None:
        pass

    def get_albums(self) -> list[dict[str, object]]:
        return [{"cid": "a1", "name": "Album", "artistes": []}]

    def get_album_detail(self, cid: str) -> dict[str, object]:
        return {"songs": [{"cid": "s1", "name": "Song", "artistes": []}]}

    def get_song_detail(self, cid: str) -> dict[str, object]:
        return {"artists": []}


class MetadataApplyTests(unittest.TestCase):
    def _fixture(
        self, root: Path, *, fingerprint: str | None = None
    ) -> tuple[Path, str]:
        album = root / "Album [a1]"
        album.mkdir()
        audio = album / "01 - Song [s1].flac"
        audio.write_bytes(b"audio")
        Image.new("RGB", (2, 2), "black").save(album / "cover.png")
        snapshot_data = {
            "version": 1,
            "albums": {
                "a1": {
                    "releaseDate": "2024-01-02",
                    "artists": ["PRTS Artist"],
                }
            },
        }
        snapshot = MetadataSnapshot.from_data(snapshot_data)
        snapshot_path = root / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot_data), encoding="utf-8")
        state = DownloadState(root / "download_state.json")
        state.mark_song(
            "a1",
            "Album",
            "s1",
            "Song",
            "complete",
            output_path=audio,
            lyrics_complete=False,
            prts_fingerprint=fingerprint,
        )
        return snapshot_path, snapshot.album("a1").fingerprint

    def test_default_apply_skips_an_unchanged_prts_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path, fingerprint = self._fixture(root)
            DownloadState(root / "download_state.json").mark_metadata_applied(
                "a1",
                "s1",
                root / "Album [a1]" / "01 - Song [s1].flac",
                fingerprint,
                prts_album_artists=True,
                prts_song_artists=True,
            )

            with (
                patch("monster_siren.metadata_apply.ensure_ffmpeg"),
                patch("monster_siren.metadata_apply.MonsterSirenAPI", FakeAPI),
                patch("monster_siren.metadata_apply.apply_prts_metadata") as apply_prts,
            ):
                report = MetadataApplier(
                    MetadataApplyConfig(root, metadata_snapshot=snapshot_path)
                ).run()

            apply_prts.assert_not_called()
            self.assertEqual(report.prts_unchanged, 1)
            self.assertEqual(report.prts_applied, 0)

    def test_default_apply_updates_changed_prts_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path, fingerprint = self._fixture(root, fingerprint="sha256:old")

            with (
                patch("monster_siren.metadata_apply.ensure_ffmpeg"),
                patch("monster_siren.metadata_apply.MonsterSirenAPI", FakeAPI),
                patch("monster_siren.metadata_apply.validate_audio"),
                patch("monster_siren.metadata_apply.apply_prts_metadata") as apply_prts,
            ):
                report = MetadataApplier(
                    MetadataApplyConfig(root, metadata_snapshot=snapshot_path)
                ).run()

            apply_prts.assert_called_once()
            self.assertEqual(report.prts_applied, 1)
            self.assertEqual(
                DownloadState(root / "download_state.json").song_metadata_fingerprint(
                    "a1", "s1"
                ),
                fingerprint,
            )

    def test_apply_logs_song_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path, _ = self._fixture(root)

            with (
                patch("monster_siren.metadata_apply.ensure_ffmpeg"),
                patch("monster_siren.metadata_apply.MonsterSirenAPI", FakeAPI),
                patch("monster_siren.metadata_apply.validate_audio"),
                patch("monster_siren.metadata_apply.apply_prts_metadata"),
                self.assertLogs(level="INFO") as logs,
            ):
                MetadataApplier(
                    MetadataApplyConfig(root, metadata_snapshot=snapshot_path)
                ).run()

            self.assertTrue(
                any(
                    "Applying metadata (1/1): Album / Song" in message
                    for message in logs.output
                )
            )

    def test_all_preserves_unchanged_prts_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path, fingerprint = self._fixture(root)
            DownloadState(root / "download_state.json").mark_metadata_applied(
                "a1",
                "s1",
                root / "Album [a1]" / "01 - Song [s1].flac",
                fingerprint,
                prts_album_artists=True,
                prts_song_artists=True,
            )

            with (
                patch("monster_siren.metadata_apply.ensure_ffmpeg"),
                patch("monster_siren.metadata_apply.MonsterSirenAPI", FakeAPI),
                patch("monster_siren.metadata_apply.validate_audio"),
                patch("monster_siren.metadata_apply.write_metadata") as write,
            ):
                report = MetadataApplier(
                    MetadataApplyConfig(
                        root, metadata_snapshot=snapshot_path, apply_all=True
                    )
                ).run()

            self.assertTrue(write.call_args.kwargs["preserve_date"])
            self.assertIsNone(write.call_args.kwargs["album_artists"])
            self.assertIsNone(write.call_args.kwargs["artists"])
            self.assertEqual(report.msr_applied, 1)
            self.assertEqual(report.prts_unchanged, 1)

    def test_all_clears_missing_msr_artists_that_were_not_prts_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path, fingerprint = self._fixture(root)
            DownloadState(root / "download_state.json").mark_metadata_applied(
                "a1",
                "s1",
                root / "Album [a1]" / "01 - Song [s1].flac",
                fingerprint,
                prts_album_artists=False,
                prts_song_artists=False,
            )

            with (
                patch("monster_siren.metadata_apply.ensure_ffmpeg"),
                patch("monster_siren.metadata_apply.MonsterSirenAPI", FakeAPI),
                patch("monster_siren.metadata_apply.validate_audio"),
                patch("monster_siren.metadata_apply.write_metadata") as write,
            ):
                MetadataApplier(
                    MetadataApplyConfig(
                        root, metadata_snapshot=snapshot_path, apply_all=True
                    )
                ).run()

            self.assertEqual(write.call_args.kwargs["album_artists"], [])
            self.assertEqual(write.call_args.kwargs["artists"], [])

    def test_prts_apply_replaces_old_fallback_when_msr_artist_was_added(self) -> None:
        class ArtistAPI(FakeAPI):
            def get_albums(self) -> list[dict[str, object]]:
                return [{"cid": "a1", "name": "Album", "artistes": ["MSR Album"]}]

            def get_album_detail(self, cid: str) -> dict[str, object]:
                return {
                    "songs": [{"cid": "s1", "name": "Song", "artistes": ["MSR Song"]}]
                }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path, fingerprint = self._fixture(root)
            state = DownloadState(root / "download_state.json")
            state.mark_metadata_applied(
                "a1",
                "s1",
                root / "Album [a1]" / "01 - Song [s1].flac",
                "sha256:old",
                prts_album_artists=True,
                prts_song_artists=True,
            )

            with (
                patch("monster_siren.metadata_apply.ensure_ffmpeg"),
                patch("monster_siren.metadata_apply.MonsterSirenAPI", ArtistAPI),
                patch("monster_siren.metadata_apply.validate_audio"),
                patch("monster_siren.metadata_apply.apply_prts_metadata") as apply_prts,
            ):
                MetadataApplier(
                    MetadataApplyConfig(root, metadata_snapshot=snapshot_path)
                ).run()

            self.assertEqual(
                apply_prts.call_args.kwargs["album_artists"], ["MSR Album"]
            )
            self.assertEqual(apply_prts.call_args.kwargs["artists"], ["MSR Song"])
            updated = DownloadState(root / "download_state.json").completed_songs()[0]
            self.assertEqual(updated.prts_fingerprint, fingerprint)
            self.assertFalse(updated.prts_album_artists)
            self.assertFalse(updated.prts_song_artists)

    def test_all_force_reapplies_prts_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path, fingerprint = self._fixture(root)
            DownloadState(root / "download_state.json").mark_metadata_applied(
                "a1", "s1", root / "Album [a1]" / "01 - Song [s1].flac", fingerprint
            )

            with (
                patch("monster_siren.metadata_apply.ensure_ffmpeg"),
                patch("monster_siren.metadata_apply.MonsterSirenAPI", FakeAPI),
                patch("monster_siren.metadata_apply.validate_audio"),
                patch("monster_siren.metadata_apply.write_metadata") as write,
            ):
                report = MetadataApplier(
                    MetadataApplyConfig(
                        root,
                        metadata_snapshot=snapshot_path,
                        apply_all=True,
                        force=True,
                    )
                ).run()

            self.assertFalse(write.call_args.kwargs["preserve_date"])
            self.assertEqual(write.call_args.kwargs["album_artists"], ["PRTS Artist"])
            self.assertEqual(write.call_args.kwargs["artists"], ["PRTS Artist"])
            self.assertEqual(report.msr_applied, 1)
            self.assertEqual(report.prts_applied, 1)

    def test_explicit_song_target_must_be_downloaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path, _ = self._fixture(root)
            (root / "download_state.json").unlink()

            with (
                patch("monster_siren.metadata_apply.ensure_ffmpeg"),
                patch("monster_siren.metadata_apply.MonsterSirenAPI", FakeAPI),
            ):
                applier = MetadataApplier(
                    MetadataApplyConfig(
                        root, metadata_snapshot=snapshot_path, song_cid="s1"
                    )
                )
                with self.assertRaisesRegex(ValueError, "not downloaded"):
                    applier.run()

    def test_explicit_album_target_must_have_a_downloaded_song(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path, _ = self._fixture(root)
            (root / "download_state.json").unlink()

            with (
                patch("monster_siren.metadata_apply.ensure_ffmpeg"),
                patch("monster_siren.metadata_apply.MonsterSirenAPI", FakeAPI),
            ):
                applier = MetadataApplier(
                    MetadataApplyConfig(
                        root, metadata_snapshot=snapshot_path, album_cid="a1"
                    )
                )
                with self.assertRaisesRegex(ValueError, "not downloaded"):
                    applier.run()

    def test_partial_album_reports_songs_that_are_not_downloaded(self) -> None:
        class PartialAPI(FakeAPI):
            def get_album_detail(self, cid: str) -> dict[str, object]:
                return {
                    "songs": [
                        {"cid": "s1", "name": "Song", "artistes": []},
                        {"cid": "s2", "name": "Missing", "artistes": []},
                    ]
                }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path, fingerprint = self._fixture(root)
            DownloadState(root / "download_state.json").mark_metadata_applied(
                "a1", "s1", root / "Album [a1]" / "01 - Song [s1].flac", fingerprint
            )

            with (
                patch("monster_siren.metadata_apply.ensure_ffmpeg"),
                patch("monster_siren.metadata_apply.MonsterSirenAPI", PartialAPI),
            ):
                report = MetadataApplier(
                    MetadataApplyConfig(
                        root, metadata_snapshot=snapshot_path, album_cid="a1"
                    )
                ).run()

            self.assertEqual(report.songs, 1)
            self.assertEqual(report.missing, 1)

    def test_writer_failure_preserves_the_original_audio_and_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path, _ = self._fixture(root, fingerprint="sha256:old")
            audio = root / "Album [a1]" / "01 - Song [s1].flac"
            original = audio.read_bytes()

            with (
                patch("monster_siren.metadata_apply.ensure_ffmpeg"),
                patch("monster_siren.metadata_apply.MonsterSirenAPI", FakeAPI),
                patch(
                    "monster_siren.metadata_apply.apply_prts_metadata",
                    side_effect=RuntimeError("tag failure"),
                ),
            ):
                report = MetadataApplier(
                    MetadataApplyConfig(root, metadata_snapshot=snapshot_path)
                ).run()

            self.assertEqual(report.failed, 1)
            self.assertEqual(audio.read_bytes(), original)
            self.assertEqual(
                DownloadState(root / "download_state.json").song_metadata_fingerprint(
                    "a1", "s1"
                ),
                "sha256:old",
            )

    def test_album_without_prts_metadata_is_not_reported_as_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path, _ = self._fixture(root)
            snapshot_path.write_text(
                json.dumps({"version": 1, "albums": {}}), encoding="utf-8"
            )

            with (
                patch("monster_siren.metadata_apply.ensure_ffmpeg"),
                patch("monster_siren.metadata_apply.MonsterSirenAPI", FakeAPI),
            ):
                report = MetadataApplier(
                    MetadataApplyConfig(root, metadata_snapshot=snapshot_path)
                ).run()

            self.assertEqual(report.prts_applied, 0)
            self.assertEqual(report.prts_unchanged, 0)
            self.assertEqual(report.prts_unavailable, 1)

    def test_all_reports_album_without_prts_metadata_as_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path, _ = self._fixture(root)
            snapshot_path.write_text(
                json.dumps({"version": 1, "albums": {}}), encoding="utf-8"
            )

            with (
                patch("monster_siren.metadata_apply.ensure_ffmpeg"),
                patch("monster_siren.metadata_apply.MonsterSirenAPI", FakeAPI),
                patch("monster_siren.metadata_apply.validate_audio"),
                patch("monster_siren.metadata_apply.write_metadata"),
            ):
                report = MetadataApplier(
                    MetadataApplyConfig(
                        root,
                        metadata_snapshot=snapshot_path,
                        apply_all=True,
                    )
                ).run()

            self.assertEqual(report.msr_applied, 1)
            self.assertEqual(report.prts_unchanged, 0)
            self.assertEqual(report.prts_unavailable, 1)


if __name__ == "__main__":
    unittest.main()
