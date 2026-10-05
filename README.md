# European Galaxy Branding Resources

This repository contains branding assets for Galaxy Europe, useGalaxy.eu, Euro Science Gateway, stickers, banners, and factsheets.

Most assets are committed as source SVG files plus generated PNG/PDF exports so they can be used directly in presentations, websites, print material, and training content.

## Factsheets

The current automatable European factsheet is:

![Galaxy Europe factsheet](factsheet/factsheet_automatable_eu.png)

Important files:

- `factsheet/factsheet_automatable_eu.svg`: editable SVG source for the European factsheet.
- `factsheet/factsheet_automatable_eu.png`: exported PNG preview.
- `factsheet/factsheet_automatable_eu.pdf`: exported PDF.
- `factsheet/factsheet_automatable_de.svg`: German variant.
- `factsheet/update_factsheet.py`: updates selected EU factsheet numbers from public stats sources.

### Update Factsheet Stats

Run the updater from the repository root:

```bash
python3 factsheet/update_factsheet.py factsheet/factsheet_automatable_eu.svg
```

The script updates the SVG text values for metrics that are available through public APIs:

- registered users
- monthly active users
- ELIXIR AAI users
- tools installed
- jobs
- datasets
- histories
- workflow executions
- TIaaS events and trainees
- GTN tutorials

The updater intentionally leaves values unchanged when the current dashboard only embeds an external view or no public API source is available. At the moment this applies to countries, publications, reference genomes, and Pulsar partners.

To preview the detected values without writing the SVG:

```bash
python3 factsheet/update_factsheet.py --dry-run factsheet/factsheet_automatable_eu.svg
```

To save local JSON fixtures from the public endpoints:

```bash
python3 factsheet/update_factsheet.py --dry-run --save-fixtures factsheet/factsheet_automatable_eu.svg
```

Grafana fixtures are compacted by default: each `data.values` array keeps only the last 10 entries. Offline fixture runs calculate metrics from the compact fixture contents, so counters based on array length, such as tools installed, reflect the trimmed fixture size. To use a different limit:

```bash
python3 factsheet/update_factsheet.py --dry-run --save-fixtures --fixture-value-limit 25 factsheet/factsheet_automatable_eu.svg
```

This writes fixtures to `factsheet/api-fixtures/`:

- `grafana_snapshots.json`
- `grafana_current.json`
- `tiaas_stats.json`
- `gtn_stats.json`

To test locally without querying any API endpoint:

```bash
python3 factsheet/update_factsheet.py --dry-run --use-fixtures factsheet/factsheet_automatable_eu.svg
```

To run a stronger offline test, render a separate SVG from the compact fixtures:

```bash
python3 factsheet/update_factsheet.py --use-fixtures --output factsheet/factsheet_rendered_from_fixtures.svg factsheet/factsheet_automatable_eu.svg
```

Run the offline smoke tests:

```bash
python3 -m unittest tests/test_update_factsheet.py
```

Run live integration tests against the real public endpoints:

```bash
RUN_LIVE_API_TESTS=1 python3 -m unittest tests/test_update_factsheet_live.py
```

The updater queries:

- `https://stats.galaxyproject.eu/`
- `https://usegalaxy.eu/tiaas/stats/`
- `https://training.galaxyproject.org/training-material/stats/#gtn-statistics`

### Render A Preview

If `rsvg-convert` is installed:

```bash
rsvg-convert factsheet/factsheet_automatable_eu.svg -o /tmp/factsheet_automatable_eu_preview.png
```

Open the rendered PNG and check for label overlap after large number changes.

## Build Logo Exports

The root `Makefile` builds PNG logo exports from root-level SVG files.

Install dependencies:

```bash
yarn install
```

Build all generated logo sizes:

```bash
make
```

The build uses:

- `svgexport`
- GraphicsMagick `gm`
- `optipng`

## Asset Guide

### Galaxy Europe

Use this when referring to the European Galaxy project or community. Do not use it for specific sub-teams.

