# msr-dl

[Korean](README.ko.md)

A command-line tool for downloading Monster Siren Records music with
cover art, metadata, and synchronized lyrics.

## Features

- Download the entire catalog or a single album or song by CID
- Resume interrupted downloads from persistent state
- Embed cover art and synchronized LRC lyrics
- Fill in release dates and missing artist credits from PRTS Wiki metadata

## Quick start

### Installation

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
```

### Run

With no arguments, msr-dl downloads the entire catalog to `./MonsterSiren`.

```bash
msr-dl
```

You can also list the catalog, download a specific album, or configure the
output directory and number of concurrent album workers.

```bash
msr-dl list
msr-dl download --album-cid 0239
msr-dl download --output ~/Music/MonsterSiren --workers 2
```

## Disclaimer

msr-dl is an unofficial project and is not affiliated with or endorsed by
Hypergryph or Monster Siren Records. All music, artwork, lyrics, trademarks,
and related materials are the property of their respective rights holders.

This project does not include downloaded media. Users are responsible for
ensuring that their use of this tool complies with applicable laws and the
terms of the source service. They are also solely responsible for any
redistribution or commercial use of downloaded content and the consequences
arising from it.

## Acknowledgments

This project was inspired by
[khanhn201/monster-siren-download](https://github.com/khanhn201/monster-siren-download).

## License

msr-dl is available under the [MIT License](LICENSE). See
[third-party notices](THIRD_PARTY_NOTICES) for incorporated work.

## Documentation

- [Usage](docs/usage.md): target selection, options, output layout, and caveats
- [PRTS metadata](docs/metadata.md): updating snapshots and applying metadata
- [Development](docs/development.md): setup, tests, builds, and architecture
