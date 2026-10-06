import datetime
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "factsheet" / "update_factsheet.py"
FIXTURE_DIR = ROOT / "factsheet" / "api-fixtures"
SVG_PATH = ROOT / "factsheet" / "factsheet_automatable_eu.svg"

spec = importlib.util.spec_from_file_location("update_factsheet", MODULE_PATH)
update_factsheet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update_factsheet)


def text_by_id(svg_path, text_id):
    root = ET.parse(svg_path).getroot()
    for element in root.iter():
        if element.tag.split("}", 1)[-1] == "text" and element.attrib.get("id") == text_id:
            return "".join(element.itertext()).strip()
    raise AssertionError(f"missing text id {text_id}")


class UpdateFactsheetSmokeTests(unittest.TestCase):
    def test_pulsar_counts_unique_remote_runners_only(self):
        source = '''destinations:
  pulsar_default:
    abstract: true
    runner: pulsar_embedded
  embedded_pulsar_docker:
    runner: pulsar_embedded
  pulsar_local:
    runner: pulsar_embedded
  pulsar_cz01_tpv:
    runner: pulsar_eu_cz01
  pulsar_cz02_tpv:
    runner: pulsar_eu_cz01 # GPU queue at the same endpoint
  pulsar_fr01_tpv:
    runner: "pulsar_eu_fr01"
#  pulsar_nemo_tpv:
#    runner: pulsar_eu_nemo
'''
        self.assertEqual(update_factsheet.count_pulsar_runners(source), 2)

    def test_pulsar_rejects_missing_or_changed_inventory(self):
        for source in ("<html>Unavailable</html>", "destinations:\n",
                       "destinations:\n  pulsar_example:\n    inherits: pulsar_default\n",
                       "destinations:\n  pulsar_example:\n    runner: {{ unknown }}\n"):
            with self.subTest(source=source), self.assertRaises(RuntimeError):
                update_factsheet.count_pulsar_runners(source)

    def test_pulsar_fixture_is_readable_mapping_and_deduplicates_runners(self):
        inventory = json.loads((FIXTURE_DIR / "pulsar_destinations.json").read_text())
        self.assertEqual(len(inventory), 17)
        self.assertEqual(inventory["pulsar_cz01_tpv"], inventory["pulsar_cz02_tpv"])
        self.assertEqual(update_factsheet.count_pulsar_inventory(inventory), 16)
        for invalid in ("escaped source", {}, {"pulsar_example": None}):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                update_factsheet.count_pulsar_inventory(invalid)

    def test_scholar_reads_all_time_citations_from_summary_table(self):
        for total in ("24794", "24,794"):
            with self.subTest(total=total):
                page = (
                    '<table><tr><td>Citations</td><td>999</td></tr></table>'
                    '<table id="gsc_rsb_st"><tbody>'
                    '<tr><td>h-index</td><td>34</td><td>27</td></tr>'
                    f'<tr><td><a>Citations</a></td><td>{total}</td><td>11434</td></tr>'
                    '</tbody></table><td class="gsc_rsb_std">123</td>'
                )
                self.assertEqual(update_factsheet.parse_scholar_html(page), {"citations": 24794})

    def test_scholar_rejects_missing_invalid_or_empty_total(self):
        pages = ["<html>unusual traffic CAPTCHA</html>", "<table><td>24794</td></table>",
                 '<table id="gsc_rsb_st"><tr><td>h-index</td><td>34</td></tr></table>']
        pages += [f'<table id="gsc_rsb_st"><tr><td>Citations</td><td>{total}</td>'
                  '<td>11434</td></tr></table>'
                  for total in ("", "0", "-1", "1.5", "24,79", "unknown")]
        for page in pages:
            with self.subTest(page=page), self.assertRaisesRegex(RuntimeError, "Google Scholar"):
                update_factsheet.parse_scholar_html(page)

    def test_reference_genomes_deduplicate_and_cross_check_by_named_column(self):
        genomes = [["Human", "hg38"], ["Human alias", "hg38"],
                   ["Old human", "hg19"], ["Catalog only", "other"],
                   ["Unspecified", "?"], ["Draft", "draft"]]
        table = {"columns": ["name", "dbkey", "value"], "fields": [
            ["Human", "hg38", "hg38full"],
            ["Human index", "hg38", "hg38index"],
            ["Old human", "hg19", "hg19"],
            ["Unregistered", "extra", "extra"],
            ["Unspecified", "?", "?"], ["Draft", "draft", "draft"],
        ]}
        with patch("sys.stderr") as stderr:
            self.assertEqual(update_factsheet.count_reference_genomes(genomes, table), 2)
        warning = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("1 genomes-only, 1 all_fasta-only", warning)

    def test_reference_genomes_reject_invalid_or_unconfirmed_inventories(self):
        table = {"columns": ["dbkey"], "fields": [["hg38"]]}
        cases = [
            ({"error": "unavailable"}, table),
            ([], table),
            ([["Human", "hg19"]], table),
            ([["Human"]], table),
            ([["Human", None]], table),
            ([["Human", "hg38"]], {"columns": ["value"], "fields": [["hg38"]]}),
            ([["Human", "hg38"]], {"columns": ["dbkey"], "fields": [[]]}),
        ]
        for genomes, fasta in cases:
            with self.subTest(genomes=genomes, fasta=fasta), self.assertRaises(RuntimeError):
                update_factsheet.count_reference_genomes(genomes, fasta)

    def test_cli_default_output_preserves_template_and_manual_figures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            template = Path(tmpdir) / "factsheet.svg"
            before = SVG_PATH.read_bytes()
            template.write_bytes(before)
            for key, text_id in update_factsheet.TEXT_IDS.items():
                self.assertEqual(
                    text_by_id(template, text_id),
                    "{{" + key.removeprefix("n_").lower() + "}}",
                )
            result = subprocess.run(
                [sys.executable, str(MODULE_PATH), "--use-fixtures", str(template)],
                cwd=ROOT, check=True, capture_output=True, text=True,
            )
            output = template.with_name(f"factsheet_rendered_{datetime.date.today():%d.%m.%Y}.svg")
            self.assertEqual(template.read_bytes(), before)
            self.assertIn(f"wrote: {output}", result.stdout)
            self.assertNotIn("{{", output.read_text())
            for key, value in update_factsheet.collect_values(fixture_dir=FIXTURE_DIR).items():
                self.assertEqual(text_by_id(output, update_factsheet.TEXT_IDS[key]), value)
            manual_elements = [
                element for element in ET.parse(template).getroot().iter()
                if element.attrib.get("data-source") == "manual"
            ]
            self.assertEqual(len(manual_elements), 1)
            for element in manual_elements:
                text_id = element.attrib["id"]
                self.assertEqual(text_by_id(output, text_id), text_by_id(template, text_id))
            self.assertEqual(output.read_text().count('data-source="manual"'), 1)

    def test_cli_rejects_output_that_aliases_template(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            template = Path(tmpdir) / "template.svg"
            template.write_bytes(SVG_PATH.read_bytes())
            symlink = Path(tmpdir) / "symlink.svg"
            symlink.symlink_to(template)
            hardlink = Path(tmpdir) / "hardlink.svg"
            hardlink.hardlink_to(template)
            before = template.read_bytes()
            for output in (template, symlink, hardlink):
                with self.subTest(output=output):
                    result = subprocess.run(
                        [sys.executable, str(MODULE_PATH), "--use-fixtures",
                         "--output", str(output), str(template)],
                        cwd=ROOT, capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("output must differ", result.stderr)
                    self.assertEqual(template.read_bytes(), before)

    def test_cli_dry_run_does_not_write_default_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            template = Path(tmpdir) / "template.svg"
            before = SVG_PATH.read_bytes()
            template.write_bytes(before)
            subprocess.run(
                [sys.executable, str(MODULE_PATH), "--use-fixtures", "--dry-run", str(template)],
                cwd=ROOT, check=True, capture_output=True, text=True,
            )
            self.assertEqual(list(Path(tmpdir).iterdir()), [template])
            self.assertEqual(template.read_bytes(), before)

    def test_formatters_cover_display_rounding(self):
        self.assertEqual(update_factsheet.format_number(173286, 10_000, plus=True), "170,000+")
        self.assertEqual(update_factsheet.format_number(10, 100), "10")
        self.assertEqual(update_factsheet.format_number(24048, unit="K", plus=True), "24K+")
        self.assertEqual(update_factsheet.format_number(106911907, unit="M"), "107M")

    def test_plus_counts_round_down_at_display_precision(self):
        cases = [
            (176000, 10_000, "", "170,000+"),
            (180000, 10_000, "", "180,000+"),
            (10, 100, "", "10+"),
            (24600, 1, "K", "24K+"),
            (1999999, 1, "M", "1.9M+"),
            (9999999, 1, "M", "9.9M+"),
            (106911907, 1, "M", "106M+"),
            (0, 100, "", "0+"),
        ]
        for value, step, unit, expected in cases:
            with self.subTest(value=value, unit=unit):
                self.assertEqual(
                    update_factsheet.format_number(value, step, unit=unit, plus=True), expected
                )
        self.assertEqual(update_factsheet.format_number(176000, 10_000), "180,000")
        self.assertEqual(update_factsheet.format_number(24600, unit="K"), "25K")

    def test_compact_fixture_values_drive_metrics(self):
        snapshots = json.loads((FIXTURE_DIR / "grafana_snapshots.json").read_text())
        current = json.loads((FIXTURE_DIR / "grafana_current.json").read_text())

        self.assertEqual(update_factsheet.last_number(snapshots, "jobs"), 106911907)
        self.assertEqual(update_factsheet.format_number(update_factsheet.last_number(snapshots, "jobs"), unit="M"), "107M")
        self.assertEqual(update_factsheet.count_values(current, "tools"), 10)

    def test_elixir_users_query_targets_life_science_provider(self):
        query = next(
            query for query in update_factsheet.current_queries()
            if query["refId"] == "elixir_users"
        )

        self.assertEqual(
            query["tags"],
            [{"key": "provider::tag", "operator": "=", "value": "life_science"}],
        )

    def test_egi_checkin_query_targets_egi_checkin_provider(self):
        query = next(
            query for query in update_factsheet.current_queries()
            if query["refId"] == "egi_checkin_users"
        )

        self.assertEqual(
            query["tags"],
            [{"key": "provider::tag", "operator": "=", "value": "egi-checkin"}],
        )

    def test_compact_grafana_result_trims_each_values_array_without_mutating_source(self):
        source = {
            "results": {
                "tools": {
                    "frames": [
                        {
                            "data": {"values": [[1, 2, 3, 4], ["a", "b", "c", "d"]]},
                            "schema": {"fields": []},
                        }
                    ]
                }
            }
        }

        compact = update_factsheet.compact_grafana_result(source, 2)

        self.assertEqual(compact["results"]["tools"]["frames"][0]["data"]["values"], [[3, 4], ["c", "d"]])
        self.assertEqual(source["results"]["tools"]["frames"][0]["data"]["values"], [[1, 2, 3, 4], ["a", "b", "c", "d"]])

    def test_last_number_ignores_nulls_and_optionally_zeros(self):
        result = {
            "results": {
                "metric": {
                    "frames": [
                        {"data": {"values": [[1, 2, 3, 4], [7.2, None, 0, 0]]}},
                        {"data": {"values": [[5, 6, 7], [None, 0, 12.6]]}},
                    ]
                }
            }
        }

        self.assertEqual(update_factsheet.last_number(result, "metric"), 13)
        result["results"]["metric"]["frames"][1]["data"]["values"][1][-1] = 0
        self.assertEqual(update_factsheet.last_number(result, "metric", ignore_zero=True), 7)

    def test_extractors_raise_for_missing_values(self):
        empty_frame = {"results": {"metric": {"frames": [{"data": {"values": [[1], [None]]}}]}}}
        no_frames = {"results": {"metric": {"frames": []}}}

        with self.assertRaises(RuntimeError):
            update_factsheet.last_number(empty_frame, "metric")
        with self.assertRaises(RuntimeError):
            update_factsheet.count_values(no_frames, "metric")

    def test_html_parsers_use_static_markup(self):
        tiaas = update_factsheet.parse_tiaas_html(
            """
            <h5>Overall</h5>
            <h1 class="card-title">615</h1>
            <p>Events since June 20, 2018</p>
            <h5>Overall</h5>
            <h1 class="card-title">24,048</h1>
            <p>Students taught over the lifetime of the TIaaS service</p>
            """
        )
        gtn = update_factsheet.parse_gtn_html(
            '<div class="card-title">527</div><div class="card-text">Tutorials</div>'
        )

        self.assertEqual(tiaas, {"events": 615, "trainees": 24048})
        self.assertEqual(gtn, {"tutorials": 527})

    def test_html_parsers_raise_on_unexpected_markup(self):
        with self.assertRaises(RuntimeError):
            update_factsheet.parse_tiaas_html("<html>No matching cards</html>")
        with self.assertRaises(RuntimeError):
            update_factsheet.parse_gtn_html("<html>No tutorials card</html>")

    def test_replace_text_updates_only_target_text_element(self):
        svg = (
            '<svg><text id="text302"><tspan>old</tspan></text>'
            '<text id="other"><tspan>keep</tspan></text></svg>'
        )
        updated = update_factsheet.replace_text(svg, "text302", "107M")

        self.assertIn("<tspan>107M</tspan>", updated)
        self.assertIn("<tspan>keep</tspan>", updated)
        with self.assertRaises(RuntimeError):
            update_factsheet.replace_text(svg, "missing", "value")

    def test_offline_fixture_render_writes_expected_svg_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "factsheet_from_fixtures.svg"
            values = update_factsheet.collect_values(fixture_dir=FIXTURE_DIR)
            svg = SVG_PATH.read_text()
            for key, value in values.items():
                svg = update_factsheet.replace_text(svg, update_factsheet.TEXT_IDS[key], value)
            output.write_text(svg)

            ET.parse(output)
            self.assertEqual(text_by_id(output, "text60591"), "500+")
            self.assertEqual(text_by_id(output, "text1418"), "10")
            self.assertEqual(text_by_id(output, "text302"), "107M")
            self.assertEqual(text_by_id(output, "text1411"), "215M")

    def test_collect_values_from_fixtures_is_expected_smoke_snapshot(self):
        self.assertEqual(
            update_factsheet.collect_values(fixture_dir=FIXTURE_DIR),
            {
                "n_GTN_tutorials": "500+",
                "n_pubs_global": "24K+",
                "n_pulsar_nodes": "16",
                "n_reference_genomes": "2",
                "n_datasets": "215M",
                "n_elixir_users": "300+",
                "n_egi_checkin": "500+",
                "n_histories": "13M",
                "n_jobs_run": "107M",
                "n_monthly_users": "8,600",
                "n_registered_users": "170,000+",
                "n_tiaas_events": "600+",
                "n_tiaas_trainees": "24K+",
                "n_tools_installed": "10",
                "n_workflow_executions": "752K",
            },
        )

    def test_cli_use_fixtures_output_path_writes_svg_without_touching_input(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "cli-output.svg"
            before = SVG_PATH.read_text()
            result = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--use-fixtures",
                    "--output",
                    str(output),
                    str(SVG_PATH),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertTrue(output.exists())
            self.assertIn("wrote:", result.stdout)
            self.assertEqual(SVG_PATH.read_text(), before)
            self.assertEqual(text_by_id(output, "text1418"), "10")

    def test_cli_keeps_elixir_value_when_series_has_no_count(self):
        for frames in ([], [{"data": {"values": [[1, 2, 3], [None, 0, 0]]}}]):
            with self.subTest(frames=frames), tempfile.TemporaryDirectory() as tmpdir:
                fixture_dir = Path(tmpdir)
                for source in FIXTURE_DIR.glob("*.json"):
                    (fixture_dir / source.name).write_bytes(source.read_bytes())
                current_path = fixture_dir / "grafana_current.json"
                current = json.loads(current_path.read_text())
                current["results"]["elixir_users"]["frames"] = frames
                current_path.write_text(json.dumps(current))
                output = fixture_dir / "output.svg"
                result = subprocess.run(
                    [sys.executable, str(MODULE_PATH), "--use-fixtures",
                     "--fixture-dir", str(fixture_dir), "--output", str(output), str(SVG_PATH)],
                    cwd=ROOT, check=True, capture_output=True, text=True,
                )
                self.assertIn("leaving ELIXIR AAI users unchanged", result.stderr)
                self.assertNotIn("n_elixir_users:", result.stdout)
                self.assertEqual(text_by_id(output, "text1360-7"), text_by_id(SVG_PATH, "text1360-7"))
                self.assertEqual(text_by_id(output, "text1418"), "10")
                self.assertEqual(text_by_id(output, "text302"), "107M")

    def test_cli_keeps_egi_checkin_value_when_series_has_no_count(self):
        for frames in ([], [{"data": {"values": [[1, 2, 3], [None, 0, 0]]}}]):
            with self.subTest(frames=frames), tempfile.TemporaryDirectory() as tmpdir:
                fixture_dir = Path(tmpdir)
                for source in FIXTURE_DIR.glob("*.json"):
                    (fixture_dir / source.name).write_bytes(source.read_bytes())
                current_path = fixture_dir / "grafana_current.json"
                current = json.loads(current_path.read_text())
                current["results"]["egi_checkin_users"]["frames"] = frames
                current_path.write_text(json.dumps(current))
                output = fixture_dir / "output.svg"
                result = subprocess.run(
                    [sys.executable, str(MODULE_PATH), "--use-fixtures",
                     "--fixture-dir", str(fixture_dir), "--output", str(output), str(SVG_PATH)],
                    cwd=ROOT, check=True, capture_output=True, text=True,
                )
                self.assertIn("leaving EGI Check-in users unchanged", result.stderr)
                self.assertNotIn("n_egi_checkin:", result.stdout)
                self.assertEqual(text_by_id(output, "text60591"), text_by_id(SVG_PATH, "text60591"))
                self.assertEqual(text_by_id(output, "text1418"), "10")
                self.assertEqual(text_by_id(output, "text302"), "107M")

    def test_save_fixtures_round_trips_live_values_without_network(self):
        sources = {
            name: json.loads((FIXTURE_DIR / f"{name}.json").read_text())
            for name in ("grafana_snapshots", "grafana_current", "tiaas_stats", "gtn_stats", "genomes", "all_fasta", "scholar_stats", "pulsar_destinations")
        }
        tiaas_html = b"Overall 615 Events since 2018 Overall 24,048 Students taught"
        gtn_html = b'<div class="card-title">527</div><div class="card-text">Tutorials</div>'
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_dir = Path(tmpdir) / "nested" / "fixtures"
            with patch.object(update_factsheet, "fetch", side_effect=[
                json.dumps(sources["grafana_snapshots"]).encode(),
                json.dumps(sources["grafana_current"]).encode(),
                tiaas_html,
                gtn_html,
                json.dumps(sources["genomes"]).encode(),
                json.dumps(sources["all_fasta"]).encode(),
                (f'<table id="gsc_rsb_st"><tr><td>Citations</td>'
                 f'<td>{sources["scholar_stats"]["citations"]}</td><td>11434</td></tr></table>').encode(),
                ("destinations:\n" + "".join(
                    f"  {name}:\n    runner: {runner}\n"
                    for name, runner in sources["pulsar_destinations"].items()
                )).encode(),
            ]) as fetch:
                values = update_factsheet.collect_values(fixture_dir=fixture_dir, save_fixtures=True)
                self.assertEqual(fetch.call_count, 8)
                self.assertEqual(fetch.call_args.args[0], update_factsheet.PULSAR_URL)
            self.assertEqual(update_factsheet.collect_values(fixture_dir=fixture_dir), values)
            for name, expected in sources.items():
                self.assertEqual(json.loads((fixture_dir / f"{name}.json").read_text()), expected)


if __name__ == "__main__":
    unittest.main()