Light Background | Dark Background
--- | ---
![](./galaxy-eu/galaxy-eu.256.png) | ![](./galaxy-eu.inv/galaxy-eu.inv.256.png)
[PNG large](galaxy-eu/galaxy-eu.png) | [PNG large](galaxy-eu.inv/galaxy-eu.inv.png)
[SVG](./galaxy-eu.svg) | [SVG](galaxy-eu.inv.svg)

### Freiburg Galaxy

Use this for the Freiburg Galaxy Team, including articles and training activities produced by the team.

Light Background | Dark Background
--- | ---
![](./freiburg-galaxy/freiburg-galaxy.256.png) | ![](./freiburg-galaxy.inv/freiburg-galaxy.inv.256.png)
[PNG large](freiburg-galaxy/freiburg-galaxy.png) | [PNG large](freiburg-galaxy.inv/freiburg-galaxy.inv.png)
[SVG](./freiburg-galaxy.svg) | [SVG](freiburg-galaxy.inv.svg)

### useGalaxy.eu

Use this when directing users to the European Galaxy server.

Light Background | Dark Background
--- | ---
![](./useGalaxy.eu/useGalaxy.eu.256.png) | ![](./useGalaxy.eu.inv/useGalaxy.eu.inv.256.png)
[PNG large](useGalaxy.eu/useGalaxy.eu.png) | [PNG large](useGalaxy.eu.inv/useGalaxy.eu.inv.png)
[SVG](./useGalaxy.eu.svg) | [SVG](useGalaxy.eu.inv.svg)

### Galaxy Project

Use this for the overall Galaxy Project.

Light Background |
--- |
![](./galaxy-project/galaxy_project_white_292x75.png) |
[PNG large](galaxy-project/galaxy_project_transparent_2000x708.png) |
[PNG 292x75 transparent](galaxy-project/galaxy_project_transparent_292x75.png) |
[PNG 292x75 white](galaxy-project/galaxy_project_white_292x75.png) |

### Galaxy Europe Icon

Use this where a logo mark is needed without text, such as favicons or compact branding.

Light Background | Dark Background
--- | ---
![](./galaxy-eu-logo/galaxy-eu-logo.256.png) | ![](./galaxy-eu-logo.inv/galaxy-eu-logo.inv.256.png)
[PNG large](galaxy-eu-logo/galaxy-eu-logo.png) | [PNG large](galaxy-eu-logo.inv/galaxy-eu-logo.inv.png)
[SVG](./galaxy-eu-logo.svg) | [SVG](galaxy-eu-logo.inv.svg)

### Euro Science Gateway

Use this for the Euro Science Gateway project. Use the colorful logo on white backgrounds, and the white or black variants where contrast requires them.

Standard | White | Black
--- | --- | ---
![](./euro-science-gateway/eosc_euro_science_gateway.256.png) | ![](./euro-science-gateway/eosc_euro_science_gateway_white.256.png) | ![](./euro-science-gateway/eosc_euro_science_gateway_black.256.png)
[SVG](euro-science-gateway/eosc_euro_science_gateway.svg) | [SVG](euro-science-gateway/eosc_euro_science_gateway_white.svg) | [SVG](euro-science-gateway/eosc_euro_science_gateway_black.svg)

## Banners And Posters

- [Euro Science Gateway roll-up banner](./euro-science-gateway/banner/ESG_banner.md)
- [Galaxy roll-up banner](./galaxy-galaxy/banner.md)
- [Galaxy render guide](./galaxy-galaxy/galaxy_render_guide.md)

## Stickers

Sticker print files and sources are in `stickers/`.

See [stickers/readme.md](stickers/readme.md) for sticker-specific notes.

## Maintenance Notes

- Keep source SVG files as the editable canonical version.
- Regenerate PNG/PDF previews after updating an SVG.
- Avoid editing generated rasters by hand unless the source file is unavailable.
- After updating factsheet stats, render a preview and inspect long values for text collisions.
