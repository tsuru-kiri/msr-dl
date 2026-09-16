from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from monster_siren.metadata import DEFAULT_ALIASES_PATH, DEFAULT_SNAPSHOT_PATH
from monster_siren.prts import update_metadata_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Update the bundled PRTS metadata.")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    result = update_metadata_snapshot(
        DEFAULT_SNAPSHOT_PATH,
        DEFAULT_ALIASES_PATH,
        check=False,
    )
    report = {
        "albums": result.albums,
        "unmatched": [{"cid": cid, "name": name} for cid, name in result.unmatched],
        "publish": asdict(result.publish),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
