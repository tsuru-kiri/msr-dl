from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from monster_siren.metadata import (
    DEFAULT_ALIASES_PATH,
    DEFAULT_SNAPSHOT_PATH,
    MetadataSnapshot,
    _fetch_remote_snapshot_data,
    load_aliases,
    load_metadata_snapshot,
    metadata_fingerprint,
    publish_snapshot,
)
from monster_siren.utils import normalize_album_name


class MetadataTests(unittest.TestCase):
    @staticmethod
    def _snapshot(generated_at: str, cid: str) -> dict[str, object]:
        artists = ("Artist",)
        return {
            "version": 2,
            "generatedAt": generated_at,
            "albums": {
                cid: {
                    "releaseDate": "2024-01-02",
                    "artists": list(artists),
                    "fingerprint": metadata_fingerprint(cid, "2024-01-02", artists),
                }
            },
        }

    def test_bundled_metadata_has_canonical_album_names(self) -> None:
        aliases = json.loads(DEFAULT_ALIASES_PATH.read_text(encoding="utf-8"))
        for record in aliases["albums"].values():
            self.assertNotEqual(
                normalize_album_name(record["msrName"]), record["prtsTitle"]
            )

        snapshot = json.loads(DEFAULT_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        for record in snapshot["albums"].values():
            self.assertEqual(record["msrName"], normalize_album_name(record["msrName"]))

    def test_existing_unmatched_record_is_retained_during_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "generatedAt": "old",
                        "albums": {
                            "old": {
                                "msrName": "Old",
                                "prtsTitle": "Old",
                                "releaseDate": "2020-01-01",
                                "artists": ["塞壬唱片-MSR"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            candidate = {
                "version": 1,
                "generatedAt": "new",
                "albums": {
                    "new": {
                        "msrName": "New",
                        "prtsTitle": "New",
                        "releaseDate": "2024-01-02",
                        "artists": ["塞壬唱片-MSR", "Singer"],
                    }
                },
            }

            result = publish_snapshot(
                path,
                candidate,
                unmatched=[("old", "Old"), ("missing", "Missing")],
            )

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(saved["albums"]), {"old", "new"})
            self.assertEqual(result.retained_unmatched, 1)
            self.assertEqual(result.new_unmatched, 1)

    def test_check_mode_does_not_change_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            original = '{"version": 1, "generatedAt": "old", "albums": {}}\n'
            path.write_text(original, encoding="utf-8")

            publish_snapshot(
                path,
                {"version": 1, "generatedAt": "new", "albums": {}},
                unmatched=[],
                check=True,
            )

            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_publish_does_not_write_when_only_generated_at_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            publish_snapshot(
                path,
                self._snapshot("2026-01-01T00:00:00+00:00", "a1"),
                unmatched=[],
            )
            original = path.read_bytes()

            publish_snapshot(
                path,
                self._snapshot("2026-01-02T00:00:00+00:00", "a1"),
                unmatched=[],
            )

            self.assertEqual(path.read_bytes(), original)

    def test_default_loader_uses_newer_remote_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundled_path = Path(directory) / "bundled.json"
            bundled_path.write_text(
                json.dumps(self._snapshot("2026-01-01T09:00:00+09:00", "old")),
                encoding="utf-8",
            )
            remote = self._snapshot("2026-01-01T00:00:01Z", "new")

            with (
                patch("monster_siren.metadata.DEFAULT_SNAPSHOT_PATH", bundled_path),
                patch(
                    "monster_siren.metadata._fetch_remote_snapshot_data",
                    return_value=remote,
                ),
            ):
                snapshot = load_metadata_snapshot()

            self.assertIsNotNone(snapshot.album("new"))
            self.assertIsNone(snapshot.album("old"))

    def test_default_loader_keeps_bundled_when_remote_is_not_newer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundled_path = Path(directory) / "bundled.json"
            bundled_path.write_text(
                json.dumps(self._snapshot("2026-01-02T00:00:00+00:00", "bundled")),
                encoding="utf-8",
            )
            remote = self._snapshot("2026-01-01T00:00:00+00:00", "remote")

            with (
                patch("monster_siren.metadata.DEFAULT_SNAPSHOT_PATH", bundled_path),
                patch(
                    "monster_siren.metadata._fetch_remote_snapshot_data",
                    return_value=remote,
                ),
            ):
                snapshot = load_metadata_snapshot()

            self.assertIsNotNone(snapshot.album("bundled"))
            self.assertIsNone(snapshot.album("remote"))

    def test_default_loader_falls_back_when_remote_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundled_path = Path(directory) / "bundled.json"
            bundled_path.write_text(
                json.dumps(self._snapshot("2026-01-01T00:00:00+00:00", "bundled")),
                encoding="utf-8",
            )

            with (
                patch("monster_siren.metadata.DEFAULT_SNAPSHOT_PATH", bundled_path),
                patch(
                    "monster_siren.metadata._fetch_remote_snapshot_data",
                    return_value={"version": 2, "generatedAt": "invalid", "albums": {}},
                ),
                self.assertLogs(level="WARNING"),
            ):
                snapshot = load_metadata_snapshot()

            self.assertIsNotNone(snapshot.album("bundled"))

    def test_explicit_snapshot_does_not_fetch_remote(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "explicit.json"
            path.write_text(
                json.dumps(self._snapshot("2026-01-01T00:00:00+00:00", "explicit")),
                encoding="utf-8",
            )

            with patch(
                "monster_siren.metadata._fetch_remote_snapshot_data"
            ) as fetch_remote:
                snapshot = load_metadata_snapshot(path)

            fetch_remote.assert_not_called()
            self.assertIsNotNone(snapshot.album("explicit"))

    def test_remote_snapshot_download_is_size_limited(self) -> None:
        response = Mock()
        response.headers = {}
        response.iter_content.return_value = [b"123456"]
        session = Mock()
        session.get.return_value = response

        with (
            patch("monster_siren.metadata.MAX_SNAPSHOT_BYTES", 5),
            self.assertRaisesRegex(ValueError, "exceeds"),
        ):
            _fetch_remote_snapshot_data(session=session)

        session.get.assert_called_once_with(
            "https://raw.githubusercontent.com/tsuru-kiri/msr-dl/refs/heads/main/"
            "monster_siren/data/prts-metadata.json",
            timeout=(10.0, 60.0),
            stream=True,
        )
        response.close.assert_called_once()

    def test_alias_file_is_validated_and_reduced_to_cid_title_map(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aliases.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "albums": {
                            "0248": {
                                "msrName": "MSR title",
                                "prtsTitle": "PRTS title",
                                "reason": "Different title",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(load_aliases(path), {"0248": "PRTS title"})

            path.write_text('{"version": 1, "albums": {"0248": {}}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "prtsTitle"):
                load_aliases(path)

    def test_snapshot_lookup_validates_records(self) -> None:
        snapshot = MetadataSnapshot.from_data(
            {
                "version": 1,
                "generatedAt": "now",
                "albums": {
                    "0242": {
                        "msrName": "Fleeting Wish",
                        "prtsTitle": "Fleeting Wish",
                        "releaseDate": "2023-11-25",
                        "artists": ["塞壬唱片-MSR", "kiyo"],
                    }
                },
            }
        )

        self.assertEqual(snapshot.album("0242").release_date, "2023-11-25")
        self.assertEqual(snapshot.album("0242").artists, ("塞壬唱片-MSR", "kiyo"))
        self.assertEqual(
            snapshot.album("0242").fingerprint,
            metadata_fingerprint("0242", "2023-11-25", ("塞壬唱片-MSR", "kiyo")),
        )
        self.assertIsNone(snapshot.album("missing"))

    def test_publish_writes_version_two_album_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            publish_snapshot(
                path,
                {
                    "version": 1,
                    "generatedAt": "now",
                    "albums": {
                        "0242": {
                            "msrName": "Fleeting Wish",
                            "prtsTitle": "Fleeting Wish",
                            "releaseDate": "2023-11-25",
                            "artists": ["塞壬唱片-MSR", "kiyo"],
                        }
                    },
                },
                unmatched=[],
            )

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["version"], 2)
            self.assertEqual(
                saved["albums"]["0242"]["fingerprint"],
                metadata_fingerprint("0242", "2023-11-25", ("塞壬唱片-MSR", "kiyo")),
            )

    def test_version_two_snapshot_rejects_a_stale_fingerprint(self) -> None:
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            MetadataSnapshot.from_data(
                {
                    "version": 2,
                    "generatedAt": "now",
                    "albums": {
                        "0242": {
                            "releaseDate": "2023-11-25",
                            "artists": ["塞壬唱片-MSR", "kiyo"],
                            "fingerprint": "sha256:stale",
                        }
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
