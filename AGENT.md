# Agent guide

## Project scope

`msr-dl` is a Python 3.10–3.13 CLI that downloads the Monster Siren catalog,
preserves MP3 sources, converts WAV to FLAC, embeds artwork and synchronized
lyrics, and augments incomplete source metadata with a PRTS snapshot.

Read the relevant document before changing behavior:

- `docs/usage.md` for CLI behavior, output layout, and resume semantics
- `docs/metadata.md` for snapshot matching, publishing, and apply semantics
- `docs/development.md` for the module map, reliability design, and builds

Keep `README.md` short, user-oriented, and in English. Preserve its Korean
translation in `README.ko.md`, keep the two files linked to each other, and
update both when their shared content changes. Write `docs/` in English, put
operational detail there, and update the corresponding document whenever
user-visible behavior changes.

## Development commands

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Run focused tests while iterating, then run the full suite and both Ruff checks
before handing off a change. Do not edit generated artifacts under `build/`,
`dist/`, `*.egg-info/`, or cache directories.

## Change constraints

- Preserve the legacy invocation: no command, or options before a command,
  must continue to behave as `download`.
- Keep CLI parsing and dispatch in `main.py`; keep domain behavior in the
  corresponding `monster_siren` module.
- Treat all API and snapshot data as untrusted. Retain response-shape checks,
  trusted-host checks, byte limits, image dimension limits, and path
  containment checks.
- Never share a `requests.Session` between album worker threads. A session is
  owned and closed by one album task.
- Publish audio, state, covers, and snapshots through a temporary file in the
  destination directory followed by atomic replacement. Clean up temporary
  files on failure.
- Keep output paths portable and collision-resistant. Album and song CIDs are
  part of the layout; do not remove them without a state migration.
- A song may be skipped only when its completed state matches the expected
  album, track, name, CID, existing output, recorded size, and requested lyric
  state.
- State paths must remain relative to the output root and must not resolve
  outside it. Invalid state must be backed up rather than overwritten.
- PRTS artists are fallback data only when Monster Siren artists are empty.
  PRTS release dates take precedence. Preserve provenance fields so later
  Monster Siren data can replace a prior fallback.
- Snapshot matching trims only leading and trailing ASCII spaces, then matches
  exactly and case-sensitively. Other title differences belong in
  `monster_siren/data/prts-aliases.json`, keyed by album CID.
- Snapshot content equality ignores `generatedAt`; do not create a content
  update when only that timestamp changed. Retain existing records for newly
  unmatched source albums.
- Do not run or design concurrent writers against the same output directory.

Tests mirror the production modules (`tests/test_api.py`, `test_audio.py`,
`test_downloader.py`, `test_metadata.py`, `test_metadata_apply.py`,
`test_prts.py`, `test_state.py`, and `test_utils.py`). Add or update the focused
test whenever behavior changes.
