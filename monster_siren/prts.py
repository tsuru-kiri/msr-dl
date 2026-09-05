from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests

from .api import MAX_API_BYTES, MonsterSirenAPI
from .metadata import PublishResult, load_aliases, publish_snapshot

MONSTER_SIREN_ARTIST = "塞壬唱片-MSR"
PRTS_MUSIC_URL = "https://prts.wiki/w/衍生作品/音乐"
_FULL_DATE = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日(?:（数字版）)?$")
_SHORT_DATE = re.compile(r"^(\d{1,2})月(\d{1,2})日$")
_YEAR_HEADING = re.compile(r"^(\d{4})年?$")
_PRESERVED_TITLE_SUFFIXES = {
    "(Monster Siren Records)",
    "(Special Edition)",
    "[初回生産限定盤]",
    "[通常盤]",
    "[期間生産限定盤]",
}


@dataclass(frozen=True)
class PRTSRelease:
    title: str
    artists: tuple[str, ...]
    release_date: str


@dataclass(frozen=True)
class UpdateReport:
    albums: int
    unmatched: list[tuple[str, str]]
    publish: PublishResult


@dataclass(frozen=True)
class _Cell:
    parts: tuple[str, ...]
    rowspan: int
    colspan: int

    @property
    def text(self) -> str:
        return " ".join(self.parts)


@dataclass(frozen=True)
class _Table:
    rows: list[list[_Cell]]
    section_year: int | None


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self._table_depth = 0
        self._rows: list[list[_Cell]] | None = None
        self._row: list[_Cell] | None = None
        self._cell_attrs: dict[str, str] | None = None
        self._cell_parts: list[str] | None = None
        self._headings: dict[int, str] = {}
        self._heading_level: int | None = None
        self._heading_parts: list[str] | None = None
        self._table_year: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._rows = []
                self._table_year = self._active_year()
            return
        if self._table_depth != 1:
            if self._table_depth == 0 and tag in {"h2", "h3", "h4"}:
                self._heading_level = int(tag[1])
                self._heading_parts = []
            return
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_attrs = {key: value or "" for key, value in attrs}
            self._cell_parts = [""]
        elif tag == "br" and self._cell_parts is not None:
            self._cell_parts.append("")

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts[-1] += data
        elif self._heading_parts is not None:
            self._heading_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            if self._table_depth == 1 and self._rows is not None:
                self.tables.append(_Table(self._rows, self._table_year))
                self._rows = None
                self._table_year = None
            self._table_depth -= 1
            return
        if self._table_depth != 1:
            if (
                self._table_depth == 0
                and self._heading_level is not None
                and tag == f"h{self._heading_level}"
            ):
                level = self._heading_level
                text = " ".join("".join(self._heading_parts or []).split())
                self._headings = {
                    current: value
                    for current, value in self._headings.items()
                    if current < level
                }
                if text:
                    self._headings[level] = text
                self._heading_level = None
                self._heading_parts = None
            return
        if tag in {"td", "th"} and self._cell_parts is not None:
            attrs = self._cell_attrs or {}
            parts = tuple(
                text for part in self._cell_parts if (text := " ".join(part.split()))
            )
            self._row.append(
                _Cell(
                    parts=parts,
                    rowspan=max(1, int(attrs.get("rowspan", "1"))),
                    colspan=max(1, int(attrs.get("colspan", "1"))),
                )
            )
            self._cell_attrs = None
            self._cell_parts = None
        elif tag == "tr" and self._row is not None and self._rows is not None:
            self._rows.append(self._row)
            self._row = None

    def _active_year(self) -> int | None:
        for level in sorted(self._headings, reverse=True):
            match = _YEAR_HEADING.fullmatch(self._headings[level])
            if match is not None:
                return int(match.group(1))
        return None


def _expand_rows(rows: list[list[_Cell]]) -> list[list[_Cell]]:
    active: dict[int, tuple[_Cell, int]] = {}
    expanded: list[list[_Cell]] = []
    empty = _Cell((), 1, 1)

    for physical_row in rows:
        grid = {column: value[0] for column, value in active.items()}
        active = {
            column: (cell, remaining - 1)
            for column, (cell, remaining) in active.items()
            if remaining > 1
        }
        column = 0
        for cell in physical_row:
            while column in grid:
                column += 1
            for offset in range(cell.colspan):
                target = column + offset
                grid[target] = cell
                if cell.rowspan > 1:
                    active[target] = (cell, cell.rowspan - 1)
            column += cell.colspan
        if grid:
            expanded.append([grid.get(index, empty) for index in range(max(grid) + 1)])
    return expanded


