# Monster Siren Downloader

Download the Monster Siren catalog with cover art, metadata, and synchronized
lyrics. MP3 sources are preserved and WAV sources are converted to FLAC.

## Reliability

- HTTP requests use timeouts, status checks, and retry/backoff.
- Each album task owns its `requests.Session`; sessions are not shared by threads.
- Audio is downloaded, converted, tagged, and validated before atomic publication.
- Output paths include album/song CIDs and track numbers to prevent collisions.
- Completed state is accepted only when its recorded output still exists.
- API application error codes and response shapes are validated.
- Corrupt state is backed up rather than silently overwritten.
- Cover, lyric, and audio downloads have size limits and trusted-host checks.

## Requirements

- Python 3.10 through 3.13
- FFmpeg available on `PATH`

Install with pip:

```bash
python -m pip install -e .
```

Install with uv:

```bash
uv venv
uv sync
```

## Standalone executable

Build a single-file executable for the current operating system:

```bash
uv sync --extra build
uv run pyinstaller --clean --noconfirm msr-dl.spec
```

The executable is written to `dist/msr-dl` (`dist/msr-dl.exe` on Windows).
Run a quick check with:

```bash
./dist/msr-dl --version
```

PyInstaller output is specific to the operating system and CPU architecture on
which it is built, so build separately on each target platform. FFmpeg is not
embedded; it must still be installed and available on `PATH` when downloading
or applying metadata. The bundled PRTS JSON snapshot and aliases are included
in the executable.

## Run

Download everything:

```bash
python main.py
# or, after package installation
msr-dl
```

List albums or an album's songs without downloading:

```bash
msr-dl list
msr-dl list --album-cid 0239
```

Download a specific album or song by CID:

```bash
msr-dl download --album-cid 0239
msr-dl download --song-cid <song-cid>
```

`msr-dl download` and the legacy `msr-dl` command both download the full
catalog by default.

Common options:

```bash
python main.py --output ~/Music/MonsterSiren
python main.py --workers 2
python main.py --album "Ambience" --album "Contingency"
python main.py --force
python main.py --no-lyrics
python main.py --verbose
```

Use an updated PRTS metadata snapshot while downloading:

```bash
msr-dl download --metadata-snapshot /config/prts-metadata.json
```

## PRTS metadata

Monster Siren does not expose album release dates and occasionally omits artist
credits. Generate a snapshot from the PRTS Wiki music overview table:

```bash
msr-dl metadata update \
  --snapshot /config/prts-metadata.json \
  --aliases /config/prts-aliases.json
```

Use `--check` to report changes without writing the snapshot. The updater makes
one Monster Siren album-list request and one PRTS music-overview request. It
does not visit individual album pages or search for unmatched titles.

Leading and trailing ASCII spaces are removed from album names before they are
matched exactly and case-sensitively. Other name differences are maintained by
CID in the aliases JSON. Existing unmatched records are retained when a
snapshot is updated, while new unmatched albums are reported and omitted.

PRTS artists are normalized to include `塞壬唱片-MSR` first. They are used only
when Monster Siren's album or song artist data is empty. PRTS release dates
replace source dates. Without a PRTS date, valid MP3/FLAC dates are preserved,
but WAV production metadata is discarded during FLAC conversion.

Apply updated PRTS metadata to files that are already downloaded without
downloading their audio, covers, or lyrics again:

```bash
msr-dl metadata apply
msr-dl metadata apply --output ~/Music/MonsterSiren
msr-dl metadata apply --snapshot /config/prts-metadata.json
msr-dl metadata apply --album-cid 0239
msr-dl metadata apply --song-cid <song-cid>
```

By default, only PRTS release dates and artist fallbacks whose album fingerprint
has changed are applied. `--force` reapplies those PRTS values even when their
fingerprint is unchanged. `--all` always reapplies current Monster Siren tags
and the existing local cover and lyrics, while still preserving unchanged PRTS
values. Combine both options to reapply everything:

```bash
msr-dl metadata apply --all
msr-dl metadata apply --all --force
```

Metadata application keeps existing file and directory names. Explicit album
or song targets must have at least one completed download in the state file.
For a partially downloaded album, only completed songs are updated and missing
songs are reported. Do not run downloads and metadata application against the
same output directory at the same time.

Newly generated PRTS snapshots use version 2 and store a SHA-256 fingerprint
for each album's CID, release date, and ordered artist list. Version 1 snapshots
remain readable and have fingerprints calculated in memory.

## Output and state

```text
MonsterSiren/
  download_state.json
  Album name [album-cid]/
    cover.png
    01 - Song name [song-cid].flac
    01 - Song name [song-cid].lrc
```

State version 3 records each output's relative path and size, plus the PRTS
fingerprint and whether its album/song artists came from the PRTS fallback.
This provenance lets later MSR artist additions replace an old fallback safely.
A failed song is retried on the next run. A completed song is skipped only when
its recorded output still exists and matches the current album, track, song
name, and CID.

Version 1 state entries have no output path, so they are treated as stale and
downloaded into the CID-based layout. Do not run multiple downloader processes
against the same output directory.

## Development

```bash
uv sync --extra dev
pytest -q
ruff check .
ruff format --check .
```

## Structure

```text
main.py
monster_siren/
  api.py          HTTP/API validation, retries, and streaming
  audio.py        media detection, WAV -> FLAC, tags, cover, and lyrics
  downloader.py   orchestration and album concurrency
  metadata.py     PRTS snapshot loading, fingerprints, and publishing
  metadata_apply.py  metadata application to completed downloads
  prts.py         PRTS Wiki parsing and snapshot generation
  state.py        resumable state and atomic persistence
  utils.py        portable unique paths and cover conversion
```
