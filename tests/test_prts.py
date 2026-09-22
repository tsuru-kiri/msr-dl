from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from monster_siren.prts import (
    PRTS_MUSIC_URL,
    build_snapshot,
    fetch_music_table,
    parse_music_table,
    update_metadata_snapshot,
)

MUSIC_TABLE = """
<html><body>
<table><tr><th>unrelated</th></tr></table>
<table>
  <tr>
    <th>用途</th><th>标题</th><th>艺术家</th><th>商品编号</th>
    <th>UPC</th><th>发布日期</th>
  </tr>
  <tr>
    <td rowspan="3">ED</td>
    <td><a>Fleeting Wish</a></td>
    <td rowspan="2">フロストノヴァ<br>(CV:高垣彩陽)</td>
    <td>LEGD-0056</td><td>1</td>
    <td rowspan="3">2023年11月25日</td>
  </tr>
  <tr>
    <td><a>Fleeting Wish</a></td><td>NO INFO</td><td>2</td>
  </tr>
  <tr>
    <td><a>Fleeting Wish (Monster Siren Records)</a></td>
    <td>kiyo</td><td>NO INFO</td><td>3</td>
  </tr>
  <tr>
    <td>OST</td><td><a>音律联觉-灯下定影原声EP</a></td>
    <td></td><td>NO INFO</td><td>4</td><td>2022年12月10日</td>
  </tr>
</table>
</body></html>
"""


