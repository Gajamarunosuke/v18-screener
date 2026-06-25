import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fund_theme_map import THEMES, render_theme_map, theme_rank_label


class FundThemeMapTests(unittest.TestCase):
    def test_theme_rank_label_shows_fixed_order_in_japanese(self):
        self.assertEqual(theme_rank_label(1), "#01 固定テーマ")

    def test_renders_theme_order_metadata_png(self):
        dates = ["06/07", "06/14"]
        scores = {name: [0, 1] for name, _ in THEMES}

        with TemporaryDirectory() as directory:
            output = Path(directory) / "theme_map.png"
            render_theme_map(dates, scores, output)

            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 1_000)


if __name__ == "__main__":
    unittest.main()
