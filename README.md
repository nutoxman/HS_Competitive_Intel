# Recruitment Scenario Planner

Streamlit application for recruitment planning with scenario simulation, timeline solving, uncertainty visualization, and country-level advanced modeling.

## Repository

GitHub: [nutoxman/RecruitmentScenarioPlannerV2](https://github.com/nutoxman/RecruitmentScenarioPlannerV2)

## Core Capabilities

- `Simple` mode with five scenario tabs (`S1`-`S5`) plus a comparison view
- `Advanced` mode with multi-country configuration and global roll-up
- Solver-backed calculations for timeline and/or site requirements
- Uncertainty bands and optimistic/pessimistic timeline outputs
- Interactive charts (date-range control, timeline markers, chart styling editor)
- Advanced outputs: country summary, global roll-up, drill-down, pie/map views, and PDF export

## HS Competitive Intelligence Tracker

This repository now also includes a separate Streamlit app for HS competitive intelligence:

- App entrypoint: `/Users/stevensweeney/Desktop/Codex/ui/hs_tracker_app.py`
- Run command: `make run-hs`
- Backing package: `/Users/stevensweeney/Desktop/Codex/hs_tracker`

Implemented features:

- Program list with server-side rollups (activity score, staleness, quiet-but-advancing)
- Program detail page (overview, trials, timeline, sources)
- Trial explorer with inclusion/exclusion visibility
- Executive heatmap + CSV/PDF export
- QC dashboard + JSON export
- ClinicalTrials.gov ingestion workflow
- Sponsor source scraping workflow (RSS + source-specific press-release pages + pipeline pages)
- Sponsor pipeline deck scan workflow (latest 4 PDFs per sponsor directory)

Ingestion commands:

- `make hs-refresh-ctgov`
- `make hs-scan-sources`
- `make hs-scan-decks`
- `make hs-ingest-all`

Source config files:

- Runtime config: `/Users/stevensweeney/Desktop/Codex/data/source_configs/sponsor_sources.json`
- Editable example: `/Users/stevensweeney/Desktop/Codex/data/source_configs/sponsor_sources.example.json`

Scheduling templates:

- Cron template: `/Users/stevensweeney/Desktop/Codex/ops/cron/hs_tracker.cron.example`
- systemd templates: `/Users/stevensweeney/Desktop/Codex/ops/systemd/`

## Requirements

- Python `3.12+` (local workspace currently uses `3.14`)
- Dependencies in `requirements.txt`

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## Run

```bash
make run
```

Equivalent:

```bash
.venv/bin/streamlit run ui/app.py
```

## Test

```bash
make test
```

Equivalent:

```bash
.venv/bin/pytest
```

## Modes

### Simple Mode

Sidebar options:

- `Simple Scenario: # of Sites Drives Timeline`
- `Simple Scenario: Timeline Drives # of Sites`

Key behavior:

- Inputs persist when switching between app modes
- The two simple scenario drivers are isolated and retain independent values
- Scenario header is dynamic to selected simple driver
- `Recruitment Rate type (primary)` options: `Screened`, `Randomized`
- `Ramp Tuning` section is collapsible and includes:
  - `Site Activation Ramp: % sites active over time (FSFV to LSFV)`
  - `Recruitment Ramp Tuning: # of subjects <screened|randomized>/site/month`
- Cumulative chart controls:
  - `Show active sites by month`
  - `Show timeline markers` (FSFV/FSLV/LSFV/LSLV)
  - `X-axis date range` slider
  - `Edit chart` panel (palette, title, legend, font, line/bar style, colors)
- Comparison tab supports JSON import/export save/load

### Advanced Mode

Key behavior:

- Country-level configuration table (up to 20 countries)
- Country targets and SAR/RR milestone inputs drive enrollment curves
- Recruitment type must be selected before country selection is enabled
- Global uncertainty controls (optional)
- Outputs include:
  - Run Inputs Used
  - Country Summary (with cumulative totals, durations, recruitment rate)
  - Global roll-up
  - Global + country cumulative chart
  - Site activation over time
  - Country drill-down (collapsible)
  - Pie view (collapsible)
  - Map view (collapsible)
- Save/Load via JSON import/export
- PDF export from results section

## Save/Load Behavior

Current persisted workflow is JSON import/export from the app UI:

- Simple mode: Comparison tab -> `Save / Load Comparison`
- Advanced mode: `Save / Load` expander

Compatibility handling:

- Legacy simple mode label values are normalized on load
- Legacy `Completed` recruitment-period values are normalized to `Randomized` on load

## Deployment Notes (Streamlit Community Cloud)

For fast deployment:

1. Push `main` to GitHub.
2. Create app on Streamlit Community Cloud.
3. Use entrypoint: `ui/app.py`.
4. Add any required secrets in app settings.

Note: current built-in save/load workflow is JSON import/export; no hosted database is required for demo deployment.

## Project Structure

- `ui/` - Streamlit app pages, components, and persistence helpers
- `engine/` - scenario solvers and state derivation logic
- `export/` - advanced PDF report generation
- `data/` - country reference datasets
- `tests/` - unit/smoke tests

## Documentation

- Operator guide: `/Users/stevensweeney/Desktop/Codex/OPERATOR_GUIDE.md`
