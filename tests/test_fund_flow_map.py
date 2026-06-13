import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fund_flow_map import build_fund_flow_history, render_fund_flow_map


class FundFlowHistoryTests(unittest.TestCase):
    def test_builds_rank_history_and_weekly_rank_changes(self):
        rows = [
            ["集計週", "取得日", "順位", "投信名", "運用会社", "資産タイプ"],
            ["2026/05/25～2026/05/31", "2026-06-01", "1", "全世界株式", "A社", "海外株式"],
            ["2026/05/25～2026/05/31", "2026-06-01", "3", "米国株式", "B社", "海外株式"],
            ["2026/06/01～2026/06/07", "2026-06-08", "2", "全世界株式", "A社", "海外株式"],
            ["2026/06/01～2026/06/07", "2026-06-08", "1", "米国株式", "B社", "海外株式"],
        ]

        history = build_fund_flow_history(rows, max_weeks=10, max_funds=15)

        self.assertEqual(history.weeks, ["05/31", "06/07"])
        self.assertEqual(history.funds, ["米国株式", "全世界株式"])
        self.assertEqual(history.ranks["米国株式"], [3, 1])
        self.assertEqual(history.changes["米国株式"], [None, 2])
        self.assertEqual(history.ranks["全世界株式"], [1, 2])
        self.assertEqual(history.changes["全世界株式"], [None, -1])

    def test_deduplicates_repeated_runs_for_the_same_week(self):
        rows = [
            ["集計週", "取得日", "順位", "投信名", "運用会社", "資産タイプ"],
            ["2026/06/01～2026/06/07", "2026-06-08", "2", "全世界株式", "A社", "海外株式"],
            ["2026/06/01～2026/06/07", "2026-06-09", "1", "全世界株式", "A社", "海外株式"],
        ]

        history = build_fund_flow_history(rows)

        self.assertEqual(history.weeks, ["06/07"])
        self.assertEqual(history.ranks["全世界株式"], [1])

    def test_renders_rank_movement_png(self):
        rows = [
            ["集計週", "取得日", "順位", "投信名", "運用会社", "資産タイプ"],
            ["2026/05/25～2026/05/31", "2026-06-01", "3", "米国株式", "B社", "海外株式"],
            ["2026/06/01～2026/06/07", "2026-06-08", "1", "米国株式", "B社", "海外株式"],
        ]
        history = build_fund_flow_history(rows)

        with TemporaryDirectory() as directory:
            output = Path(directory) / "fund_flow.png"
            render_fund_flow_map(history, output)

            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 1_000)


if __name__ == "__main__":
    unittest.main()
