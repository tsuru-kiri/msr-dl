from __future__ import annotations

import argparse
import logging
from pathlib import Path

from monster_siren.downloader import Downloader, DownloaderConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Monster Siren albums with metadata and lyrics."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("./MonsterSiren"),
        help="Download directory (default: ./MonsterSiren)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of albums to process concurrently (default: 4)",
    )
    parser.add_argument(
        "--album",
        action="append",
        default=[],
        help="Only download albums whose name contains this text. Repeatable.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Redownload songs even when state says they are complete.",
    )
    parser.add_argument(
        "--no-lyrics",
        action="store_true",
        help="Do not download or embed lyrics.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    config = DownloaderConfig(
        output_dir=args.output,
        workers=max(1, args.workers),
        album_filters=tuple(args.album),
        force=args.force,
        download_lyrics=not args.no_lyrics,
    )

    downloader = Downloader(config)
    failures = downloader.run()

    if failures:
        logging.error("%d album(s) finished with errors.", failures)
        return 1

    logging.info("All requested albums completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