def _release_date(value: str, section_year: int | None) -> str:
    match = _FULL_DATE.fullmatch(value)
    if match is not None:
        year, month, day = (int(part) for part in match.groups())
        return datetime(year, month, day).date().isoformat()
    match = _SHORT_DATE.fullmatch(value)
    if match is None:
        raise ValueError(f"Invalid PRTS release date: {value}")
    if section_year is None:
        raise ValueError(f"PRTS release date has no year heading: {value}")
    month, day = (int(part) for part in match.groups())
    year = section_year
    return datetime(year, month, day).date().isoformat()


def _artists(parts: tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for value in (MONSTER_SIREN_ARTIST, *parts):
        cleaned = " ".join(value.split())
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return tuple(values)


def _release_title(cell: _Cell) -> str:
    if not cell.parts:
        return ""
    title = cell.parts[0]
    if len(cell.parts) > 1 and cell.parts[1] in _PRESERVED_TITLE_SUFFIXES:
        return f"{title} {cell.parts[1]}"
    return title


def parse_music_table(html: str) -> dict[str, PRTSRelease]:
    parser = _TableParser()
    parser.feed(html)

    releases: dict[str, PRTSRelease] = {}
    found_table = False
    for table in parser.tables:
        rows = _expand_rows(table.rows)
        header_index = next(
            (
                index
                for index, row in enumerate(rows)
                if any(cell.text == "标题" for cell in row)
                and any("发布日期" in cell.text for cell in row)
            ),
            None,
        )
        if header_index is None:
            continue
        found_table = True
        header = rows[header_index]
        title_column = next(i for i, cell in enumerate(header) if cell.text == "标题")
        artist_column = next(
            (i for i, cell in enumerate(header) if cell.text == "艺术家"), None
        )
        date_column = next(
            i for i, cell in enumerate(header) if "发布日期" in cell.text
        )
        for row in rows[header_index + 1 :]:
            if max(title_column, date_column) >= len(row):
                continue
            title = _release_title(row[title_column])
            date_text = row[date_column].text
            if not title or not date_text:
                continue
            release = PRTSRelease(
                title=title,
                artists=_artists(
                    row[artist_column].parts
                    if artist_column is not None and artist_column < len(row)
                    else ()
                ),
                release_date=_release_date(date_text, table.section_year),
            )
            previous = releases.get(title)
            if previous is not None and previous.release_date != release.release_date:
                raise ValueError(f"Conflicting release dates for {title}")
            if previous is not None:
                release = PRTSRelease(
                    title=title,
                    artists=_artists((*previous.artists, *release.artists)),
                    release_date=release.release_date,
                )
            releases[title] = release
    if not found_table:
        raise ValueError("Could not find the PRTS music table")
    if not releases:
        raise ValueError("PRTS music table contains no release rows")
    return releases


def fetch_music_table(session: requests.Session | None = None) -> str:
    owns_session = session is None
    client = session or requests.Session()
    try:
        client.headers.update(
            {"Accept": "text/html", "User-Agent": "msr-dl metadata updater"}
        )
        response = client.get(PRTS_MUSIC_URL, timeout=(10.0, 120.0))
        response.raise_for_status()
        if len(response.content) > MAX_API_BYTES:
            raise ValueError(f"PRTS response exceeds {MAX_API_BYTES} bytes")
        return response.text
    finally:
        if owns_session:
            client.close()


def build_snapshot(
    albums: list[dict[str, Any]],
    releases: dict[str, PRTSRelease],
    aliases: dict[str, str],
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    records: dict[str, Any] = {}
    unmatched: list[tuple[str, str]] = []
    for album in albums:
        cid = album["cid"]
        name = album["name"]
        prts_title = aliases.get(cid, name)
        release = releases.get(prts_title)
        if release is None:
            unmatched.append((cid, name))
            continue
        records[cid] = {
            "msrName": name,
            "prtsTitle": prts_title,
            "releaseDate": release.release_date,
            "artists": list(release.artists),
        }
    return (
        {
            "version": 1,
            "generatedAt": datetime.now(UTC).isoformat(),
            "albums": records,
        },
        unmatched,
    )


def update_metadata_snapshot(
    snapshot_path: Path,
    aliases_path: Path,
    *,
    check: bool,
) -> UpdateReport:
    aliases = load_aliases(aliases_path)
    with MonsterSirenAPI() as api:
        albums = api.get_albums()
    releases = parse_music_table(fetch_music_table())
    snapshot, unmatched = build_snapshot(albums, releases, aliases)
    published = publish_snapshot(
        snapshot_path,
        snapshot,
        unmatched=unmatched,
        check=check,
    )
    return UpdateReport(len(albums), unmatched, published)