class PRTSTests(unittest.TestCase):
    def test_fetch_uses_only_the_music_overview_url(self) -> None:
        response = Mock(text=MUSIC_TABLE, content=MUSIC_TABLE.encode("utf-8"))
        response.raise_for_status = Mock()
        session = Mock()
        session.get.return_value = response

        self.assertEqual(fetch_music_table(session), MUSIC_TABLE)
        session.get.assert_called_once_with(PRTS_MUSIC_URL, timeout=(10.0, 120.0))
        session.mount.assert_not_called()

    def test_fetch_retries_transient_failures_with_owned_session(self) -> None:
        response = Mock(text=MUSIC_TABLE, content=MUSIC_TABLE.encode("utf-8"))
        response.raise_for_status = Mock()
        session = Mock()
        session.get.return_value = response

        with patch("monster_siren.prts.requests.Session", return_value=session):
            self.assertEqual(fetch_music_table(), MUSIC_TABLE)

        session.mount.assert_called_once()
        prefix, adapter = session.mount.call_args.args
        self.assertEqual(prefix, "https://")
        retry = adapter.max_retries
        self.assertEqual(retry.total, 4)
        self.assertEqual(retry.connect, 4)
        self.assertEqual(retry.read, 4)
        self.assertEqual(retry.status, 4)
        self.assertEqual(retry.backoff_factor, 0.8)
        self.assertEqual(retry.status_forcelist, (429, 500, 502, 503, 504))
        self.assertEqual(retry.allowed_methods, frozenset({"GET"}))
        self.assertTrue(retry.respect_retry_after_header)
        session.close.assert_called_once()

    def test_rowspans_are_expanded_and_duplicate_editions_are_merged(self) -> None:
        releases = parse_music_table(MUSIC_TABLE)

        self.assertEqual(
            releases["Fleeting Wish"].release_date,
            "2023-11-25",
        )
        self.assertEqual(
            releases["Fleeting Wish"].artists,
            ("塞壬唱片-MSR", "フロストノヴァ", "(CV:高垣彩陽)"),
        )
        self.assertEqual(
            releases["Fleeting Wish (Monster Siren Records)"].artists,
            ("塞壬唱片-MSR", "kiyo"),
        )

    def test_empty_prts_artists_default_to_monster_siren(self) -> None:
        releases = parse_music_table(MUSIC_TABLE)

        self.assertEqual(
            releases["音律联觉-灯下定影原声EP"].artists,
            ("塞壬唱片-MSR",),
        )

    def test_album_catalog_without_artist_column_uses_default_artist(self) -> None:
        html = """
        <table>
          <tr><th>标题</th><th>发布日期</th><th>相关活动</th></tr>
          <tr>
            <td>音律联觉-灯下定影原声EP</td>
            <td>2022年12月10日</td><td>灯下定影</td>
          </tr>
          <tr>
            <td>出苍白海OST</td><td>2024年12月13日</td><td>出苍白海</td>
          </tr>
        </table>
        """

        releases = parse_music_table(html)

        self.assertEqual(
            releases["音律联觉-灯下定影原声EP"].artists,
            ("塞壬唱片-MSR",),
        )
        snapshot, unmatched = build_snapshot(
            [
                {
                    "cid": "0248",
                    "name": "2022明日方舟音律联觉-灯下定影原声EP",
                },
                {"cid": "8926", "name": "A Toda Vela"},
            ],
            releases,
            {"0248": "音律联觉-灯下定影原声EP", "8926": "出苍白海OST"},
        )
        self.assertEqual(set(snapshot["albums"]), {"0248", "8926"})
        self.assertEqual(unmatched, [])

    def test_digital_edition_note_after_release_date_is_accepted(self) -> None:
        html = """
        <table>
          <tr><th>标题</th><th>发布日期</th></tr>
          <tr><td>Digital Album</td><td>2019年6月20日（数字版）</td></tr>
        </table>
        """

        releases = parse_music_table(html)

        self.assertEqual(releases["Digital Album"].release_date, "2019-06-20")

    def test_all_music_tables_on_the_overview_page_are_combined(self) -> None:
        second_table = """
        <table>
          <tr><th>标题</th><th>艺术家</th><th>发布日期</th></tr>
          <tr><td>Later Album</td><td>Later Artist</td><td>2024年1月2日</td></tr>
        </table>
        """

        releases = parse_music_table(
            MUSIC_TABLE.replace("</body>", second_table + "</body>")
        )

        self.assertIn("Fleeting Wish", releases)
        self.assertEqual(releases["Later Album"].release_date, "2024-01-02")

    def test_year_heading_supplies_year_for_short_dates(self) -> None:
        html = """
        <h2>EP</h2>
        <h3 id="2027">2027</h3>
        <table>
          <tr><th>标题</th><th>艺术家</th><th>发布日期</th></tr>
          <tr><td>Future Album</td><td>Artist</td><td>1月5日</td></tr>
        </table>
        <h3 id="2028年">2028年</h3>
        <table>
          <tr><th>标题</th><th>艺术家</th><th>发布日期</th></tr>
          <tr><td>Later Album</td><td>Artist</td><td>12月31日</td></tr>
        </table>
        """

        releases = parse_music_table(html)

        self.assertEqual(releases["Future Album"].release_date, "2027-01-05")
        self.assertEqual(releases["Later Album"].release_date, "2028-12-31")

    def test_short_date_without_active_year_heading_is_rejected(self) -> None:
        html = """
        <h3>2027</h3>
        <table>
          <tr><th>标题</th><th>艺术家</th><th>发布日期</th></tr>
          <tr><td>First</td><td>Artist</td><td>1月5日</td></tr>
        </table>
        <h2>单曲</h2>
        <table>
          <tr><th>标题</th><th>艺术家</th><th>发布日期</th></tr>
          <tr><td>Missing Year</td><td>Artist</td><td>2月1日</td></tr>
        </table>
        """

        with self.assertRaisesRegex(ValueError, "no year heading"):
            parse_music_table(html)

    def test_title_uses_first_line_and_keeps_msr_suffix(self) -> None:
        html = """
        <table>
          <tr><th>标题</th><th>艺术家</th><th>发布日期</th></tr>
          <tr>
            <td><a>Speed of Light</a><br>飞驰如光</td>
            <td>Artist</td><td>2019年11月19日</td>
          </tr>
          <tr>
            <td><a>Fleeting Wish</a><br>(Monster Siren Records)</td>
            <td>kiyo</td><td>2023年11月25日</td>
          </tr>
          <tr>
            <td><a>Operation Barrenland<br>(W&amp;W Soundtrack Mix)</a></td>
            <td>W&amp;W</td><td>2020年3月9日</td>
          </tr>
        </table>
        """

        releases = parse_music_table(html)

        self.assertIn("Speed of Light", releases)
        self.assertNotIn("Speed of Light 飞驰如光", releases)
        self.assertIn("Fleeting Wish (Monster Siren Records)", releases)
        self.assertIn("Operation Barrenland", releases)

    def test_commercial_edition_suffixes_prevent_false_date_conflicts(self) -> None:
        html = """
        <table>
          <tr><th>标题</th><th>艺术家</th><th>发布日期</th></tr>
          <tr><td>Alive</td><td>ReoNa</td><td>2022年11月5日</td></tr>
          <tr>
            <td>Alive<br>(Special Edition)</td>
            <td>ReoNa</td><td>2022年12月7日</td>
          </tr>
          <tr>
            <td>Alive<br>[初回生産限定盤]</td>
            <td>ReoNa</td><td>2022年12月7日</td>
          </tr>
          <tr>
            <td>Alive<br>[通常盤]</td>
            <td>ReoNa</td><td>2022年12月7日</td>
          </tr>
          <tr>
            <td>Alive<br>[期間生産限定盤]</td>
            <td>ReoNa</td><td>2022年12月7日</td>
          </tr>
        </table>
        """

        releases = parse_music_table(html)

        self.assertEqual(releases["Alive"].release_date, "2022-11-05")
        self.assertIn("Alive (Special Edition)", releases)
        self.assertIn("Alive [初回生産限定盤]", releases)
        self.assertIn("Alive [通常盤]", releases)
        self.assertIn("Alive [期間生産限定盤]", releases)

    def test_snapshot_uses_exact_names_and_cid_aliases(self) -> None:
        releases = parse_music_table(MUSIC_TABLE)
        albums = [
            {"cid": "7774", "name": "Fleeting Wish"},
            {"cid": "spaced", "name": " Fleeting Wish "},
            {"cid": "0242", "name": "Fleeting Wish (Monster Siren Records)"},
            {
                "cid": "0248",
                "name": "2022明日方舟音律联觉-灯下定影原声EP",
            },
            {"cid": "missing", "name": "Not Present"},
        ]
        aliases = {"0248": "音律联觉-灯下定影原声EP"}

        snapshot, unmatched = build_snapshot(albums, releases, aliases)

        self.assertEqual(
            snapshot["albums"]["0242"]["artists"], ["塞壬唱片-MSR", "kiyo"]
        )
        self.assertEqual(
            snapshot["albums"]["0248"]["prtsTitle"],
            "音律联觉-灯下定影原声EP",
        )
        self.assertEqual(snapshot["albums"]["spaced"]["msrName"], "Fleeting Wish")
        self.assertEqual(snapshot["albums"]["spaced"]["prtsTitle"], "Fleeting Wish")
        self.assertEqual(unmatched, [("missing", "Not Present")])

    def test_conflicting_duplicate_dates_are_rejected(self) -> None:
        html = MUSIC_TABLE.replace(
            "<td><a>Fleeting Wish</a></td><td>NO INFO</td><td>2</td>",
            "<td><a>Fleeting Wish</a></td><td>NO INFO</td><td>2</td>"
            "<td>2024年1月1日</td>",
        ).replace('rowspan="3">2023年11月25日', 'rowspan="1">2023年11月25日')

        with self.assertRaisesRegex(ValueError, "Conflicting release dates"):
            parse_music_table(html)

    def test_update_fetches_each_catalog_once_and_publishes_snapshot(self) -> None:
        class API:
            def __enter__(self) -> API:
                return self

            def __exit__(self, *exc_info: object) -> None:
                pass

            def get_albums(self) -> list[dict[str, object]]:
                return [{"cid": "7774", "name": "Fleeting Wish"}]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aliases = root / "aliases.json"
            aliases.write_text('{"version": 1, "albums": {}}', encoding="utf-8")
            snapshot = root / "snapshot.json"
            with (
                patch("monster_siren.prts.MonsterSirenAPI", API),
                patch(
                    "monster_siren.prts.fetch_music_table", return_value=MUSIC_TABLE
                ) as fetch,
            ):
                report = update_metadata_snapshot(snapshot, aliases, check=False)

            fetch.assert_called_once_with()
            self.assertEqual(report.albums, 1)
            self.assertEqual(report.unmatched, [])
            self.assertTrue(snapshot.is_file())


if __name__ == "__main__":
    unittest.main()
