from __future__ import annotations

import argparse
import logging
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from unicodedata import combining, east_asian_width

from monster_siren import __version__
from monster_siren.api import MonsterSirenAPI
from monster_siren.downloader import Downloader, DownloaderConfig
from monster_siren.metadata import DEFAULT_ALIASES_PATH
from monster_siren.metadata_apply import MetadataApplier, MetadataApplyConfig
from monster_siren.prts import update_metadata_snapshot
from monster_siren.utils import normalize_album_name

try:
    VERSION = version("msr-dl")
except PackageNotFoundError:
    VERSION = __version__


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="msr-dl",
        description="Download Monster Siren albums with metadata and lyrics.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command")

    download = subparsers.add_parser("download", help="Download albums or songs.")
    download.add_argument(
        "--output",
        type=Path,
        default=Path("./MonsterSiren"),
        help="Download directory (default: ./MonsterSiren)",
    )
    download.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of albums to process concurrently (default: 4)",
    )
    targets = download.add_mutually_exclusive_group()
    targets.add_argument(
        "--album",
        action="append",
        default=[],
        help="Only download albums whose name contains this text. Repeatable.",
    )
    targets.add_argument("--album-cid", help="Download the album with this CID.")
    targets.add_argument("--song-cid", help="Download the song with this CID.")
    download.add_argument(
        "--force",
        action="store_true",
        help="Redownload songs even when state says they are complete.",
    )
    download.add_argument(
        "--no-lyrics",
        action="store_true",
        help="Do not download or embed lyrics.",
    )
    download.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    download.add_argument(
        "--metadata-snapshot",
        type=Path,
        help="Use this PRTS metadata snapshot instead of the bundled snapshot.",
    )

    listing = subparsers.add_parser("list", help="List albums or an album's songs.")
    listing.add_argument("--album-cid", help="List songs in the album with this CID.")
    listing.add_argument("--verbose", action="store_true", help="Enable debug logging.")

    metadata = subparsers.add_parser("metadata", help="Manage PRTS metadata.")
    metadata_commands = metadata.add_subparsers(dest="metadata_command", required=True)
    update = metadata_commands.add_parser("update", help="Update a PRTS snapshot.")
    update.add_argument("--snapshot", type=Path, required=True)
    update.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES_PATH)
    update.add_argument("--check", action="store_true")
    update.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    apply = metadata_commands.add_parser(
        "apply", help="Apply updated metadata to downloaded songs."
    )
    apply.add_argument(
        "--output",
        type=Path,
        default=Path("./MonsterSiren"),
        help="Download directory (default: ./MonsterSiren)",
    )
    apply.add_argument(
        "--snapshot",
        type=Path,
        help="Use this PRTS metadata snapshot instead of the bundled snapshot.",
    )
    apply_targets = apply.add_mutually_exclusive_group()
    apply_targets.add_argument(
        "--album",
        action="append",
        default=[],
        help="Only update albums whose name contains this text. Repeatable.",
    )
    apply_targets.add_argument("--album-cid", help="Update the album with this CID.")
    apply_targets.add_argument("--song-cid", help="Update the song with this CID.")
    apply.add_argument(
        "--all",
        action="store_true",
        dest="apply_all",
        help="Reapply all Monster Siren metadata and local artwork and lyrics.",
    )
    apply.add_argument(
        "--force",
        action="store_true",
        help="Reapply PRTS metadata even when its fingerprint is unchanged.",
    )
    apply.add_argument("--verbose", action="store_true", help="Enable debug logging.")

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in {
        "download",
        "list",
        "metadata",
        "-h",
        "--help",
        "--version",
    }:
        arguments.insert(0, "download")
    return parser.parse_args(arguments)


