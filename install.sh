#!/bin/sh

set -eu

REPOSITORY=tsuru-kiri/msr-dl
LATEST_RELEASE_API="https://api.github.com/repos/$REPOSITORY/releases/latest"
UV_INSTALLER_URL=https://astral.sh/uv/install.sh
BTBN_RELEASE_URL=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest
STEP=0
STEP_COUNT=5
TEMP_DIRECTORY=
FFMPEG_STAGING_ROOT=

fail() {
    printf '\nInstallation failed: %s\n' "$*" >&2
    exit 1
}

step() {
    STEP=$((STEP + 1))
    printf '[%s/%s] %s\n' "$STEP" "$STEP_COUNT" "$1"
}

have() {
    command -v "$1" >/dev/null 2>&1
}

cleanup() {
    if [ -n "$FFMPEG_STAGING_ROOT" ] && [ -d "$FFMPEG_STAGING_ROOT" ]; then
        rm -rf -- "$FFMPEG_STAGING_ROOT"
    fi
    if [ -n "$TEMP_DIRECTORY" ] && [ -d "$TEMP_DIRECTORY" ]; then
        rm -rf -- "$TEMP_DIRECTORY"
    fi
}

trap cleanup EXIT HUP INT TERM

sha256_file() {
    if have shasum; then
        shasum -a 256 "$1" | awk '{print $1}'
    elif have sha256sum; then
        sha256sum "$1" | awk '{print $1}'
    else
        fail "SHA-256 verification requires shasum or sha256sum."
    fi
}

find_uv() {
    if have uv; then
        command -v uv
        return
    fi
    for candidate in \
        "${UV_INSTALL_DIR:-}/uv" \
        "${XDG_BIN_HOME:-}/uv" \
        "${XDG_DATA_HOME:-}/../bin/uv" \
        "$HOME/.local/bin/uv"
    do
        if [ "$candidate" != "/uv" ] && [ "$candidate" != "/../bin/uv" ] && [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return
        fi
    done
    return 1
}

OS_NAME=$(uname -s)
MACHINE=$(uname -m)
case "$OS_NAME:$MACHINE" in
    Darwin:x86_64) PLATFORM=macos; FFMPEG_ARCH=amd64 ;;
    Darwin:arm64) PLATFORM=macos; FFMPEG_ARCH=arm64 ;;
    Linux:x86_64|Linux:amd64) PLATFORM=linux; FFMPEG_ARCH=linux64 ;;
    Linux:aarch64|Linux:arm64) PLATFORM=linux; FFMPEG_ARCH=linuxarm64 ;;
    Darwin:*) fail "Unsupported macOS architecture: $MACHINE (x86_64 and arm64 are supported)." ;;
    Linux:*) fail "Unsupported Linux architecture: $MACHINE (x86_64 and arm64 are supported)." ;;
    *) fail "Unsupported operating system: $OS_NAME (macOS and glibc Linux are supported)." ;;
esac

if [ "$PLATFORM" = linux ]; then
    if ! have getconf || ! getconf GNU_LIBC_VERSION >/dev/null 2>&1; then
        fail "This installer requires glibc Linux; musl/Alpine is not supported."
    fi
    FFMPEG_ROOT=${XDG_DATA_HOME:-$HOME/.local/share}/msr-dl/ffmpeg
else
    FFMPEG_ROOT=$HOME/Library/Application\ Support/msr-dl/ffmpeg
fi
FFMPEG=$FFMPEG_ROOT/bin/ffmpeg
if [ "$PLATFORM" = macos ]; then
    FFMPEG_SOURCE_URL="https://ffmpeg.martin-riedl.de/redirect/latest/macos/$FFMPEG_ARCH/release/ffmpeg.zip"
else
    FFMPEG_ASSET=ffmpeg-master-latest-$FFMPEG_ARCH-gpl.tar.xz
    FFMPEG_SOURCE_URL=$BTBN_RELEASE_URL/$FFMPEG_ASSET
fi

have curl || fail "curl is required."
if [ "$PLATFORM" = macos ]; then
    have unzip || fail "unzip is required on macOS."
else
    have tar || fail "tar with xz support is required on Linux."
fi

TEMP_DIRECTORY=$(mktemp -d "${TMPDIR:-/tmp}/msr-dl-install.XXXXXXXX") || fail "Could not create a temporary directory."

step "Checking uv"
UV=$(find_uv || true)
if [ -z "$UV" ]; then
    printf '  Installing uv...\n'
    curl -LsSf "$UV_INSTALLER_URL" | sh
    UV=$(find_uv || true)
    [ -n "$UV" ] || fail "uv was installed but could not be found."
