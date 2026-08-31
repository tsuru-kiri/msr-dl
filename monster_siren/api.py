from __future__ import annotations

from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_URL = "https://monster-siren.hypergryph.com"


class MonsterSirenAPI:
    """Small HTTP client responsible only for Monster Siren API/network access."""

    def __init__(self, timeout: tuple[float, float] = (10.0, 60.0)) -> None:
        self.timeout = timeout
        self.session = requests.Session()

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
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        self.session.mount("https://", adapter)
        self.session.headers.update({"Accept": "application/json"})

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "MonsterSirenAPI":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _get_json(self, url: str) -> Any:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if "data" not in payload:
            raise ValueError(f"Unexpected API response from {url}")
        return payload["data"]

    def get_albums(self) -> list[dict[str, Any]]:
        return self._get_json(f"{BASE_URL}/api/albums")

    def get_album_detail(self, cid: str) -> dict[str, Any]:
        return self._get_json(f"{BASE_URL}/api/album/{cid}/detail")

    def get_song_detail(self, cid: str) -> dict[str, Any]:
        return self._get_json(f"{BASE_URL}/api/song/{cid}")

    def download_bytes(self, url: str) -> bytes:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.content

    def stream_to_file(
        self,
        url: str,
        destination: Path,
        *,
        chunk_size: int = 64 * 1024,
    ) -> str:
        """Download to *.part first and atomically rename when complete."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")

        try:
            with self.session.get(url, stream=True, timeout=self.timeout) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";")[0].lower()

                with partial.open("wb") as f:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)

            partial.replace(destination)
            return content_type
        except Exception:
            partial.unlink(missing_ok=True)
            raise
