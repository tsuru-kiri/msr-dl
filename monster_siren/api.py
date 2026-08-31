from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://monster-siren.hypergryph.com"
MAX_COVER_BYTES = 20 * 1024 * 1024
MAX_LYRIC_BYTES = 5 * 1024 * 1024
MAX_AUDIO_BYTES = 2 * 1024 * 1024 * 1024
MAX_API_BYTES = 20 * 1024 * 1024


class MonsterSirenAPIError(RuntimeError):
    pass


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

    def __enter__(self) -> MonsterSirenAPI:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _get_json(self, url: str) -> Any:
        response = self._get_api_response(url)
        try:
            response.raise_for_status()
            content = self._read_limited(response, max_bytes=MAX_API_BYTES)
        finally:
            response.close()
        payload = json.loads(content)
        if not isinstance(payload, dict) or "data" not in payload:
            raise ValueError(f"Unexpected API response from {url}")
        if payload.get("code") != 0:
            message = payload.get("msg") or "unknown error"
            raise MonsterSirenAPIError(f"API error {payload.get('code')}: {message}")
        return payload["data"]

    def get_albums(self) -> list[dict[str, Any]]:
        data = self._get_json(f"{BASE_URL}/api/albums")
        if not isinstance(data, list):
            raise ValueError("Album list response must be a list")
        for album in data:
            self._validate_summary(album, "album")
        return data

    def get_album_detail(self, cid: str) -> dict[str, Any]:
        data = self._get_json(f"{BASE_URL}/api/album/{cid}/detail")
        if not isinstance(data, dict) or not isinstance(data.get("songs"), list):
            raise ValueError(f"Invalid album detail for {cid}")
        for song in data["songs"]:
            self._validate_summary(song, "song")
        return data

    def get_song_detail(self, cid: str) -> dict[str, Any]:
        data = self._get_json(f"{BASE_URL}/api/song/{cid}")
        if not isinstance(data, dict) or not isinstance(data.get("sourceUrl"), str):
            raise ValueError(f"Invalid song detail for {cid}")
        return data

    @staticmethod
    def _validate_summary(value: object, label: str) -> None:
        if not isinstance(value, dict):
            raise ValueError(f"Invalid {label} entry")
        if not isinstance(value.get("cid"), str) or not isinstance(
            value.get("name"), str
        ):
            raise ValueError(f"{label.title()} entry is missing cid or name")

    @staticmethod
    def _validate_download_url(url: str) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (
            host == "monster-siren.hypergryph.com" or host.endswith(".hycdn.cn")
        ):
            raise ValueError(f"Untrusted download URL: {url}")

    @staticmethod
    def _validate_api_url(url: str) -> None:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "monster-siren.hypergryph.com"
        ):
            raise ValueError(f"Untrusted API URL: {url}")

    def _get_api_response(self, url: str) -> requests.Response:
        return self._get_redirected_response(url, self._validate_api_url)

    def download_bytes(self, url: str, *, max_bytes: int) -> bytes:
        with self._get_download_response(url) as response:
            response.raise_for_status()
            return self._read_limited(response, max_bytes=max_bytes)

    @staticmethod
    def _read_limited(response: requests.Response, *, max_bytes: int) -> bytes:
        length = response.headers.get("content-length")
        if length and int(length) > max_bytes:
            raise ValueError(f"Response exceeds {max_bytes} bytes")
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > max_bytes:
                raise ValueError(f"Response exceeds {max_bytes} bytes")
            chunks.append(chunk)
        if size == 0:
            raise ValueError("Empty response")
        return b"".join(chunks)

    def _get_download_response(self, url: str) -> requests.Response:
        return self._get_redirected_response(url, self._validate_download_url)

    def _get_redirected_response(
        self,
        url: str,
        validator: Any,
    ) -> requests.Response:
        for _ in range(6):
            validator(url)
            response = self.session.get(
                url,
                stream=True,
                timeout=self.timeout,
                allow_redirects=False,
            )
            if not response.is_redirect:
                return response

            location = response.headers.get("location")
            response.close()
            if not location:
                raise ValueError("Download redirect has no Location header")
            url = urljoin(url, location)

        raise ValueError("Too many download redirects")

    def stream_to_file(
        self,
        url: str,
        destination: Path,
        *,
        chunk_size: int = 64 * 1024,
        max_bytes: int = MAX_AUDIO_BYTES,
    ) -> str:
        """Download to *.part first and atomically rename when complete."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial: Path | None = None

        try:
            with self._get_download_response(url) as response:
                response.raise_for_status()
                content_type = (
                    response.headers.get("content-type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                length = response.headers.get("content-length")
                if length and int(length) > max_bytes:
                    raise ValueError(f"Audio exceeds {max_bytes} bytes")

                with tempfile.NamedTemporaryFile(
                    prefix=f".{destination.name}.",
                    suffix=".part",
                    dir=destination.parent,
                    delete=False,
                ) as f:
                    partial = Path(f.name)
                    size = 0
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            size += len(chunk)
                            if size > max_bytes:
                                raise ValueError(f"Audio exceeds {max_bytes} bytes")
                            f.write(chunk)
                    if size == 0:
                        raise ValueError("Empty audio response")

            partial.replace(destination)
            return content_type
        finally:
            if partial is not None:
                partial.unlink(missing_ok=True)
