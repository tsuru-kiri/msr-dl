#!/usr/bin/env python3
"""Helpers used by the release workflow."""

from __future__ import annotations

import argparse
import re
import subprocess
import tomllib
from pathlib import Path

SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
INIT_VERSION_PATTERN = re.compile(r'(?m)^__version__ = "(?P<version>[^"]+)"$')


def parse_version(value: str) -> tuple[int, int, int]:
    """Parse a stable SemVer version without a prefix or suffix."""
    match = SEMVER_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(
            f"invalid version {value!r}; expected stable SemVer such as 1.2.3"
        )
    return tuple(int(part) for part in match.groups())


def project_version(project_root: Path) -> str:
    with (project_root / "pyproject.toml").open("rb") as source:
        return tomllib.load(source)["project"]["version"]


def package_version(project_root: Path) -> str:
    source = (project_root / "monster_siren" / "__init__.py").read_text(
        encoding="utf-8"
    )
    match = INIT_VERSION_PATTERN.search(source)
    if match is None:
        raise ValueError("monster_siren/__init__.py has no __version__ assignment")
    return match.group("version")


def validate_new_version(project_root: Path, value: str) -> None:
    requested = parse_version(value)
    current_value = project_version(project_root)
    current = parse_version(current_value)
    current_package = package_version(project_root)

    if current_package != current_value:
        raise ValueError(
            "project versions are out of sync: "
            f"pyproject.toml={current_value}, "
            f"monster_siren/__init__.py={current_package}"
        )
    if requested <= current:
        raise ValueError(
            f"release version {value} must be greater than current version "
            f"{current_value}"
        )


def sync_package_version(project_root: Path, value: str) -> None:
    parse_version(value)
    init_path = project_root / "monster_siren" / "__init__.py"
    source = init_path.read_text(encoding="utf-8")
    updated, replacements = INIT_VERSION_PATTERN.subn(
        f'__version__ = "{value}"', source
    )
    if replacements != 1:
        raise ValueError(
            "expected exactly one __version__ assignment in monster_siren/__init__.py"
        )
    init_path.write_text(updated, encoding="utf-8")


def git_output(project_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def previous_release_tag(project_root: Path, head: str) -> str | None:
    tags = git_output(
        project_root,
        "tag",
        "--merged",
        head,
        "--list",
        "v*",
        "--sort=-creatordate",
    ).splitlines()
    return next((tag for tag in tags if SEMVER_PATTERN.fullmatch(tag[1:])), None)


def release_commits(
    project_root: Path, head: str, previous_tag: str | None
) -> list[tuple[str, str]]:
    revision = f"{previous_tag}..{head}" if previous_tag else head
    fields = git_output(
        project_root,
        "log",
        "--reverse",
        "--format=%H%x00%s%x00",
        revision,
    ).split("\0")
    fields = [field.strip() for field in fields if field.strip()]
    if len(fields) % 2:
        raise ValueError("unexpected git log output while generating changelog")
    return list(zip(fields[::2], fields[1::2], strict=True))


def format_changelog(
    commits: list[tuple[str, str]], repository: str, previous_tag: str | None
) -> str:
    heading = f"## Changes since {previous_tag}" if previous_tag else "## Changes"
    lines = [heading, ""]
    if not commits:
        lines.append("No commits since the previous release.")
    else:
        for commit, subject in commits:
            url = f"https://github.com/{repository}/commit/{commit}"
            lines.append(f"- {subject} ([`{commit[:7]}`]({url}))")
    return "\n".join(lines) + "\n"


def write_changelog(
    project_root: Path, head: str, repository: str, output: Path
) -> None:
    previous_tag = previous_release_tag(project_root, head)
    commits = release_commits(project_root, head, previous_tag)
    output.write_text(
        format_changelog(commits, repository, previous_tag), encoding="utf-8"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate-version")
    validate.add_argument("version")

    sync = commands.add_parser("sync-package-version")
    sync.add_argument("version")

    changelog = commands.add_parser("changelog")
    changelog.add_argument("--head", required=True)
    changelog.add_argument("--repository", required=True)
    changelog.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    project_root = args.project_root.resolve()
    if args.command == "validate-version":
        validate_new_version(project_root, args.version)
    elif args.command == "sync-package-version":
        sync_package_version(project_root, args.version)
    else:
        write_changelog(project_root, args.head, args.repository, args.output)


if __name__ == "__main__":
    main()