fi
printf '  %s\n' "$("$UV" --version)"
TOOL_BIN=$("$UV" tool dir --bin)
[ -n "$TOOL_BIN" ] || fail "uv did not report its tool executable directory."
PATH=$TOOL_BIN:$PATH
export PATH
"$UV" tool update-shell >/dev/null

step "Checking FFmpeg"
if [ "${MSR_DL_INSTALL_FORCE_FFMPEG:-0}" != 1 ] && have ffmpeg; then
    FFMPEG=$(command -v ffmpeg)
    printf '  Using FFmpeg from PATH.\n'
elif [ -x "$FFMPEG" ]; then
    printf '  Using the existing msr-dl FFmpeg installation.\n'
else
    printf '  Installing FFmpeg for msr-dl...\n'
    FFMPEG_ARCHIVE=$TEMP_DIRECTORY/ffmpeg-archive
    FFMPEG_CHECKSUM=$TEMP_DIRECTORY/ffmpeg.sha256
    FFMPEG_EXTRACT=$TEMP_DIRECTORY/ffmpeg-extracted
    mkdir "$FFMPEG_EXTRACT"

    if [ "$PLATFORM" = macos ]; then
        EFFECTIVE_URL=$(curl -LsSf -w '%{url_effective}' -o "$FFMPEG_ARCHIVE" "$FFMPEG_SOURCE_URL")
        FFMPEG_SOURCE_URL=$EFFECTIVE_URL
        curl -LsSf -o "$FFMPEG_CHECKSUM" "$EFFECTIVE_URL.sha256"
        (cd "$FFMPEG_EXTRACT" && unzip -q "$FFMPEG_ARCHIVE")
    else
        curl -LsSf -o "$FFMPEG_ARCHIVE" "$FFMPEG_SOURCE_URL"
        curl -LsSf -o "$FFMPEG_CHECKSUM" "$BTBN_RELEASE_URL/checksums.sha256"
        tar -xJf "$FFMPEG_ARCHIVE" -C "$FFMPEG_EXTRACT" || fail "tar must support xz archives."
    fi

    EXPECTED_HASH=$(awk -v name="${FFMPEG_ASSET:-ffmpeg.zip}" '
        NF >= 1 && ($2 == name || $2 == "*" name || NF == 1) { print $1 }
    ' "$FFMPEG_CHECKSUM")
    case "$EXPECTED_HASH" in
        *[!0-9A-Fa-f]*|'') fail "The FFmpeg checksum file is invalid." ;;
    esac
    [ "${#EXPECTED_HASH}" -eq 64 ] || fail "The FFmpeg checksum file is invalid."
    ACTUAL_HASH=$(sha256_file "$FFMPEG_ARCHIVE")
    [ "$(printf '%s' "$ACTUAL_HASH" | tr 'A-F' 'a-f')" = "$(printf '%s' "$EXPECTED_HASH" | tr 'A-F' 'a-f')" ] || fail "The downloaded FFmpeg archive failed SHA-256 verification."

    FOUND_FFMPEG=$(find "$FFMPEG_EXTRACT" -type f -name ffmpeg | sed -n '1p')
    [ -n "$FOUND_FFMPEG" ] || fail "The FFmpeg archive did not contain an ffmpeg executable."
    [ "$(find "$FFMPEG_EXTRACT" -type f -name ffmpeg | wc -l | tr -d ' ')" = 1 ] || fail "The FFmpeg archive contained multiple ffmpeg executables."
    FFMPEG_PARENT=$(dirname "$FFMPEG_ROOT")
    mkdir -p "$FFMPEG_PARENT"
    FFMPEG_STAGING_ROOT=$FFMPEG_PARENT/.ffmpeg.$$
    mkdir -p "$FFMPEG_STAGING_ROOT/bin"
    cp "$FOUND_FFMPEG" "$FFMPEG_STAGING_ROOT/bin/ffmpeg"
    FOUND_FFMPEG_LICENSE=$(find "$FFMPEG_EXTRACT" -type f \( -iname 'LICENSE*' -o -iname 'COPYING*' \) | sed -n '1p')
    if [ -n "$FOUND_FFMPEG_LICENSE" ]; then
        cp "$FOUND_FFMPEG_LICENSE" "$FFMPEG_STAGING_ROOT/FFMPEG-LICENSE.txt"
    fi
    chmod 755 "$FFMPEG_STAGING_ROOT/bin/ffmpeg"
    if [ -e "$FFMPEG_ROOT" ]; then
        rm -rf -- "$FFMPEG_ROOT"
    fi
    mv "$FFMPEG_STAGING_ROOT" "$FFMPEG_ROOT"
    FFMPEG_STAGING_ROOT=
fi

