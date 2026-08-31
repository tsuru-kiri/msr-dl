# Monster Siren Downloader — Refactored

This is a refactoring of `khanhn201/monster-siren-download` that keeps the core behavior:

- fetch all Monster Siren albums
- download album covers
- download MP3/WAV sources
- convert WAV to FLAC
- download LRC lyrics
- embed album/title/artist/track/cover/lyrics metadata

## Main improvements

- API/network code is isolated in `monster_siren/api.py`
- HTTP timeouts, `raise_for_status()`, and retry/backoff are enabled
- one `requests.Session` is created per worker thread
- downloads use `*.part` files and atomic rename
- state is keyed by **album cid + song cid**, not album name
- failed songs are recorded and can be retried on the next run
- state file updates are thread-safe and atomic
- broad `except: pass` blocks are removed
- multiple artists are stored with `, ` separators
- configurable output path, worker count, album filter, lyrics, and force mode
- functions/classes have narrower responsibilities

## Requirements

Python 3.10+ is recommended.

FFmpeg must be installed and available on PATH.

```bash
pip install -r requirements.txt
```

## Run

Download everything:

```bash
python main.py
```

Choose output directory:

```bash
python main.py --output ~/Music/MonsterSiren
```

Limit concurrency:

```bash
python main.py --workers 2
```

Download only matching albums:

```bash
python main.py --album "Ambience"
```

Repeat `--album` to match multiple album-name fragments:

```bash
python main.py --album "Ambience" --album "Contingency"
```

Retry/redownload everything selected:

```bash
python main.py --force
```

Skip lyrics:

```bash
python main.py --no-lyrics
```

Verbose logs:

```bash
python main.py --verbose
```

## State file

Progress is stored in:

```text
MonsterSiren/download_state.json
```

Example:

```json
{
  "version": 1,
  "albums": {
    "album-cid": {
      "name": "Album name",
      "songs": {
        "song-cid": {
          "name": "Song name",
          "status": "complete"
        }
      },
      "status": "complete"
    }
  }
}
```

A failed song remains `failed`, so the next normal run retries it while completed songs are skipped.

## Structure

```text
main.py
monster_siren/
  api.py          HTTP/API, retries, streaming
  audio.py        WAV -> FLAC, tags, cover, lyrics
  downloader.py   orchestration and concurrency
  state.py        resumable state
  utils.py        safe filenames and cover conversion
```
