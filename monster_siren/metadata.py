from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_ALIASES_PATH = Path(__file__).with_name("data") / "prts-aliases.json"
DEFAULT_SNAPSHOT_PATH = Path(__file__).with_name("data") / "prts-metadata.json"
REMOTE_SNAPSHOT_URL = (
    "https://raw.githubusercontent.com/tsuru-kiri/msr-dl/refs/heads/main/"
    "monster_siren/data/prts-metadata.json"
)
MAX_SNAPSHOT_BYTES = 20 * 1024 * 1024


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


def _snapshot_datetime(data: object) -> datetime:
    root = _root(data, "metadata snapshot")
    generated_at = root.get("generatedAt")
    if not isinstance(generated_at, str) or not generated_at:
        raise ValueError("Metadata snapshot has no generatedAt")
    value = generated_at[:-1] + "+00:00" if generated_at.endswith("Z") else generated_at
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Metadata snapshot has an invalid generatedAt") from exc
    if parsed.tzinfo is None:
        raise ValueError("Metadata snapshot generatedAt must include a timezone")
    return parsed.astimezone(UTC)


def _fetch_remote_snapshot_data(
    url: str = REMOTE_SNAPSHOT_URL,
    session: requests.Session | None = None,
) -> object:
    owns_session = session is None
    client = session or requests.Session()
    if owns_session:
        retry = Retry(
            total=4,
            connect=4,
            read=4,
            status=4,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        client.mount("https://", HTTPAdapter(max_retries=retry))
    response: requests.Response | None = None
    try:
        response = client.get(url, timeout=(10.0, 60.0), stream=True)
        response.raise_for_status()
        length = response.headers.get("content-length")
        if length and int(length) > MAX_SNAPSHOT_BYTES:
            raise ValueError(f"Metadata snapshot exceeds {MAX_SNAPSHOT_BYTES} bytes")
        content = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            content.extend(chunk)
            if len(content) > MAX_SNAPSHOT_BYTES:
                raise ValueError(
                    f"Metadata snapshot exceeds {MAX_SNAPSHOT_BYTES} bytes"
                )
        return json.loads(content)
    finally:
        if response is not None:
            response.close()
        if owns_session:
            client.close()


def load_metadata_snapshot(path: Path | None = None) -> MetadataSnapshot:
    """Load an explicit snapshot, or choose the newest bundled/remote snapshot."""
    if path is not None:
        return MetadataSnapshot.from_path(path)

    try:
        bundled_data = json.loads(DEFAULT_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Could not load metadata snapshot {DEFAULT_SNAPSHOT_PATH}: {exc}"
        ) from exc
    bundled = MetadataSnapshot.from_data(bundled_data)
    bundled_generated_at = _snapshot_datetime(bundled_data)

    try:
        remote_data = _fetch_remote_snapshot_data()
        remote = MetadataSnapshot.from_data(remote_data)
        if _snapshot_datetime(remote_data) > bundled_generated_at:
            logging.info("Using newer remote metadata snapshot.")
            return remote
    except (OSError, ValueError, requests.RequestException) as exc:
        logging.warning("Could not use remote metadata snapshot: %s", exc)
    return bundled


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
    MetadataSnapshot.from_data(data)
    return _root(data, "metadata snapshot")


def _without_generated_at(snapshot: dict[str, Any]) -> dict[str, Any]:
    comparable = dict(snapshot)
    comparable.pop("generatedAt", None)
    return comparable


def publish_snapshot(
    path: Path,
    candidate: dict[str, Any],
    *,
    unmatched: list[tuple[str, str]],
    check: bool = False,
) -> PublishResult:
    existed = path.exists()
    candidate = _normalize_snapshot(candidate)
    old_raw = _load_raw_snapshot(path)
    old = _normalize_snapshot(old_raw)
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
    content_changed = not existed or _without_generated_at(
        candidate
    ) != _without_generated_at(old_raw)
    if check or not content_changed:
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
