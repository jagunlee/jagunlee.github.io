import importlib.util
import unittest
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "update_conferences.py"
spec = importlib.util.spec_from_file_location("updater", MODULE_PATH)
updater = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = updater
spec.loader.exec_module(updater)


class ParserTests(unittest.TestCase):
    def test_date_range(self):
        dates = updater.extract_dates("June 17-19, 2026", 2026, {2026})
        self.assertEqual([updater.iso(d) for d in dates][:2], ["2026-06-17", "2026-06-19"])

    def test_cross_month_range(self):
        dates = updater.extract_dates("June 30 - July 2, 2026", 2026, {2026})
        self.assertEqual([updater.iso(d) for d in dates][:2], ["2026-06-30", "2026-07-02"])

    def test_wikicfp_candidate_score(self):
        conf = {"acronym": "WADS", "name": "Algorithms and Data Structures Symposium", "aliases": []}
        self.assertGreaterEqual(
            updater.score_wikicfp_candidate("WADS 2027 Algorithms and Data Structures Symposium", conf, 2027),
            55,
        )
        self.assertLess(
            updater.score_wikicfp_candidate("WADS 2026 unrelated workshop", conf, 2027),
            0,
        )


if __name__ == "__main__":
    unittest.main()
