#!/usr/bin/env python3
"""Render the UseGalaxy.eu factsheet template to a separate SVG using public stats."""

from __future__ import annotations

import argparse
import cairosvg
import copy
import datetime
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


GRAFANA_BASE = "https://stats.galaxyproject.eu"
HISTORICAL_DS = {"type": "influxdb", "uid": "PEBD82B4560F292BD"}
CURRENT_DS = {"type": "influxdb", "uid": "P9B81C0353945995B"}
TIAAS_URL = "https://usegalaxy.eu/tiaas/stats/"
GTN_URL = "https://training.galaxyproject.org/training-material/stats/#gtn-statistics"
GENOMES_URL = "https://usegalaxy.eu/api/genomes"
ALL_FASTA_URL = "https://usegalaxy.eu/api/tool_data/all_fasta"
SCHOLAR_URL = "https://scholar.google.de/citations?hl=en&user=3tSiRGoAAAAJ"
PULSAR_URL = "https://raw.githubusercontent.com/usegalaxy-eu/infrastructure-playbook/master/files/galaxy/tpv/destinations.yml.j2"
DEFAULT_FIXTURE_DIR = Path("factsheet/api-fixtures")
DEFAULT_FIXTURE_VALUE_LIMIT = 10

# PNG output: try native renderers first, fall back to the cairosvg module.
PNG_WIDTH = 4240  # match the width of the previously published factsheet PNG
PNG_RENDERERS = (
    ("inkscape", ("inkscape", "--export-type=png", "--export-filename")),
    ("rsvg-convert", ("rsvg-convert", "-o")),
)


def write_png(svg_path: Path, png_path: Path) -> None:
    """Render the SVG to PNG under png_path."""
    try:
        cairosvg.svg2png(
            url=str(svg_path),
            write_to=str(png_path),
            output_width=PNG_WIDTH,
        )
    except Exception as error:
        raise RuntimeError(f"Failed to render PNG: {error}") from error


DEFAULT_FIXTURE_VALUE_LIMIT = 10

TEXT_IDS = {
    "n_pulsar_nodes": "text1422",
    "n_pubs_global": "text414",
    "n_reference_genomes": "text1418-4",
    "n_elixir_users": "text1360-7",
    "n_egi_checkin": "text60591",
    "n_monthly_users": "text354",
    "n_registered_users": "text280",
    "n_tiaas_trainees": "text1392-3-2-9",
    "n_tiaas_events": "text1392-3",
    "n_GTN_tutorials": "text1392",
    "n_histories": "text1421",
    "n_datasets": "text1411",
    "n_workflow_executions": "text1371",
    "n_jobs_run": "text302",
    "n_tools_installed": "text1418",
}


def fetch(url: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def grafana_query(queries: list[dict], from_ms: int, to_ms: int) -> dict:
    payload = json.dumps({"queries": queries, "from": str(from_ms), "to": str(to_ms)}).encode()
    data = fetch(
        f"{GRAFANA_BASE}/api/ds/query",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    return json.loads(data)


def parse_scholar_html(text: str) -> dict[str, int]:
    """Read the all-time citations total, not recent citations or article counts.

    The profile is requested in English to identify the Citations row. Fail on
    challenge pages or changed markup rather than displaying a misleading count.
    """
    table = re.search(r'<table\b[^>]*\bid=["\']gsc_rsb_st["\'][^>]*>(.*?)</table>', text, re.S)
    if table:
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table.group(1), re.S):
            cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)
            plain = [html.unescape(re.sub(r"<[^>]+>", "", cell)).strip() for cell in cells]
            if len(plain) >= 2 and plain[0] == "Citations":
                total = plain[1]
                if re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)", total):
                    count = int(total.replace(",", ""))
                    if count > 0:
                        return {"citations": count}
    raise RuntimeError("Could not parse Google Scholar all-time citations total (page may be blocked or changed)")


