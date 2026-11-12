import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lifecycle import derive_repository_health


class RepositoryHealthTests(unittest.TestCase):
    def test_platform_archive_overrides_recent_push(self):
        with tempfile.TemporaryDirectory() as directory:
            row = {"archived": "true", "pushed_at": "2026-11-01T00:00:00Z", "commits": "50", "commits_90d": "20", "active_months_12m": "8"}
            health = derive_repository_health(row, pathlib.Path(directory), "2026-11-12T00:00:00Z")
            self.assertEqual(health["lifecycle"]["status"], "archived")
            self.assertTrue(health["lifecycle"]["repository_archived"])

    def test_readme_deprecation_is_detected_without_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "README.md").write_text("# Plugin\n\nDeprecated: use the new plugin instead.\n")
            health = derive_repository_health({"pushed_at": "2026-10-01T00:00:00Z", "commits": "5"}, root, "2026-11-12T00:00:00Z")
            self.assertEqual(health["lifecycle"]["status"], "deprecated")
            self.assertIn("README.md:3:deprecated", health["lifecycle"]["signals"])

    def test_commit_and_issue_metrics_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            row = {"archived":"false","disabled":"false","pushed_at":"2026-11-10T00:00:00Z","commits":"40","commits_30d":"8","commits_90d":"20","commits_365d":"40","active_months_12m":"9","median_commit_interval_days":"3.5","has_issues":"true","open_issues_count":"7","issue_sample_size":"10","issue_open_sample":"2","issue_closed_sample":"8","issue_close_rate_sample":"0.8","issue_median_close_days_sample":"4.5","issues_updated_90d_sample":"6","latest_issue_updated_at":"2026-11-11T00:00:00Z"}
            health = derive_repository_health(row, pathlib.Path(directory), "2026-11-12T00:00:00Z")
            self.assertEqual(health["maintenance"]["frequency"], "monthly_or_more")
            self.assertEqual(health["issues"]["open_items_count"], 7)
            self.assertEqual(health["issues"]["close_rate_sample"], 0.8)
            self.assertEqual(sum(health["score_components"].values()), health["health_score"])
            self.assertEqual(health["score_confidence"], "high")


if __name__ == "__main__":
    unittest.main()
