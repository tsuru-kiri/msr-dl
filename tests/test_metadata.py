from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from monster_siren.metadata import (
    MetadataSnapshot,
    load_aliases,
    publish_snapshot,
)


class MetadataTests(unittest.TestCase):
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
        self.assertIsNone(snapshot.album("missing"))


if __name__ == "__main__":
    unittest.main()