def parse_pulsar_destinations(text: str) -> dict[str, str]:
    """Extract remote destination-to-runner mappings without evaluating Jinja.

    Read only destination names and direct scalar fields at their expected
    indentation. Shared templates, embedded runners and comments do not count.
    This measures configured runners, not institutions or live availability.
    """
    section = re.search(r"^destinations:\s*\n", text, re.M)
    if not section:
        raise RuntimeError("Invalid Pulsar inventory: missing destinations mapping")
    entries = re.split(r"^  ([A-Za-z0-9_]+):[^\n]*\n", text[section.end():], flags=re.M)
    destinations = {}
    for name, body in zip(entries[1::2], entries[2::2]):
        if not name.startswith("pulsar_"):
            continue
        if re.search(r"^    abstract: true\s*(?:#.*)?$", body, re.M):
            continue
        fields = re.findall(r"^    runner:[ \t]*([^\n]+)", body, re.M)
        if len(fields) != 1:
            raise RuntimeError(f"Invalid Pulsar inventory: expected one runner for {name}")
        runner = fields[0].split("#", 1)[0].strip().strip("\"'")
        if not re.fullmatch(r"pulsar_[A-Za-z0-9_]+", runner):
            raise RuntimeError(f"Invalid Pulsar inventory: unsupported runner for {name}")
        if runner != "pulsar_embedded":
            destinations[name] = runner
    if not destinations:
        raise RuntimeError("No remote Pulsar runners found in destination configuration")
    return destinations


def count_pulsar_runners(text: str) -> int:
    return len(set(parse_pulsar_destinations(text).values()))


def count_pulsar_inventory(destinations: dict[str, str]) -> int:
    if not isinstance(destinations, dict) or not destinations or any(
        not isinstance(name, str) or not name.startswith("pulsar_")
        or not isinstance(runner, str)
        or not re.fullmatch(r"pulsar_[A-Za-z0-9_]+", runner)
        or runner == "pulsar_embedded"
        for name, runner in destinations.items()
    ):
        raise RuntimeError("Invalid Pulsar destination inventory")
    return len(set(destinations.values()))


def compact_grafana_result(result: dict, value_limit: int) -> dict:
    compact = copy.deepcopy(result)
    for response in compact.get("results", {}).values():
        for frame in response.get("frames", []):
            values = frame.get("data", {}).get("values", [])
            if not values:
                continue

            frame["data"]["values"] = [
                value[-value_limit:] if isinstance(value, list) and len(value) > value_limit else value
                for value in values
            ]
    return compact


def last_number(result: dict, ref_id: str, *, ignore_zero: bool = False) -> int:
    frames = result["results"][ref_id].get("frames", [])
    for frame in reversed(frames):
        values = frame["data"]["values"]
        if len(values) < 2:
            continue
        for value in reversed(values[-1]):
            if value is not None and (not ignore_zero or value != 0):
                return int(round(value))
    raise RuntimeError(f"No numeric value returned for {ref_id}")


def count_values(result: dict, ref_id: str) -> int:
    frames = result["results"][ref_id].get("frames", [])
    if not frames:
        raise RuntimeError(f"No frames returned for {ref_id}")
    return len(frames[0]["data"]["values"][0])


def latest_snapshot_queries() -> list[dict]:
    queries = []

    measurements = {
        "registered_users": "server-users",
        "histories": "server-histories",
        "jobs": "server-jobs",
        "datasets": "server-datasets",
        "workflows": "server-workflow-invocations",
    }
    for ref_id, measurement in measurements.items():
        where = "$timeFilter"
        if ref_id == "registered_users":
            where += " AND \"deleted\"='f' AND \"purged\"='f' AND \"external\"='f'"
        queries.append(
            {
                "refId": ref_id,
                "datasource": HISTORICAL_DS,
                "rawQuery": True,
                "resultFormat": "time_series",
                "query": (
                    f'SELECT sum("count") AS "Count" FROM "{measurement}" '
                    f"WHERE {where} GROUP BY time(1d) fill(none)"
                ),
                "intervalMs": 86_400_000,
                "maxDataPoints": 500,
            }
        )
    return queries


