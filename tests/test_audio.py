from __future__ import annotations

import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from mutagen.flac import FLAC
from PIL import Image

from monster_siren.audio import convert_wav_to_flac, write_metadata


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


if __name__ == "__main__":
    unittest.main()
