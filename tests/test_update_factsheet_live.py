import importlib.util
import json
import math
import os
import tempfile
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "factsheet" / "update_factsheet.py"
SVG_PATH = ROOT / "factsheet" / "factsheet_automatable_eu.svg"
RUN_LIVE_TESTS = os.environ.get("RUN_LIVE_API_TESTS") == "1"

spec = importlib.util.spec_from_file_location("update_factsheet", MODULE_PATH)
update_factsheet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update_factsheet)


def require_live_tests():
    if not RUN_LIVE_TESTS:
        raise unittest.SkipTest("set RUN_LIVE_API_TESTS=1 to run live API integration tests")


class UpdateFactsheetLiveIntegrationTests(unittest.TestCase):
    def setUp(self):
        require_live_tests()

    def test_live_scholar_returns_all_time_citation_total(self):
        stats = update_factsheet.parse_scholar_html(
            update_factsheet.fetch(update_factsheet.SCHOLAR_URL).decode("utf-8", errors="replace")
        )
        self.assertIsInstance(stats["citations"], int)
        self.assertGreater(stats["citations"], 0)

    def test_live_reference_genomes_cross_check(self):
        genomes = json.loads(update_factsheet.fetch(update_factsheet.GENOMES_URL))
        fasta = json.loads(update_factsheet.fetch(update_factsheet.ALL_FASTA_URL))
        count = update_factsheet.count_reference_genomes(genomes, fasta)
        self.assertGreater(count, 0)
        self.assertLessEqual(count, len(genomes))
        self.assertLessEqual(count, len(fasta["fields"]))

    def test_live_grafana_current_queries_return_expected_shapes(self):
        now_ms = int(update_factsheet.time.time() * 1000)
        current = update_factsheet.grafana_query(
            update_factsheet.current_queries(),
            now_ms - 6 * 60 * 60 * 1000,
            now_ms,
        )

        self.assertIn("tools", current["results"])
        self.assertIn("elixir_users", current["results"])
        self.assertIn("egi_checkin_users", current["results"])
        self.assertIn("monthly_users", current["results"])
        self.assertGreater(update_factsheet.count_values(current, "tools"), 1000)
        self.assertGreater(update_factsheet.last_number(current, "monthly_users"), 0)

        # Empty or zero-filled ELIXIR and EGI series are supported by the updater.
        # API errors and malformed data should still fail this integration check.
        for ref_id in ("elixir_users", "egi_checkin_users"):
            with self.subTest(ref_id=ref_id):
                response = current["results"][ref_id]
                self.assertFalse(response.get("error"), response.get("error"))
                self.assertEqual(response.get("status", 200), 200)
                frames = response.get("frames", [])
                self.assertIsInstance(frames, list)
                has_count = False
                for frame in frames:
                    columns = frame["data"]["values"]
                    self.assertGreaterEqual(len(columns), 2)
                    self.assertIsInstance(columns[-1], list)
                    for value in columns[-1]:
                        if value is None:
                            continue
                        self.assertIsInstance(value, (int, float))
                        self.assertTrue(math.isfinite(value))
                        self.assertGreaterEqual(value, 0)
                        has_count = has_count or value > 0
                if has_count:
                    self.assertGreater(update_factsheet.last_number(current, ref_id, ignore_zero=True), 0)

    def test_live_grafana_snapshot_queries_return_expected_shapes(self):
        now_ms = int(update_factsheet.time.time() * 1000)
        snapshots = update_factsheet.grafana_query(
            update_factsheet.latest_snapshot_queries(),
            now_ms - 365 * 24 * 60 * 60 * 1000,
            now_ms,
        )

        for ref_id in ("registered_users", "histories", "jobs", "datasets", "workflows"):
            self.assertIn(ref_id, snapshots["results"])
            self.assertGreater(update_factsheet.last_number(snapshots, ref_id), 0)

    def test_live_tiaas_and_gtn_pages_parse(self):
        tiaas = update_factsheet.parse_tiaas_html(update_factsheet.fetch(update_factsheet.TIAAS_URL).decode("utf-8", errors="replace"))
        gtn = update_factsheet.parse_gtn_html(update_factsheet.fetch(update_factsheet.GTN_URL).decode("utf-8", errors="replace"))

        self.assertGreater(tiaas["events"], 0)
        self.assertGreater(tiaas["trainees"], 0)
        self.assertGreater(gtn["tutorials"], 0)

    def test_live_collect_values_can_render_svg_to_temp_output(self):
        values = update_factsheet.collect_values()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "live-render.svg"
            svg = SVG_PATH.read_text()
            for key, value in values.items():
                svg = update_factsheet.replace_text(svg, update_factsheet.TEXT_IDS[key], value)
            output.write_text(svg)
            ET.parse(output)

        self.assertTrue(values["n_jobs_run"].endswith("M"))
        self.assertRegex(values["n_tools_installed"], r"^\d{1,3}(,\d{3})*$")


if __name__ == "__main__":
    try:
        unittest.main()
    except urllib.error.URLError as error:
        raise SystemExit(f"live endpoint test failed: {error}")