def current_queries() -> list[dict]:
    return [
        {
            "refId": "tools",
            "datasource": CURRENT_DS,
            "rawQuery": True,
            "resultFormat": "time_series",
            "query": 'SHOW TAG VALUES FROM "tool-usage" WITH KEY = "tool_id"',
            "intervalMs": 60_000,
            "maxDataPoints": 5_000,
        },
        oidc_users_query("elixir_users", "life_science"),
        oidc_users_query("egi_checkin_users", "egi-checkin"),
        {
            "refId": "monthly_users",
            "datasource": CURRENT_DS,
            "rawQuery": True,
            "resultFormat": "table",
            "query": (
                'SELECT last("active_users") as "Active users" '
                'FROM "galaxy_monthly_active_users" GROUP BY "month"::tag'
            ),
            "intervalMs": 60_000,
            "maxDataPoints": 10,
        },
    ]


def oidc_users_query(ref_id: str, provider: str) -> dict:
    return {
        "refId": ref_id,
        "datasource": CURRENT_DS,
        "measurement": "users-with-oidc",
        "policy": "default",
        "resultFormat": "time_series",
        "orderByTime": "ASC",
        "select": [[{"type": "field", "params": ["count"]}, {"type": "last", "params": []}]],
        "tags": [{"key": "provider::tag", "operator": "=", "value": provider}],
        "groupBy": [
            {"type": "time", "params": ["60000ms"]},
            {"type": "tag", "params": ["provider"]},
            {"type": "fill", "params": ["0"]},
        ],
        "intervalMs": 60_000,
        "maxDataPoints": 500,
    }


def parse_tiaas_html(text: str) -> dict[str, int]:
    plain = html.unescape(re.sub(r"<[^>]+>", " ", text))
    plain = " ".join(plain.split())
    events = re.search(r"Overall\s+([\d,]+)\s+Events since", plain)
    trainees = re.search(r"Overall\s+([\d,]+)\s+Students taught", plain)
    if not events or not trainees:
        raise RuntimeError("Could not parse TIaaS stats page")
    return {
        "events": int(events.group(1).replace(",", "")),
        "trainees": int(trainees.group(1).replace(",", "")),
    }


def parse_gtn_html(text: str) -> dict[str, int]:
    match = re.search(r'<div class="card-title">([\d,]+)</div>\s*<div class="card-text">Tutorials</div>', text)
    if not match:
        raise RuntimeError("Could not parse GTN stats page")
    return {"tutorials": int(match.group(1).replace(",", ""))}


def count_reference_genomes(genomes: list, all_fasta: dict) -> int:
    """Count registered assembly dbkeys backed by all_fasta, once per dbkey.

    This is an identifier count: aliases are not merged without evidence, and
    tool indexes, FASTA variants and repeated rows do not add assemblies.
    """
    placeholders = {"", "?", "draft"}

    def valid_key(value):
        if not isinstance(value, str):
            raise ValueError("genome IDs must be strings")
        return value.strip()

    try:
        if not isinstance(genomes, list) or not isinstance(all_fasta, dict):
            raise ValueError("unexpected inventory response")
        registered = set()
        for row in genomes:
            if not isinstance(row, list) or len(row) != 2:
                raise ValueError("expected genome label/ID pairs")
            registered.add(valid_key(row[1]))
        columns = all_fasta["columns"]
        rows = all_fasta["fields"]
        if not isinstance(columns, list) or not isinstance(rows, list):
            raise ValueError("expected data-table columns and fields")
        dbkey_index = columns.index("dbkey")
        installed = set()
        for row in rows:
            if not isinstance(row, list) or len(row) != len(columns):
                raise ValueError("data-table row does not match columns")
            installed.add(valid_key(row[dbkey_index]))
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError(f"Invalid reference genome inventory: {error}") from error

    registered -= placeholders
    installed -= placeholders
    confirmed = registered & installed
    if not confirmed:
        raise RuntimeError("No reference genomes confirmed by both genomes and all_fasta")
    if registered != installed:
        print(
            f"warning: reference genome cross-check: {len(confirmed)} shared dbkeys; "
            f"{len(registered - installed)} genomes-only, "
            f"{len(installed - registered)} all_fasta-only; counting shared dbkeys only",
            file=sys.stderr,
        )
    return len(confirmed)


