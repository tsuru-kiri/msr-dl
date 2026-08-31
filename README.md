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

## Output and state

```text
MonsterSiren/
  download_state.json
  Album name [album-cid]/
    cover.png
    01 - Song name [song-cid].flac
    01 - Song name [song-cid].lrc
```

State version 2 records each output's relative path and size. A failed song is
retried on the next run. A completed song is skipped only when its recorded
output still exists and matches the current album, track, song name, and CID.

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
  state.py        resumable state and atomic persistence
  utils.py        portable unique paths and cover conversion
```
