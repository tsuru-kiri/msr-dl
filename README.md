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

Python 3.10–3.13 and FFmpeg available on `PATH` are required.

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