def format_number(value: int, step: int = 1, *, unit: str = "", plus: bool = False) -> str:
    """Format a count, rounding down for '+' so the displayed minimum is accurate."""
    if plus:
        # Match the displayed precision before applying the usual formatting.
        if unit == "M":
            precision = 100_000 if value < 10_000_000 else 1_000_000
        elif unit == "K":
            precision = 1_000
        else:
            precision = step if abs(value) >= step else 1
        value = value // precision * precision

    if unit == "M":
        millions = value / 1_000_000
        text = f"{millions:.1f}M" if millions < 10 else f"{round(millions)}M"
    elif unit == "K":
        text = f"{round(value / 1_000)}K"
    else:
        rounded = round(value / step) * step if abs(value) >= step else value
        text = f"{rounded:,}"
    return text + ("+" if plus else "")


def replace_text(svg: str, text_id: str, value: str) -> str:
    pattern = re.compile(rf'(<text\b(?:(?!</text>).)*?\bid="{re.escape(text_id)}"(?:(?!</text>).)*?>)(.*?)(</text>)', re.S)
    match = pattern.search(svg)
    if not match:
        raise RuntimeError(f"Could not find text element {text_id}")
    body = match.group(2)
    tspan_pattern = re.compile(r"(>)([^<>]*)(</tspan>)", re.S)
    body, replacements = tspan_pattern.subn(lambda m: f"{m.group(1)}{html.escape(value)}{m.group(3)}", body, count=1)
    if replacements != 1:
        raise RuntimeError(f"Could not replace tspan text in {text_id}")
    return svg[: match.start(2)] + body + svg[match.end(2) :]


