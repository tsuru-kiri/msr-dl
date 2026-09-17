# msr-dl

[English](README.md)
[Korean](README.ko.md)

A command-line tool for downloading Monster Siren Records music with
cover art, metadata, and synchronized lyrics.

## Features

- Download the entire catalog or a single album or song by CID
- Resume interrupted downloads from persistent state
- Embed cover art and synchronized LRC lyrics
- Fill in release dates and missing artist credits from PRTS Wiki metadata

## Quick start

On macOS or Linux, run the installer below. Run the same command again to
update when a newer release is available.

```sh
curl -LsSf https://github.com/tsuru-kiri/msr-dl/releases/latest/download/install.sh | sh
```

It supports Intel and Apple Silicon macOS and 64-bit glibc Linux on x86_64 or
ARM64. It installs `uv`, msr-dl, and, when needed, a private FFmpeg without
administrator privileges.

On Windows, open PowerShell and run the installer. The same command installs
updates when a newer release is available.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -c "irm https://github.com/tsuru-kiri/msr-dl/releases/latest/download/install.ps1 | iex"
```

The installer sets up `uv`, msr-dl, and a private FFmpeg installation without
requiring administrator privileges.

Homebrew remains an alternative on macOS:

```bash
brew install tsuru-kiri/tap/msr-dl
```

To run from source instead, Python 3.11–3.13 and FFmpeg available on `PATH`
are required.

```bash
python -m pip install -e .
msr-dl list
msr-dl download --album-cid 0239
```

With no arguments, msr-dl downloads the entire catalog to `./MonsterSiren`.

```bash
msr-dl
```

The output directory and number of concurrent album workers are configurable.

```bash
msr-dl download --output ~/Music/MonsterSiren --workers 2
```

## Documentation

- [Usage](docs/usage.md): target selection, options, output layout, and caveats
- [PRTS metadata](docs/metadata.md): updating snapshots and applying metadata
- [Development](docs/development.md): setup, tests, builds, and architecture