if [ "$FFMPEG" = "$FFMPEG_ROOT/bin/ffmpeg" ]; then
    printf '%s\n' \
        'FFmpeg is third-party software and is not covered by the msr-dl license.' \
        "Binary source: $FFMPEG_SOURCE_URL" \
        'License and source information: https://ffmpeg.org/legal.html' \
        >"$FFMPEG_ROOT/FFMPEG-NOTICE.txt"
fi

step "Checking the latest msr-dl release"
RELEASE_JSON=$TEMP_DIRECTORY/release.json
RELEASE_INFO=$TEMP_DIRECTORY/release-info
PARSER=$TEMP_DIRECTORY/parse-release.py
curl -LsSf -H 'Accept: application/vnd.github+json' -H 'User-Agent: msr-dl-installer' -o "$RELEASE_JSON" "$LATEST_RELEASE_API"
cat >"$PARSER" <<'PY'
import json
import re
import sys

release = json.load(open(sys.argv[1], encoding="utf-8"))
if release.get("draft") or release.get("prerelease"):
    raise SystemExit("GitHub returned a draft or prerelease as the latest release")
match = re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", release.get("tag_name", ""))
if not match:
    raise SystemExit("The latest release tag is not stable SemVer")
version = ".".join(match.groups())
name = f"msr_dl-{version}-py3-none-any.whl"
assets = [asset for asset in release.get("assets", []) if asset.get("name") == name]
if len(assets) != 1:
    raise SystemExit(f"The release must contain exactly one {name} asset")
digest = assets[0].get("digest", "")
if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
    raise SystemExit("The release wheel does not have a valid SHA-256 digest")
print(version)
print(name)
print(assets[0]["browser_download_url"])
print(digest.removeprefix("sha256:"))
PY
"$UV" run --quiet --no-project --managed-python --python 3.13 python "$PARSER" "$RELEASE_JSON" >"$RELEASE_INFO" || fail "Could not validate the latest GitHub release."
LATEST_VERSION=$(sed -n '1p' "$RELEASE_INFO")
WHEEL_NAME=$(sed -n '2p' "$RELEASE_INFO")
WHEEL_URL=$(sed -n '3p' "$RELEASE_INFO")
EXPECTED_WHEEL_HASH=$(sed -n '4p' "$RELEASE_INFO")
printf '  Latest version: %s\n' "$LATEST_VERSION"

step "Installing or updating msr-dl"
MSR_DL=$TOOL_BIN/msr-dl
INSTALLED_VERSION=
if [ -x "$MSR_DL" ]; then
    INSTALLED_OUTPUT=$("$MSR_DL" --version)
    INSTALLED_VERSION=${INSTALLED_OUTPUT#msr-dl }
    [ "$INSTALLED_VERSION" != "$INSTALLED_OUTPUT" ] || fail "Could not read the installed msr-dl version: $INSTALLED_OUTPUT"
fi
VERSION_DECISION=$("$UV" run --quiet --no-project --managed-python --python 3.13 python - "$INSTALLED_VERSION" "$LATEST_VERSION" <<'PY'
import re
import sys

def version(value):
    match = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value)
    if not match:
        raise SystemExit(f"Invalid installed version: {value}")
    return tuple(map(int, match.groups()))

print("install" if not sys.argv[1] or version(sys.argv[1]) < version(sys.argv[2]) else "same" if version(sys.argv[1]) == version(sys.argv[2]) else "newer")
PY
)
if [ "$VERSION_DECISION" = install ]; then
    WHEEL_PATH=$TEMP_DIRECTORY/$WHEEL_NAME
    curl -LsSf -o "$WHEEL_PATH" "$WHEEL_URL"
    ACTUAL_WHEEL_HASH=$(sha256_file "$WHEEL_PATH")
    [ "$(printf '%s' "$ACTUAL_WHEEL_HASH" | tr 'A-F' 'a-f')" = "$(printf '%s' "$EXPECTED_WHEEL_HASH" | tr 'A-F' 'a-f')" ] || fail "The downloaded wheel failed SHA-256 verification."
    "$UV" tool install --quiet --force "$WHEEL_PATH"
    printf '  Installed msr-dl %s.\n' "$LATEST_VERSION"
elif [ "$VERSION_DECISION" = same ]; then
    printf '  msr-dl %s is already up to date.\n' "$INSTALLED_VERSION"
else
    printf '  Keeping newer installed version %s.\n' "$INSTALLED_VERSION"
fi

step "Verifying the installation"
printf '  %s\n' "$("$UV" --version)"
printf '  %s\n' "$("$FFMPEG" -version | sed -n '1p')"
printf '  %s\n' "$("$MSR_DL" --version)"
printf '\nInstallation complete. Open a new terminal and run: msr-dl --help\n'