def collect_values(
    *,
    fixture_dir: Path | None = None,
    save_fixtures: bool = False,
    fixture_value_limit: int = DEFAULT_FIXTURE_VALUE_LIMIT,
) -> dict[str, str]:
    """Load stats sources, optionally save fixtures, then format the counts."""
    if fixture_dir and not save_fixtures:
        source_data = {}
        for name in ("grafana_snapshots", "grafana_current", "tiaas_stats", "gtn_stats", "genomes", "all_fasta", "scholar_stats", "pulsar_destinations"):
            source_data[name] = json.loads((fixture_dir / f"{name}.json").read_text())
    else:
        now_ms = int(time.time() * 1000)
        six_hours_ago_ms = now_ms - 6 * 60 * 60 * 1000
        one_year_ago_ms = now_ms - 365 * 24 * 60 * 60 * 1000
        source_data = {
            "grafana_snapshots": grafana_query(latest_snapshot_queries(), one_year_ago_ms, now_ms),
            "grafana_current": grafana_query(current_queries(), six_hours_ago_ms, now_ms),
            "tiaas_stats": parse_tiaas_html(fetch(TIAAS_URL).decode("utf-8", errors="replace")),
            "gtn_stats": parse_gtn_html(fetch(GTN_URL).decode("utf-8", errors="replace")),
            "genomes": json.loads(fetch(GENOMES_URL)),
            "all_fasta": json.loads(fetch(ALL_FASTA_URL)),
            "scholar_stats": parse_scholar_html(fetch(SCHOLAR_URL).decode("utf-8", errors="replace")),
            "pulsar_destinations": parse_pulsar_destinations(fetch(PULSAR_URL).decode("utf-8")),
        }

    if fixture_dir and save_fixtures:
        fixture_dir.mkdir(parents=True, exist_ok=True)
        for name, data in source_data.items():
            if name.startswith("grafana_"):
                data = compact_grafana_result(data, fixture_value_limit)
            (fixture_dir / f"{name}.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    snapshots = source_data["grafana_snapshots"]
    current = source_data["grafana_current"]
    tiaas = source_data["tiaas_stats"]
    gtn = source_data["gtn_stats"]

    values = {
        "n_pulsar_nodes": format_number(count_pulsar_inventory(source_data["pulsar_destinations"])),
        "n_pubs_global": format_number(source_data["scholar_stats"]["citations"], unit="K", plus=True),
        "n_reference_genomes": format_number(
            count_reference_genomes(source_data["genomes"], source_data["all_fasta"]), 10, plus=True
        ),
        "n_monthly_users": format_number(last_number(current, "monthly_users"), 100),
        "n_registered_users": format_number(last_number(snapshots, "registered_users"), 10_000, plus=True),
        "n_tiaas_trainees": format_number(tiaas["trainees"], unit="K", plus=True),
        "n_tiaas_events": format_number(tiaas["events"], 100, plus=True),
        "n_GTN_tutorials": format_number(gtn["tutorials"], 100, plus=True),
        "n_histories": format_number(last_number(snapshots, "histories"), unit="M"),
        "n_datasets": format_number(last_number(snapshots, "datasets"), unit="M"),
        "n_workflow_executions": format_number(last_number(snapshots, "workflows"), unit="K"),
        "n_jobs_run": format_number(last_number(snapshots, "jobs"), unit="M"),
        "n_tools_installed": format_number(count_values(current, "tools"), 100),
    }
    # Grafana fills gaps in this series with zero. Leave the template placeholder
    # visible when the queried period has no real count.
    try:
        elixir_users = last_number(current, "elixir_users", ignore_zero=True)
    except RuntimeError as error:
        print(f"warning: {error}; leaving ELIXIR AAI users unchanged (placeholder remains in template-based output)", file=sys.stderr)
    else:
        values["n_elixir_users"] = format_number(elixir_users, 100, plus=True)
    try:
        egi_checkin_users = last_number(current, "egi_checkin_users", ignore_zero=True)
    except RuntimeError as error:
        print(f"warning: {error}; leaving EGI Check-in users unchanged", file=sys.stderr)
    else:
        values["n_egi_checkin"] = format_number(egi_checkin_users, 100, plus=True)
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("svg", nargs="?", default="factsheet/factsheet_automatable_eu.svg", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output path (default: <input stem>_rendered.svg beside the template). Must differ from the input.",
    )
    parser.add_argument(
        "--no-png",
        action="store_true",
        help="Skip rendering a PNG version of the output SVG.",
    )
    parser.add_argument(
        "--fixture-dir",
        default=DEFAULT_FIXTURE_DIR,
        type=Path,
        help="Directory for API JSON fixtures.",
    )
    parser.add_argument(
        "--save-fixtures",
        action="store_true",
        help="Save API responses and parsed external stats as JSON fixtures.",
    )
    parser.add_argument(
        "--use-fixtures",
        action="store_true",
        help="Read JSON fixtures instead of querying public endpoints.",
    )
    parser.add_argument(
        "--fixture-value-limit",
        default=DEFAULT_FIXTURE_VALUE_LIMIT,
        type=int,
        help="Maximum values to keep in each Grafana fixture data.values array when saving fixtures.",
    )
    args = parser.parse_args()
    if args.save_fixtures and args.use_fixtures:
        parser.error("--save-fixtures and --use-fixtures cannot be combined")
    update_date = datetime.date.today().strftime("%d.%m.%Y")
    output = args.output or args.svg.with_name(f"{args.svg.stem}_rendered_{update_date}{args.svg.suffix}")
    if output.resolve() == args.svg.resolve() or (output.exists() and output.samefile(args.svg)):
        parser.error("output must differ from the input SVG template")
    png_output = output.with_suffix(".png")
    if not args.no_png and not args.dry_run and png_output.resolve() == args.svg.resolve():
        parser.error("PNG output must differ from the input SVG template")

    fixture_dir = args.fixture_dir if args.save_fixtures or args.use_fixtures else None
    values = collect_values(
        fixture_dir=fixture_dir,
        save_fixtures=args.save_fixtures,
        fixture_value_limit=args.fixture_value_limit,
    )
    svg = args.svg.read_text()
    for key, value in values.items():
        svg = replace_text(svg, TEXT_IDS[key], value)

    if not args.dry_run:
        output.write_text(svg)
        if not args.no_png:
            write_png(output, png_output)
    for key in sorted(values):
        print(f"{key}: {values[key]}")
    if not args.dry_run:
        print(f"wrote: {output}")
        if not args.no_png:
            print(f"wrote: {png_output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, urllib.error.URLError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
