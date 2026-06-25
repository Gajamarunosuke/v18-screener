import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sector_heatmap import SectorHeatmap, aggregate_sector_history, render_sector_heatmap, sector_rank_label


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

    def test_sector_rank_label_shows_top_rank_and_10_day_ratio(self):
        rows = [
            ["Date", "Code"],
            ["2026-06-12", "1001"],
            ["2026-06-12", "1002"],
        ]
        hm = aggregate_sector_history(
            rows,
            {"1001": "Insurance", "1002": "Insurance"},
            sector_denominators={"Insurance": 10},
            date_header="Date",
            code_header="Code",
        )

        self.assertEqual(sector_rank_label(hm, "Insurance", 1), "#01 10d 13.3%")

    def test_calculates_streak_from_latest_trading_day(self):
        rows = [
            ["日付", "コード"],
            ["2026-06-09", "1001"],
            ["2026-06-10", "1001"],
            ["2026-06-10", "2001"],
            ["2026-06-11", "1001"],
            ["2026-06-12", "1001"],
            ["2026-06-12", "2001"],
        ]
        sector_map = {
            "1001": "銀行業",
            "2001": "小売業",
        }

        hm = aggregate_sector_history(rows, sector_map)

        self.assertEqual(hm.streaks["銀行業"], 4)
        self.assertEqual(hm.streaks["小売業"], 1)

    def test_streak_is_zero_when_sector_is_not_lit_on_latest_day(self):
        rows = [
            ["日付", "コード"],
            ["2026-06-11", "1001"],
            ["2026-06-12", "2001"],
        ]
        sector_map = {
            "1001": "銀行業",
            "2001": "小売業",
        }

        hm = aggregate_sector_history(rows, sector_map)

        self.assertEqual(hm.streaks["銀行業"], 0)
        self.assertEqual(hm.streaks["小売業"], 1)

    def test_us_symbols_with_custom_normalizer_and_header(self):
        from sector_heatmap import normalize_us_symbol

        rows = [
            ["日付", "Symbol"],
            ["2026-06-12", "AAPL"],
            ["2026-06-12", "MMM"],    # 3文字: zfill(4)で壊れてはいけない
            ["2026-06-12", "BRK.B"],  # ドット→ハイフン正規化が必要
        ]
        sector_map = {
            "AAPL": "Information Technology",
            "MMM": "Industrials",
            "BRK-B": "Financials",
        }
        denominators = {"Information Technology": 72, "Industrials": 80, "Financials": 76}

        hm = aggregate_sector_history(
            rows, sector_map,
            sector_denominators=denominators,
            code_normalizer=normalize_us_symbol,
            code_header="Symbol",
        )

        self.assertEqual(hm.daily_totals, [3])
        self.assertEqual(set(hm.sectors), {"Information Technology", "Industrials", "Financials"})
        self.assertEqual(hm.counts["Financials"][0], 1)   # BRK.B→BRK-B が一致
        self.assertEqual(hm.counts["Industrials"][0], 1)  # MMM がzfillで壊れていない

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
