# Development

## Setup and verification

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Run the relevant test file while working on a focused area. Before handing off
a change, run the full test suite and both Ruff checks.

## Publishing a release

Run the **Release** workflow from the GitHub Actions page on the `main` branch
and enter the next stable SemVer without a `v` prefix, such as `1.2.3`. The
version must be greater than the current project version. The workflow updates
the package version, commits it as `chore: release v1.2.3`, and creates the
annotated `v1.2.3` tag.

After the source checks pass, the workflow publishes a GitHub Release whose
notes list commit messages since the previous release. Its assets include the
wheel, source distribution, `install.ps1` Windows installer, and POSIX
`install.sh`. The Windows installer uses the release wheel with
`uv tool install` and installs its private FFmpeg at
`%LOCALAPPDATA%\msr-dl\ffmpeg` when FFmpeg is not already on `PATH`.

The POSIX installer supports Intel and Apple Silicon macOS plus glibc Linux on
x86_64 and ARM64. It rejects 32-bit, musl, and other platforms before making
changes. Its private FFmpeg lives at
`~/Library/Application Support/msr-dl/ffmpeg` on macOS or
`${XDG_DATA_HOME:-$HOME/.local/share}/msr-dl/ffmpeg` on Linux. macOS stable
release ZIPs and their SHA-256 sidecars come from Martin Riedl's build server;
Linux GPL static archives and `checksums.sha256` come from BtbN FFmpeg Builds.
The release wheel is selected from GitHub's latest-release API and checked
against the asset's SHA-256 digest before `uv tool install` runs.

After publication, the workflow runs each installer twice: Windows on its
native runner and POSIX on x86_64/ARM64 Linux and Intel/Apple Silicon macOS.
This verifies architecture-specific downloads, checksums, version reporting,
the private FFmpeg, and the no-op update path. CI parses `install.ps1` with
Windows PowerShell 5.1 and checks `install.sh` with `sh -n` and ShellCheck.

After publishing the GitHub release, the workflow updates `Formula/msr-dl.rb`
in `tsuru-kiri/homebrew-tap` to install the source distribution into an
isolated Homebrew virtual environment backed by `python@3.13`. Python resources
are resolved and checksummed with `brew update-python-resources`; Pillow is
provided by its Homebrew formula. The generated formula is installed and tested
before it is committed. The `HOMEBREW_TAP_DEPLOY_KEY` Actions secret must
contain a private deploy key whose public key has write access to that tap
repository.

The same release is published to `ghcr.io/<owner>/<repository>` for
`linux/amd64` and `linux/arm64`, with `v1.2.3`, `1.2.3`, and `latest` tags.
GitHub Actions needs permission to write repository contents and packages, and
branch protection must allow the workflow to push its release commit and tag.

If a job fails after the tag has been pushed, use **Re-run failed jobs** on the
same workflow run. Do not dispatch a new run with the same version, because
duplicate versions and tags are rejected deliberately.

## Code structure

```text
main.py                    CLI parsing and command dispatch
monster_siren/
  api.py                   HTTP/API validation, retries, and streaming
  audio.py                 Media detection, WAV→FLAC, tags, covers, and lyrics
  downloader.py            Download orchestration and album concurrency
  metadata.py              PRTS snapshot loading, fingerprints, and publishing
  metadata_apply.py        Metadata application to completed downloads
  prts.py                  PRTS Wiki parsing and snapshot generation
  state.py                 Resumable state and atomic persistence
  utils.py                 Portable unique paths and cover conversion
monster_siren/data/        Bundled snapshot and album aliases
tests/                     pytest tests organized by module
```

## Reliability design

- HTTP requests use timeouts, status checks, retries, and backoff.
- Each album task owns its own `requests.Session`; sessions are never shared
  between threads.
- Audio is downloaded, converted, tagged, and validated before atomic
  publication.
- Cover, lyric, and audio downloads have size limits and trusted-host checks.
- API application error codes and response shapes are validated.
- Output paths include CIDs and track numbers and must remain portable.
- Completed state is accepted only when the recorded output exists and matches
  the expected path and size.
- State and snapshot publication use a temporary file in the destination
  directory followed by atomic replacement.

The current state format is version 3. Version 1 entries have no output path,
so they are treated as stale and downloaded again into the CID-based layout.
State also records the PRTS fingerprint and whether album or song artists came
from a PRTS fallback. This provenance allows artist data later added by Monster
Siren to replace an older fallback safely.
