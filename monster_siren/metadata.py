from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

DEFAULT_ALIASES_PATH = Path(__file__).with_name("data") / "prts-aliases.json"
DEFAULT_SNAPSHOT_PATH = Path(__file__).with_name("data") / "prts-metadata.json"


@dataclass(frozen=True)
class AlbumMetadata:
    release_date: str
    artists: tuple[str, ...]
    fingerprint: str = ""


@dataclass(frozen=True)
class PublishResult:
    added: int
    updated: int
    unchanged: int
    retained_unmatched: int
    new_unmatched: int


class MetadataSnapshot:
    def __init__(self, albums: dict[str, AlbumMetadata]) -> None:
        self._albums = albums

    @classmethod
    def from_path(cls, path: Path) -> MetadataSnapshot:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not load metadata snapshot {path}: {exc}") from exc
        return cls.from_data(data)

    @classmethod
    def from_data(cls, data: object) -> MetadataSnapshot:
        root = _root(data, "metadata snapshot")
        version = root.get("version")
        if version not in {1, 2} or not isinstance(root.get("albums"), dict):
            raise ValueError(
                "Metadata snapshot must have version 1 or 2 and an albums object"
            )
        albums: dict[str, AlbumMetadata] = {}
        for cid, value in root["albums"].items():
            if not isinstance(cid, str):
                raise ValueError("Metadata snapshot album CID must be a string")
            record = _root(value, f"metadata snapshot album {cid}")
            release_date = record.get("releaseDate")
            artists = record.get("artists")
            if not isinstance(release_date, str):
                raise ValueError(f"Metadata snapshot album {cid} has no releaseDate")
            try:
                date.fromisoformat(release_date)
            except ValueError as exc:
                raise ValueError(
                    f"Metadata snapshot album {cid} has an invalid releaseDate"
                ) from exc
            if not isinstance(artists, list) or not all(
                isinstance(artist, str) and artist for artist in artists
            ):
                raise ValueError(f"Metadata snapshot album {cid} has invalid artists")
            fingerprint = metadata_fingerprint(cid, release_date, tuple(artists))
            if version == 2 and record.get("fingerprint") != fingerprint:
                raise ValueError(
                    f"Metadata snapshot album {cid} has an invalid fingerprint"
                )
            albums[cid] = AlbumMetadata(release_date, tuple(artists), fingerprint)
        return cls(albums)

    def album(self, cid: str) -> AlbumMetadata | None:
        return self._albums.get(cid)


def _root(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Invalid {label}")
    return value


def metadata_fingerprint(cid: str, release_date: str, artists: tuple[str, ...]) -> str:
    canonical = json.dumps(
        {"artists": list(artists), "cid": cid, "releaseDate": release_date},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _normalize_snapshot(data: object) -> dict[str, Any]:
    root = _root(data, "metadata snapshot")
    MetadataSnapshot.from_data(root)
    normalized = dict(root)
    normalized["version"] = 2
    normalized_albums: dict[str, Any] = {}
    for cid, value in _root(root["albums"], "metadata snapshot albums").items():
        record = dict(_root(value, f"metadata snapshot album {cid}"))
        record["fingerprint"] = metadata_fingerprint(
            cid, record["releaseDate"], tuple(record["artists"])
        )
        normalized_albums[cid] = record
    normalized["albums"] = normalized_albums
    return normalized


def load_aliases(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load aliases {path}: {exc}") from exc
    root = _root(data, "aliases")
    if root.get("version") != 1 or not isinstance(root.get("albums"), dict):
        raise ValueError("Aliases must have version 1 and an albums object")
    aliases: dict[str, str] = {}
    for cid, value in root["albums"].items():
        record = _root(value, f"alias {cid}")
        title = record.get("prtsTitle")
        if not isinstance(cid, str) or not isinstance(title, str) or not title:
            raise ValueError(f"Alias {cid} must have a non-empty prtsTitle")
        aliases[cid] = title
    return aliases


def _load_raw_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 2, "generatedAt": "", "albums": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    return _normalize_snapshot(data)


def publish_snapshot(
    path: Path,
    candidate: dict[str, Any],
    *,
    unmatched: list[tuple[str, str]],
    check: bool = False,
) -> PublishResult:
    candidate = _normalize_snapshot(candidate)
    old = _load_raw_snapshot(path)
    old_albums = _root(old["albums"], "metadata snapshot albums")
    new_albums = _root(candidate["albums"], "candidate snapshot albums")

    retained = 0
    new_unmatched = 0
    for cid, _ in unmatched:
        if cid in old_albums:
            new_albums[cid] = old_albums[cid]
            retained += 1
        else:
            new_unmatched += 1

    added = len(new_albums.keys() - old_albums.keys())
    unchanged = sum(old_albums.get(cid) == record for cid, record in new_albums.items())
    updated = len(new_albums) - added - unchanged
    result = PublishResult(added, updated, unchanged, retained, new_unmatched)
    if check:
        return result

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as output:
            temporary = Path(output.name)
            json.dump(candidate, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return result
