# Recruitment Scenario Planner

Streamlit application for recruitment scenario planning with:

- Simple mode (up to 5 scenarios + comparison)
- Advanced mode (multi-country allocation and roll-up)
- Solver-backed timeline/site calculations
- Uncertainty bands, map/pie analytics, and PDF export

## Repository

GitHub: [nutoxman/RecruitmentScenarioPlannerV2](https://github.com/nutoxman/RecruitmentScenarioPlannerV2)

## Requirements

- Python 3.14 (as used in this workspace)
- Virtual environment with dependencies from `requirements.txt`

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

Equivalent command:

```bash
.venv/bin/streamlit run ui/app.py
```

## Test

```bash
make test
```

Equivalent command:

```bash
.venv/bin/pytest
```

## Modes

### Simple mode

- Two drivers:
- `# of Sites Drives Timeline` (fixed sites, solve for LSFV)
- `Timeline Drives # of Sites` (fixed timeline, solve for sites)
- Five scenario tabs (`S1-S5`) plus comparison tab
- Scenario copy, save/load JSON, uncertainty bands
- Dynamic chart date-range selectors on scenario and comparison charts

### Advanced mode

- Single global scenario split across up to 20 countries
- Weight-based integer goal allocation
- Country-level runs + global aggregation
- Map and pie analytics, country drill-down
- Dynamic chart date-range selectors on global/site/country charts
- Save/load JSON and PDF export

## Current UI behavior highlights

- Sidebar mode selector label: `Select one`
- App baseline font: 10pt
- Display date format: `dd-mmm-yyyy`
- Date input widget format: `dd-mm-yyyy` (Streamlit limitation)
- `Solve For` label replaces `Goal Type`
- `Recruitment Rate type (primary)` replaces recruitment-period label
- Primary-rate dropdown restricted to `Screened` and `Randomized`

## Documentation

- Operator guide: `/Users/stevensweeney/Desktop/Codex/OPERATOR_GUIDE.md`

## Project structure

- `ui/` - Streamlit UI and persistence
- `engine/` - solver and series derivation logic
- `export/` - advanced PDF report generation
- `data/` - country reference datasets
- `tests/` - unit and smoke tests
