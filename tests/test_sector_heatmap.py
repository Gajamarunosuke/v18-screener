import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sector_heatmap import SectorHeatmap, aggregate_sector_history, render_sector_heatmap


class AggregateSectorHistoryTests(unittest.TestCase):
    def test_aggregates_unique_codes_by_day_and_sector(self):
        rows = [
            ["日付", "実行時刻", "コード"],
            ["2026-06-08", "16:10", "8306"],
            ["2026-06-08", "16:10", "7182"],
            ["2026-06-08", "16:10", "8283"],
            ["2026-06-08", "16:20", "8306"],
            ["2026-06-09", "16:10", "8306"],
        ]
        sector_map = {
            "8306": "銀行業",
            "7182": "銀行業",
            "8283": "小売業",
        }

        heatmap = aggregate_sector_history(rows, sector_map, max_days=10, max_sectors=15)

        self.assertEqual(heatmap.dates, ["2026-06-08", "2026-06-09"])
        self.assertEqual(heatmap.daily_totals, [3, 1])
        self.assertEqual(heatmap.sectors[:2], ["銀行業", "小売業"])
        self.assertEqual(heatmap.counts["銀行業"], [2, 1])
        self.assertEqual(heatmap.counts["小売業"], [1, 0])

    def test_keeps_only_latest_trading_days(self):
        rows = [["日付", "実行時刻", "コード"]]
        sector_map = {}
        for day in range(1, 13):
            code = f"{8000 + day}"
            rows.append([f"2026-06-{day:02d}", "16:10", code])
            sector_map[code] = "銀行業"

        heatmap = aggregate_sector_history(rows, sector_map, max_days=10, max_sectors=15)

        self.assertEqual(heatmap.dates[0], "2026-06-03")
        self.assertEqual(heatmap.dates[-1], "2026-06-12")
        self.assertEqual(len(heatmap.dates), 10)

    def test_normalizes_google_sheets_date_format(self):
        rows = [
            ["日付", "実行時刻", "コード"],
            ["2026/06/12", "16:10", "8306"],
        ]

        heatmap = aggregate_sector_history(rows, {"8306": "銀行業"})

        self.assertEqual(heatmap.dates, ["2026-06-12"])

    def test_ignores_empty_and_unknown_rows(self):
        rows = [
            ["日付", "実行時刻", "コード"],
            ["2026-06-12", "16:10", "本日の候補なし"],
            ["2026-06-12", "16:10", "9999"],
            ["", "", ""],
        ]

        heatmap = aggregate_sector_history(rows, {}, max_days=10, max_sectors=15)

        self.assertEqual(heatmap.dates, ["2026-06-12"])
        self.assertEqual(heatmap.daily_totals, [0])
        self.assertEqual(heatmap.sectors, [])

    def test_hybrid_ratio_reorders_by_denominator(self):
        rows = [
            ["日付", "コード"],
            ["2026-06-12", "1001"],
            ["2026-06-12", "1002"],
            ["2026-06-12", "1003"],  # 電機 3件
            ["2026-06-12", "1004"],
            ["2026-06-12", "1005"],  # 保険 2件
        ]
        sector_map = {
            "1001": "電機", "1002": "電機", "1003": "電機",
            "1004": "保険", "1005": "保険",
        }
        denominators = {"電機": 200, "保険": 10}

        hm = aggregate_sector_history(rows, sector_map, sector_denominators=denominators)

        # 絶対数では電機(3)>保険(2)だが、母数補正後は保険が上位
        self.assertEqual(hm.sectors[0], "保険")
        self.assertEqual(hm.counts["電機"][0], 3)        # 数字は絶対数のまま
        self.assertEqual(hm.ratios["保険"][0], round(2 / 15 * 100, 2))   # 13.33%
        self.assertEqual(hm.ratios["電機"][0], round(3 / 205 * 100, 2))  # 1.46%
        self.assertEqual(hm.daily_leaders[0], ("保険", 2))  # リーダーも割合ベース
        self.assertEqual(hm.denominators["保険"], 10)

    def test_without_denominator_keeps_absolute_mode(self):
        rows = [
            ["日付", "コード"],
            ["2026-06-12", "1001"],
            ["2026-06-12", "1002"],
            ["2026-06-12", "1003"],
            ["2026-06-12", "1004"],
            ["2026-06-12", "1005"],
        ]
        sector_map = {
            "1001": "電機", "1002": "電機", "1003": "電機",
            "1004": "保険", "1005": "保険",
        }

        hm = aggregate_sector_history(rows, sector_map)

        self.assertEqual(hm.sectors[0], "電機")  # 絶対数順
        self.assertEqual(hm.ratios, {})
        self.assertEqual(hm.denominators, {})

    def test_renders_hybrid_png(self):
        hm = aggregate_sector_history(
            [
                ["日付", "コード"],
                ["2026-06-11", "1001"],
                ["2026-06-12", "1004"],
                ["2026-06-12", "1005"],
            ],
            {"1001": "電機", "1004": "保険", "1005": "保険"},
            sector_denominators={"電機": 200, "保険": 10},
        )
        with TemporaryDirectory() as directory:
            output = Path(directory) / "hybrid.png"
            render_sector_heatmap(hm, output, title="V18 業種シグナル・ヒートマップ")
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 1_000)

    def test_renders_png(self):
        heatmap = SectorHeatmap(
            dates=["2026-06-11", "2026-06-12"],
            daily_totals=[3, 5],
            sectors=["銀行業", "小売業"],
            counts={"銀行業": [2, 4], "小売業": [1, 1]},
            daily_leaders=[("銀行業", 2), ("銀行業", 4)],
        )

        with TemporaryDirectory() as directory:
            output = Path(directory) / "heatmap.png"
            render_sector_heatmap(heatmap, output)

            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 1_000)


if __name__ == "__main__":
    unittest.main()
