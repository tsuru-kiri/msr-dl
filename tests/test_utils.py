from __future__ import annotations

import unittest

from monster_siren.utils import (
    album_directory_name,
    normalize_album_name,
    safe_filename,
    song_stem,
)


class AlbumNameTests(unittest.TestCase):
    def test_only_leading_and_trailing_ascii_spaces_are_removed(self) -> None:
        self.assertEqual(normalize_album_name("  A  B  "), "A  B")
        self.assertEqual(normalize_album_name("\tAlbum\t"), "\tAlbum\t")
        no_break_spaces = "\N{NO-BREAK SPACE}Album\N{NO-BREAK SPACE}"
        self.assertEqual(normalize_album_name(no_break_spaces), no_break_spaces)


class FilenameTests(unittest.TestCase):
    def test_cids_disambiguate_sanitized_names(self) -> None:
        self.assertNotEqual(
            album_directory_name("A/B", "1"),
            album_directory_name("A:B", "2"),
        )
        self.assertNotEqual(
            song_stem("Same", "one", 1),
            song_stem("Same", "two", 2),
        )

    def test_windows_reserved_name_is_escaped(self) -> None:
        self.assertEqual(safe_filename("CON"), "_CON")

    def test_final_components_fit_common_filesystem_byte_limit(self) -> None:
        self.assertLessEqual(
            len(album_directory_name("가" * 200, "a" * 100).encode("utf-8")),
            240,
        )
        self.assertLessEqual(
            len(song_stem("곡" * 200, "s" * 100, 1).encode("utf-8")),
            230,
        )

    def test_unsafe_cids_remain_unique_after_sanitization(self) -> None:
        self.assertNotEqual(
            album_directory_name("Album", "A/B"),
            album_directory_name("Album", "A:B"),
        )


if __name__ == "__main__":
    unittest.main()
