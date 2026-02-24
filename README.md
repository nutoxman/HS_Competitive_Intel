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

## Latest Enhancements

- Canonical simple mode label is now `Simple Scenario: # of Sites Drives Timeline` (legacy saved label still loads).
- Simple mode inputs persist when switching to `Advanced` and back.
- The two simple drivers are isolated from each other (independent values per mode).
- Scenario input headers are dynamic by selected driver: `Scenario Sx Inputs: # of Sites Drives Timeline` and `Scenario Sx Inputs: Timeline Drives # of Sites`.
- Input layout in simple mode is now mode-specific with a 4-column arrangement.
- `Recruitment Rate type (primary)` defaults to `Screened` for new simple scenarios.
- RR and SAR input table text color is `#09CFEA`.
- Summary typography is standardized to 10pt, and `Avg Randomized/site/month` plus `Avg Screened/site/month` are shown with solved outputs.
- Uncertainty labels now read `Pessimistic: Lower % (below)` and `Optimistic: Upper % (above)`.
- Summary can show `Optimistic Timelines` and `Pessimistic Timelines` alongside base `Timelines`.
- Cumulative series extends to pessimistic `LSLV` when uncertainty is enabled.
- Scenario chart control is now `X-axis date range` (slider below the chart).
- Optional `Show timeline markers` toggle is available below `Show active sites by month`.
- Timeline markers include `FSFV`, `FSLV`, `LSFV`, and `LSLV` as bright yellow dotted vertical lines.
- Legend order is fixed to `Screened`, `Randomized`, `Completed` with title `# of Subjects`.
- Axes show tick marks and vertical grid lines.
- Active-sites overlay bars were widened.
- Comparison chart x-axis defaults extend one month past latest solved completion date and support the same `X-axis date range` slider.

## Modes

### Simple mode

- Drivers: `Simple Scenario: # of Sites Drives Timeline` (fixed sites, solve for LSFV) and `Simple Scenario: Timeline Drives # of Sites` (fixed timeline, solve for sites)
- Five scenario tabs (`S1-S5`) plus comparison tab
- Scenario copy controls in a single row (dropdown + button)
- Save/load JSON in comparison tab
- Uncertainty bands and timeline projections
- X-axis date range sliders for scenario and comparison charts

### Advanced mode

- Single global scenario split across up to 20 countries
- Weight-based integer goal allocation
- Country-level runs + global aggregation
- Uncertainty support on country/global curves
- Map and pie analytics, country drill-down
- X-axis date range sliders on global/site/country charts
- Save/load JSON and PDF export

## Current UI Behavior Highlights

- Sidebar mode selector title: `Mode`
- Sidebar mode selector label: `Select one`
- App baseline font: 10pt
- Display date format: `dd-mmm-yyyy`
- Date input widget format: `dd-mm-yyyy` (Streamlit limitation)
- `Solve For` replaces `Goal Type`
- `Recruitment Rate type (primary)` replaces recruitment-period naming
- Primary-rate options are `Screened` and `Randomized`

## Save/Load Compatibility

- Legacy simple mode label values are normalized automatically on load.
- Legacy `Completed` primary-period values are auto-converted to `Randomized` when loading saved files.

## Documentation

- Operator guide: `/Users/stevensweeney/Desktop/Codex/OPERATOR_GUIDE.md`

## Project Structure

- `ui/` - Streamlit UI and persistence
- `engine/` - solver and series derivation logic
- `export/` - advanced PDF report generation
- `data/` - country reference datasets
- `tests/` - unit and smoke tests