def list_catalog(album_cid: str | None) -> int:
    with MonsterSirenAPI() as api:
        if album_cid is None:
            rows = [
                (
                    album["cid"],
                    normalize_album_name(album["name"]),
                    ", ".join(Downloader._string_list(album.get("artistes"))) or "-",
                )
                for album in api.get_albums()
            ]
            print(_format_table(("CID", "ALBUM NAME", "ARTISTS"), rows))
            return 0

        detail = api.get_album_detail(album_cid)
        rows = [
            (
                f"{number:02d}",
                song["cid"],
                song["name"],
                ", ".join(Downloader._string_list(song.get("artistes"))) or "-",
            )
            for number, song in enumerate(detail["songs"], start=1)
        ]
        print(_format_table(("TRACK", "CID", "SONG NAME", "ARTISTS"), rows))
    return 0


def _display_width(value: str) -> int:
    width = 0
    for character in value:
        if not combining(character):
            width += 2 if east_asian_width(character) in {"F", "W"} else 1
    return width


def _format_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    widths = [
        max(_display_width(cell) for cell in column)
        for column in zip(headers, *rows, strict=True)
    ]

    def format_row(row: tuple[str, ...]) -> str:
        return " | ".join(
            f"{cell}{' ' * (width - _display_width(cell))}"
            for cell, width in zip(row, widths, strict=True)
        )

    separator = "-+-".join("-" * width for width in widths)
    return "\n".join(
        (format_row(headers), separator, *(format_row(row) for row in rows))
    )


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    if args.command == "list":
        try:
            return list_catalog(args.album_cid)
        except Exception:
            logging.exception("Could not retrieve catalog information.")
            return 1

    if args.command == "metadata":
        if args.metadata_command == "apply":
            config = MetadataApplyConfig(
                output_dir=args.output,
                metadata_snapshot=args.snapshot,
                album_filters=tuple(args.album),
                album_cid=args.album_cid,
                song_cid=args.song_cid,
                apply_all=args.apply_all,
                force=args.force,
            )
            try:
                report = MetadataApplier(config).run()
            except KeyboardInterrupt:
                logging.warning("Interrupted by user.")
                return 130
            except Exception:
                logging.exception("Could not apply metadata to downloaded songs.")
                return 1
            logging.info(
                "Albums: %d | Songs: %d | MSR applied: %d | PRTS applied: %d | "
                "PRTS unchanged: %d | PRTS unavailable: %d | Missing: %d | "
                "Failed: %d",
                report.albums,
                report.songs,
                report.msr_applied,
                report.prts_applied,
                report.prts_unchanged,
                report.prts_unavailable,
                report.missing,
                report.failed,
            )
            return 1 if report.failed else 0

        try:
            report = update_metadata_snapshot(
                args.snapshot, args.aliases, check=args.check
            )
        except Exception:
            logging.exception("Could not update the PRTS metadata snapshot.")
            return 1
        for cid, name in report.unmatched:
            logging.warning("Unmatched album: %s | %s", cid, name)
        result = report.publish
        logging.info(
            "Albums: %d | Added: %d | Updated: %d | Unchanged: %d | "
            "Retained unmatched: %d | New unmatched: %d",
            report.albums,
            result.added,
            result.updated,
            result.unchanged,
            result.retained_unmatched,
            result.new_unmatched,
        )
        return 0

    config = DownloaderConfig(
        output_dir=args.output,
        workers=max(1, args.workers),
        album_filters=tuple(args.album),
        album_cid=args.album_cid,
        song_cid=args.song_cid,
        force=args.force,
        download_lyrics=not args.no_lyrics,
        metadata_snapshot=args.metadata_snapshot,
    )

    try:
        downloader = Downloader(config)
        failures = downloader.run()
    except KeyboardInterrupt:
        logging.warning("Interrupted by user.")
        return 130
    except Exception:
        logging.exception("Downloader failed before all albums could be processed.")
        return 1

    if failures:
        logging.error("%d album(s) finished with errors.", failures)
        return 1

    logging.info("All requested albums completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
