# Usage

## Installation

Python 3.10–3.13 and FFmpeg available on `PATH` are required. Install the
working tree with pip or uv.

```bash
python -m pip install -e .
```

```bash
uv venv
uv sync
```

## Browsing the catalog

List albums or the songs in an album without downloading them.

```bash
msr-dl list
msr-dl list --album-cid 0239
```

## Downloading

`msr-dl`, `msr-dl download`, and `python main.py` download the entire catalog
to `./MonsterSiren` by default.

```bash
msr-dl
msr-dl download
```

Select one album or song by CID.

```bash
msr-dl download --album-cid 0239
msr-dl download --song-cid <song-cid>
```

You can also filter albums by a case-insensitive substring. Repeat `--album` to
match more than one value.

```bash
msr-dl download --album "Ambience" --album "Contingency"
```

Common options include:

```bash
msr-dl download --output ~/Music/MonsterSiren
msr-dl download --workers 2
msr-dl download --force
msr-dl download --no-lyrics
msr-dl download --verbose
msr-dl download --metadata-snapshot /config/prts-metadata.json
```

- `--force` redownloads songs even when their state is complete.
- `--no-lyrics` skips downloading and embedding lyrics.
- `--metadata-snapshot` uses the given PRTS snapshot instead of the bundled or
  remote snapshot.

## Output and resume behavior

The default output layout is:

```text
MonsterSiren/
  download_state.json
  Album name [album-cid]/
    cover.png
    01 - Song name [song-cid].flac
    01 - Song name [song-cid].lrc
```

MP3 sources remain MP3 files, while WAV sources are converted to FLAC. Album
and song CIDs and track numbers are included in paths to prevent collisions
between items with the same name.

`download_state.json` records each output's relative path, size, and metadata
provenance. A song is skipped on a later run only when its completed record
matches the actual output. Failed songs and stale state entries are processed
again. A corrupt state file is preserved in the same directory with a
`.broken-<timestamp>` suffix instead of being overwritten.

Do not run multiple downloader processes against the same output directory, or
run downloads and `metadata apply` against that directory at the same time.

