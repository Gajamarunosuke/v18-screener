import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / ".deps"))
sys.path.insert(0, str(BASE_DIR / "scripts"))

import kitra_jp_check


class KitraLocalReportTests(unittest.TestCase):
    def test_run_date_can_be_overridden_for_retry(self):
        with patch.dict(kitra_jp_check.os.environ, {"KITRA_RUN_DATE": "2026-06-26"}, clear=False):
            self.assertEqual(kitra_jp_check.run_date(), "2026-06-26")

    def test_reads_only_today_local_v18_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "2026-06-21_v18_screener.md").write_text(
                "| [[1111]] | 100 | 90 | 80 | 70 | 1.00% | MA20 | 100,000 |\n",
                encoding="utf-8",
            )
            (output_dir / "2026-06-22_v18_screener.md").write_text(
                "| [[6383]] | 7277 | 7100 | 7000 | 6900 | 2.10% | MA20 | 934,900 |\n",
                encoding="utf-8",
            )

            with patch.object(kitra_jp_check, "OUTPUT_DIR", output_dir):
                rows = kitra_jp_check.get_v18_results_from_latest_report("2026-06-22")

        self.assertEqual([row["コード"] for row in rows], ["6383"])

    def test_stale_local_report_stops_instead_of_sending_false_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "2026-06-21_v18_screener.md").write_text(
                "| [[1111]] | 100 | 90 | 80 | 70 | 1.00% | MA20 | 100,000 |\n",
                encoding="utf-8",
            )

            with patch.object(kitra_jp_check, "OUTPUT_DIR", output_dir):
                with patch.dict(kitra_jp_check.os.environ, {"KITRA_ALLOW_STALE_LOCAL_REPORT": ""}, clear=False):
                    with self.assertRaises(SystemExit) as raised:
                        kitra_jp_check.get_v18_results_from_latest_report("2026-06-22")

        self.assertIn("today's local V18 report does not exist", str(raised.exception))

    def test_tv_run_timeout_is_treated_as_missing_values(self):
        with patch.object(
            kitra_jp_check.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["node", "values"], 30),
        ):
            self.assertIsNone(kitra_jp_check.tv_run(["node", "values"]))


if __name__ == "__main__":
    unittest.main()
