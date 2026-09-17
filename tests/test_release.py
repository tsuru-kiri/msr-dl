from __future__ import annotations

import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).parents[1] / ".github" / "scripts" / "release.py"
SPEC = importlib.util.spec_from_file_location("release_helpers", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release
SPEC.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_parse_version_accepts_stable_semver(self) -> None:
        self.assertEqual(release.parse_version("12.3.40"), (12, 3, 40))

    def test_parse_version_rejects_prefix_suffix_and_leading_zeroes(self) -> None:
        for value in ("v1.2.3", "1.2", "1.2.3-rc1", "01.2.3"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                release.parse_version(value)

    def test_validate_requires_an_increase_and_synchronized_sources(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "monster_siren").mkdir()
            (root / "pyproject.toml").write_text(
                '[project]\nname = "msr-dl"\nversion = "1.2.3"\n',
                encoding="utf-8",
            )
            init_path = root / "monster_siren" / "__init__.py"
            init_path.write_text('__version__ = "1.2.3"\n', encoding="utf-8")

            release.validate_new_version(root, "1.2.4")
            with self.assertRaises(ValueError):
                release.validate_new_version(root, "1.2.3")

            init_path.write_text('__version__ = "1.2.2"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                release.validate_new_version(root, "1.2.4")

    def test_sync_package_version_updates_only_assignment(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "monster_siren"
            package.mkdir()
            init_path = package / "__init__.py"
            init_path.write_text(
                '"""Package."""\n\n__version__ = "1.2.3"\n', encoding="utf-8"
            )

            release.sync_package_version(root, "2.0.0")

            self.assertEqual(
                init_path.read_text(encoding="utf-8"),
                '"""Package."""\n\n__version__ = "2.0.0"\n',
            )

    def test_previous_release_tag_skips_non_semver_tags(self) -> None:
        with patch.object(
            release,
            "git_output",
            return_value="nightly\nv1.2.3-rc1\nv1.2.2\nv1.0.0\n",
        ):
            self.assertEqual(release.previous_release_tag(Path.cwd(), "HEAD"), "v1.2.2")

    def test_changelog_uses_commit_messages_and_links(self) -> None:
        rendered = release.format_changelog(
            [("abcdef0123456789", "Add release workflow")],
            "owner/repository",
            "v1.0.0",
        )

        self.assertIn("## Changes since v1.0.0", rendered)
        self.assertIn("Add release workflow", rendered)
        self.assertIn(
            "https://github.com/owner/repository/commit/abcdef0123456789", rendered
        )
        self.assertIn("`abcdef0`", rendered)

    def test_render_homebrew_formula_uses_python_source_distribution(self) -> None:
        with TemporaryDirectory() as directory:
            assets = Path(directory)
            sdist = assets / "msr_dl-1.2.3.tar.gz"
            sdist.write_bytes(b"python source distribution")

            rendered = release.render_homebrew_formula("1.2.3", "owner/msr-dl", assets)

            self.assertIn('version "1.2.3"', rendered)
            self.assertIn("include Language::Python::Virtualenv", rendered)
            self.assertIn(sdist.name, rendered)
            self.assertIn(
                hashlib.sha256(b"python source distribution").hexdigest(), rendered
            )
            self.assertIn('depends_on "python@3.13"', rendered)
            self.assertIn('depends_on "pillow" => :no_linkage', rendered)
            self.assertIn('pypi_packages exclude_packages: "pillow"', rendered)
            self.assertIn("virtualenv_install_with_resources", rendered)
            self.assertNotIn("on_arm do", rendered)
            self.assertNotIn("on_intel do", rendered)

    def test_render_homebrew_formula_requires_source_distribution(self) -> None:
        with TemporaryDirectory() as directory:
            assets = Path(directory)
            (assets / "msr-dl-v1.2.3-macos-arm64.tar.gz").write_bytes(b"arm")

            with self.assertRaisesRegex(ValueError, "source distribution"):
                release.render_homebrew_formula("1.2.3", "owner/msr-dl", assets)

    def test_render_homebrew_formula_rejects_wrong_sdist_version(self) -> None:
        with TemporaryDirectory() as directory:
            assets = Path(directory)
            (assets / "msr_dl-1.2.2.tar.gz").write_bytes(b"old")

            with self.assertRaisesRegex(ValueError, "unexpected.*version"):
                release.render_homebrew_formula("1.2.3", "owner/msr-dl", assets)


if __name__ == "__main__":
    unittest.main()
