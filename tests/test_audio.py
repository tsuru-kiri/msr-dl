from __future__ import annotations

import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
from mutagen.id3 import APIC, ID3
from PIL import Image

from monster_siren.audio import (
    apply_prts_metadata,
    convert_wav_to_flac,
    ensure_ffmpeg,
    validate_audio,
    write_metadata,
)


class AudioMetadataTests(unittest.TestCase):
    @staticmethod
    def _wav(path: Path) -> None:
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"\x00\x00" * 800)

    @staticmethod
    def _cover(path: Path) -> None:
        Image.new("RGB", (2, 2), "black").save(path)

    def test_prts_release_date_overwrites_existing_flac_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav = root / "audio.wav"
            self._wav(wav)
            audio = convert_wav_to_flac(wav)
            tags = FLAC(audio)
            tags["date"] = "2020-01-01"
            tags.save()
            cover = root / "cover.png"
            self._cover(cover)

            write_metadata(
                audio,
                album="Album",
                title="Song",
                album_artists=["Artist"],
                artists=["Artist"],
                track_number=1,
                cover_path=cover,
                lyric_path=None,
                release_date="2023-11-25",
            )

            self.assertEqual(FLAC(audio)["date"], ["2023-11-25"])

    def test_valid_source_flac_date_is_preserved_without_prts_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav = root / "audio.wav"
            self._wav(wav)
            audio = convert_wav_to_flac(wav)
            tags = FLAC(audio)
            tags["date"] = "2022-12"
            tags.save()
            cover = root / "cover.png"
            self._cover(cover)

            write_metadata(
                audio,
                album="Album",
                title="Song",
                album_artists=["Artist"],
                artists=["Artist"],
                track_number=1,
                cover_path=cover,
                lyric_path=None,
                release_date=None,
            )

            self.assertEqual(FLAC(audio)["date"], ["2022-12"])

    def test_wav_production_date_is_not_copied_to_flac(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.wav"
            dated = root / "dated.wav"
            self._wav(source)
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-i",
                    str(source),
                    "-metadata",
                    "date=2565-05-23",
                    str(dated),
                ],
                check=True,
            )

            audio = convert_wav_to_flac(dated)

            self.assertNotIn("date", FLAC(audio))

    def test_prts_only_update_preserves_unmanaged_flac_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav = root / "audio.wav"
            self._wav(wav)
            audio = convert_wav_to_flac(wav)
            tags = FLAC(audio)
            tags["album"] = "Album"
            tags["title"] = "Song"
            tags["albumartist"] = "MSR Artist"
            tags["artist"] = "Old fallback"
            tags["tracknumber"] = "7"
            tags["custom"] = "keep"
            tags.save()

            apply_prts_metadata(
                audio,
                release_date="2024-01-02",
                album_artists=None,
                artists=["PRTS Artist"],
            )

            updated = FLAC(audio)
            self.assertEqual(updated["date"], ["2024-01-02"])
            self.assertEqual(updated["albumartist"], ["MSR Artist"])
            self.assertEqual(updated["artist"], ["PRTS Artist"])
            self.assertEqual(updated["album"], ["Album"])
            self.assertEqual(updated["title"], ["Song"])
            self.assertEqual(updated["tracknumber"], ["7"])
            self.assertEqual(updated["custom"], ["keep"])

    def test_full_update_can_preserve_prts_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav = root / "audio.wav"
            self._wav(wav)
            audio = convert_wav_to_flac(wav)
            tags = FLAC(audio)
            tags["date"] = "2021-03-04"
            tags["albumartist"] = "PRTS Album Artist"
            tags["artist"] = "PRTS Song Artist"
            tags.save()
            cover = root / "cover.png"
            self._cover(cover)

            write_metadata(
                audio,
                album="New Album",
                title="New Song",
                album_artists=None,
                artists=None,
                track_number=2,
                cover_path=cover,
                lyric_path=None,
                preserve_date=True,
            )

            updated = FLAC(audio)
            self.assertEqual(updated["date"], ["2021-03-04"])
            self.assertEqual(updated["albumartist"], ["PRTS Album Artist"])
            self.assertEqual(updated["artist"], ["PRTS Song Artist"])
            self.assertEqual(updated["album"], ["New Album"])
            self.assertEqual(updated["title"], ["New Song"])
            self.assertEqual(updated["tracknumber"], ["2"])

    def test_ffmpeg_on_path_takes_precedence(self) -> None:
        with (
            patch("monster_siren.audio.which", return_value=r"C:\tools\ffmpeg.exe"),
            patch("monster_siren.audio.sys.platform", "win32"),
        ):
            self.assertEqual(ensure_ffmpeg(), r"C:\tools\ffmpeg.exe")

    def test_windows_uses_managed_ffmpeg_when_path_lookup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "msr-dl" / "ffmpeg" / "bin" / "ffmpeg.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()

            with (
                patch("monster_siren.audio.which", return_value=None),
                patch("monster_siren.audio.sys.platform", "win32"),
                patch.dict("os.environ", {"LOCALAPPDATA": directory}),
            ):
                self.assertEqual(ensure_ffmpeg(), str(executable))

    def test_macos_uses_managed_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = (
                Path(directory)
                / "Library"
                / "Application Support"
                / "msr-dl"
                / "ffmpeg"
                / "bin"
                / "ffmpeg"
            )
            executable.parent.mkdir(parents=True)
            executable.touch()

            with (
                patch("monster_siren.audio.which", return_value=None),
                patch("monster_siren.audio.sys.platform", "darwin"),
                patch("monster_siren.audio.Path.home", return_value=Path(directory)),
            ):
                self.assertEqual(ensure_ffmpeg(), str(executable))

    def test_linux_uses_default_managed_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = (
                Path(directory)
                / ".local"
                / "share"
                / "msr-dl"
                / "ffmpeg"
                / "bin"
                / "ffmpeg"
            )
            executable.parent.mkdir(parents=True)
            executable.touch()

            with (
                patch("monster_siren.audio.which", return_value=None),
                patch("monster_siren.audio.sys.platform", "linux"),
                patch("monster_siren.audio.Path.home", return_value=Path(directory)),
                patch.dict("os.environ", {}, clear=True),
            ):
                self.assertEqual(ensure_ffmpeg(), str(executable))

    def test_linux_honors_xdg_data_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "msr-dl" / "ffmpeg" / "bin" / "ffmpeg"
            executable.parent.mkdir(parents=True)
            executable.touch()

            with (
                patch("monster_siren.audio.which", return_value=None),
                patch("monster_siren.audio.sys.platform", "linux"),
                patch.dict("os.environ", {"XDG_DATA_HOME": directory}, clear=True),
            ):
                self.assertEqual(ensure_ffmpeg(), str(executable))

    def test_unsupported_platform_rejects_managed_ffmpeg(self) -> None:
        with (
            patch("monster_siren.audio.which", return_value=None),
            patch("monster_siren.audio.sys.platform", "freebsd13"),
            self.assertRaisesRegex(RuntimeError, "FFmpeg is required"),
        ):
            ensure_ffmpeg()

    def test_conversion_uses_resolved_ffmpeg_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wav = Path(directory) / "audio.wav"
            wav.touch()
            with (
                patch(
                    "monster_siren.audio.ensure_ffmpeg", return_value="managed-ffmpeg"
                ),
                patch("monster_siren.audio.subprocess.run") as run,
                patch("monster_siren.audio.FLAC"),
            ):
                convert_wav_to_flac(wav)

            self.assertEqual(run.call_args.args[0][0], "managed-ffmpeg")

    def test_validation_uses_resolved_ffmpeg_executable(self) -> None:
        with (
            patch("monster_siren.audio.ensure_ffmpeg", return_value="managed-ffmpeg"),
            patch("monster_siren.audio.detect_audio_type", return_value="mp3"),
            patch("monster_siren.audio.subprocess.run") as run,
        ):
            validate_audio(Path("audio.mp3"))

        self.assertEqual(run.call_args.args[0][0], "managed-ffmpeg")

    def test_prts_only_update_preserves_mp3_tags_and_cover(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav = root / "audio.wav"
            self._wav(wav)
            audio = root / "audio.mp3"
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-i",
                    str(wav),
                    str(audio),
                ],
                check=True,
            )
            tags = EasyID3(audio)
            tags["album"] = "Album"
            tags["title"] = "Song"
            tags["albumartist"] = "MSR Artist"
            tags["artist"] = "Old fallback"
            tags["tracknumber"] = "3"
            tags.save()
            id3 = ID3(audio)
            id3.add(APIC(mime="image/png", type=3, desc="Cover", data=b"cover"))
            id3.save()

            apply_prts_metadata(
                audio,
                release_date="2024-01-02",
                album_artists=None,
                artists=["PRTS Artist"],
            )

            updated = EasyID3(audio)
            self.assertEqual(updated["date"], ["2024-01-02"])
            self.assertEqual(updated["albumartist"], ["MSR Artist"])
            self.assertEqual(updated["artist"], ["PRTS Artist"])
            self.assertEqual(updated["album"], ["Album"])
            self.assertEqual(updated["title"], ["Song"])
            self.assertEqual(updated["tracknumber"], ["3"])
            self.assertEqual(len(ID3(audio).getall("APIC")), 1)


if __name__ == "__main__":
    unittest.main()
