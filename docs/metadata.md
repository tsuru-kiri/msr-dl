# PRTS metadata

The Monster Siren API does not provide album release dates and occasionally
omits artist credits. msr-dl supplements it with a snapshot generated from the
PRTS Wiki music overview.

## Snapshot selection during downloads

Unless a snapshot is specified, msr-dl compares the bundled snapshot with the
snapshot on the repository's `main` branch and uses the one with the newer
`generatedAt` value. If the remote snapshot cannot be downloaded or validated,
msr-dl logs a warning and continues with the bundled snapshot.

To use a specific file:

```bash
msr-dl download --metadata-snapshot /config/prts-metadata.json
```

PRTS release dates replace source dates. PRTS artists are normalized with
`塞壬唱片-MSR` first and are used only when Monster Siren's album or song artist
data is empty. Without a PRTS date, valid MP3 and FLAC dates are preserved, but
WAV production metadata is discarded during FLAC conversion.

## Updating a snapshot

Generate a snapshot from the PRTS Wiki music overview:

```bash
msr-dl metadata update \
  --snapshot /config/prts-metadata.json \
  --aliases /config/prts-aliases.json
```

Add `--check` to report changes without writing the snapshot. The updater makes
one Monster Siren album-list request and one PRTS music-overview request. It
does not visit individual album pages or search for unmatched titles.

Album names have leading and trailing ASCII spaces removed before they are
matched exactly and case-sensitively. Other title differences are maintained
by CID in the aliases JSON. Existing unmatched records are retained during an
update, while new unmatched albums are reported and omitted.

GitHub Actions refreshes the bundled snapshot daily and whenever
`monster_siren/data/prts-aliases.json` changes. An update that changes only
`generatedAt` is not committed. Unmatched albums are maintained in one
automation issue, which is closed automatically when every match is resolved.

New snapshots use version 2 and store a SHA-256 fingerprint of each album's
CID, release date, and ordered artist list. Version 1 snapshots remain readable
and have their fingerprints calculated in memory.

## Applying metadata to existing files

Update PRTS metadata in completed files without downloading audio, covers, or
lyrics again.

```bash
msr-dl metadata apply
msr-dl metadata apply --output ~/Music/MonsterSiren
msr-dl metadata apply --snapshot /config/prts-metadata.json
msr-dl metadata apply --album-cid 0239
msr-dl metadata apply --song-cid <song-cid>
```

By default, PRTS release dates and artist fallbacks are applied only when the
album fingerprint has changed.

- `--force` reapplies PRTS values even when the fingerprint is unchanged.
- `--all` always reapplies the current Monster Siren tags and local cover and
  lyrics while preserving unchanged PRTS values.
- Using both options reapplies every value.

```bash
msr-dl metadata apply --all --force
```

Metadata application keeps existing file and directory names. An explicitly
selected album or song must have at least one completed download in the state
file. For a partially downloaded album, only completed songs are updated and
missing songs are reported.

