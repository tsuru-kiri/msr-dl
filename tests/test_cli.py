from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import main


class FakeAPI:
    def __init__(self) -> None:
        self.album_requests: list[str] = []

    def __enter__(self) -> FakeAPI:
        return self

    def __exit__(self, *exc_info: object) -> None:
        pass

    def get_albums(self) -> list[dict[str, object]]:
        return [{"cid": "a1", "name": "앨범", "artistes": ["Artist"]}]

    def get_album_detail(self, cid: str) -> dict[str, object]:
        self.album_requests.append(cid)
        return {
            "songs": [
                {"cid": "s1", "name": "노래", "artistes": ["Singer"]},
            ]
        }


class CLITests(unittest.TestCase):
    def test_legacy_arguments_default_to_download(self) -> None:
        args = main.parse_args(["--album", "Ambience"])

        self.assertEqual(args.command, "download")
        self.assertEqual(args.album, ["Ambience"])

    def test_version_prints_without_selecting_a_command(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main.parse_args(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue(), f"msr-dl {main.VERSION}\n")

    def test_download_cid_targets_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            main.parse_args(["download", "--album-cid", "a1", "--song-cid", "s1"])

    def test_metadata_update_accepts_configurable_paths_and_check_mode(self) -> None:
        args = main.parse_args(
            [
                "metadata",
                "update",
                "--snapshot",
                "/tmp/custom.json",
                "--aliases",
                "/tmp/aliases.json",
                "--check",
            ]
        )

        self.assertEqual(args.command, "metadata")
        self.assertEqual(args.metadata_command, "update")
        self.assertEqual(args.snapshot, Path("/tmp/custom.json"))
        self.assertEqual(args.aliases, Path("/tmp/aliases.json"))
        self.assertTrue(args.check)

    def test_download_accepts_metadata_snapshot(self) -> None:
        args = main.parse_args(["download", "--metadata-snapshot", "/tmp/custom.json"])

        self.assertEqual(args.metadata_snapshot, Path("/tmp/custom.json"))

    def test_download_command_logs_summary(self) -> None:
        report = Mock(
            albums=2,
            songs=3,
            downloaded=1,
            skipped=1,
            failed=1,
            failed_albums=1,
        )

        with (
            patch("sys.argv", ["msr-dl", "download"]),
            patch("main.Downloader") as downloader,
            self.assertLogs(level="INFO") as logs,
        ):
            downloader.return_value.run.return_value = report
            result = main.main()

        self.assertEqual(result, 1)
        self.assertTrue(
            any(
                "Albums: 2 | Songs: 3 | Downloaded: 1 | Skipped: 1 | Failed: 1" in line
                for line in logs.output
            )
        )

    def test_metadata_update_command_runs_without_downloader(self) -> None:
        report = Mock()
        report.albums = 1
        report.unmatched = []
        report.publish.added = 1
        report.publish.updated = 0
        report.publish.unchanged = 0
        report.publish.retained_unmatched = 0
        report.publish.new_unmatched = 0

        with (
            patch(
                "sys.argv",
                ["msr-dl", "metadata", "update", "--snapshot", "/tmp/meta.json"],
            ),
            patch("main.update_metadata_snapshot", return_value=report) as update,
        ):
            result = main.main()

        self.assertEqual(result, 0)
        update.assert_called_once_with(
            Path("/tmp/meta.json"), main.DEFAULT_ALIASES_PATH, check=False
        )

    def test_metadata_apply_accepts_targets_all_and_force(self) -> None:
        args = main.parse_args(
            [
                "metadata",
                "apply",
                "--output",
                "/tmp/music",
                "--snapshot",
                "/tmp/meta.json",
                "--song-cid",
                "s1",
                "--all",
                "--force",
            ]
        )

        self.assertEqual(args.metadata_command, "apply")
        self.assertEqual(args.output, Path("/tmp/music"))
        self.assertEqual(args.snapshot, Path("/tmp/meta.json"))
        self.assertEqual(args.song_cid, "s1")
        self.assertTrue(args.apply_all)
        self.assertTrue(args.force)

    def test_metadata_apply_targets_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            main.parse_args(
                ["metadata", "apply", "--album-cid", "a1", "--song-cid", "s1"]
            )

    def test_metadata_apply_command_runs_without_downloader(self) -> None:
        report = Mock(failed=0)
        report.albums = 1
        report.songs = 1
        report.msr_applied = 0
        report.prts_applied = 0
        report.prts_unchanged = 0
        report.prts_unavailable = 1
        report.missing = 0

        with (
            patch(
                "sys.argv",
                [
                    "msr-dl",
                    "metadata",
                    "apply",
                    "--output",
                    "/tmp/music",
                    "--snapshot",
                    "/tmp/meta.json",
                ],
            ),
            patch("main.MetadataApplier") as applier,
            self.assertLogs(level="INFO") as logs,
        ):
            applier.return_value.run.return_value = report
            result = main.main()

        self.assertEqual(result, 0)
        self.assertTrue(any("PRTS unavailable: 1" in line for line in logs.output))
        applier.assert_called_once_with(
            main.MetadataApplyConfig(
                output_dir=Path("/tmp/music"),
                metadata_snapshot=Path("/tmp/meta.json"),
            )
        )

    def test_list_albums_prints_catalog_without_downloader(self) -> None:
        output = io.StringIO()
        with patch("main.MonsterSirenAPI", FakeAPI), redirect_stdout(output):
            result = main.list_catalog(None)

        self.assertEqual(result, 0)
        lines = output.getvalue().splitlines()
        self.assertEqual(lines[0], "CID | ALBUM NAME | ARTISTS")
        self.assertEqual(lines[1], "----+------------+--------")
        self.assertEqual(lines[2].split("|")[0].strip(), "a1")

    def test_list_albums_normalizes_album_names(self) -> None:
        class SpacedAlbumAPI(FakeAPI):
            def get_albums(self) -> list[dict[str, object]]:
                return [{"cid": "a1", "name": " 앨범 ", "artistes": ["Artist"]}]

        with (
            patch("main.MonsterSirenAPI", SpacedAlbumAPI),
            patch("main._format_table", return_value="") as format_table,
            redirect_stdout(io.StringIO()),
        ):
            result = main.list_catalog(None)

        self.assertEqual(result, 0)
        self.assertEqual(format_table.call_args.args[1][0][1], "앨범")

    def test_list_album_songs_prints_tracks(self) -> None:
        output = io.StringIO()
        with patch("main.MonsterSirenAPI", FakeAPI), redirect_stdout(output):
            result = main.list_catalog("a1")

        self.assertEqual(result, 0)
        lines = output.getvalue().splitlines()
        self.assertEqual(lines[0], "TRACK | CID | SONG NAME | ARTISTS")
        self.assertEqual(lines[1], "------+-----+-----------+--------")
        self.assertEqual(lines[2].split("|")[2].strip(), "노래")

    def test_table_cells_align_by_terminal_display_width(self) -> None:
        table = main._format_table(
            ("NAME", "ARTIST"), [("ASCII", "가수"), ("한글", "Singer")]
        )

        lines = table.splitlines()
        widths = [
            [main._display_width(cell) for cell in line.split("|")]
            for line in (lines[0], lines[2], lines[3])
        ]
        self.assertEqual(widths[0], widths[1])
        self.assertEqual(widths[0], widths[2])
