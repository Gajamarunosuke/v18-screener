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
