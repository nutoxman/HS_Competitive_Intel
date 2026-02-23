# Recruitment Scenario Planner - Operator Guide

This guide covers day-to-day operation of the Streamlit app.

## 1) Quick start

From `/Users/stevensweeney/Desktop/Codex`:

```bash
make run
```

Run tests:

```bash
make test
```

## 2) Global UI behavior

- Sidebar mode selector label is `Select one`.
- App UI baseline font is set to 10pt.
- Table cells are centered globally for both text and numeric values.
- Displayed dates use `dd-mmm-yyyy` across charts, tables, timelines, and PDF output.
- Date input widgets use `dd-mm-yyyy` (Streamlit input-format limitation).

## 3) Modes

Sidebar options:

- `Simple Scenario: Simple Scenario: # of Sites Drives Timeline`
- `Simple Scenario: Timeline Drives # of Sites`
- `Advanced`

## 4) Simple mode

### 4.1 Page title and defaults

Page title changes by selected simple mode and is rendered at 12pt:

- `Simple Mode: # of Sites Drives Timeline`
- `Simple Mode: Timeline Drives # of Sites`

Per-scenario defaults on first initialization:

- `FSFV = today`
- `LSFV = today + 1 year`
- `Sites = 10`
- `Lag Screened -> Randomized = 14`
- `Lag Randomized -> Completed = 60`

### 4.2 Inputs

- `Goal Type` is renamed to `Solve For`.
- Values display as `Total Randomized` and `Total Completed`.
- `Recruitment period type (primary)` is renamed to `Recruitment Rate type (primary)`.
- Primary-period options are restricted to `Screened` and `Randomized`.

### 4.3 RR and SAR tables

RR table behavior:

- RR table is shown first after the input fields.
- Label remains dynamic by selected primary period (screened/randomized wording).
- First column title is `#/site/month`.
- Row label `RR` is changed to `Rate`.
- Milestone header `0%` is changed to `0% (FSFV)`.

SAR table behavior:

- Milestone header `0%` is changed to `0% (FSFV)`.

Calculated milestone output tables for RR and SAR also use `0% (FSFV)`.

### 4.4 Copy controls

- `Copy inputs from:` uses a fixed-width dropdown (~1 inch / 96px).
- Copy controls are hidden until at least one scenario has been run.
- Once visible, copy behavior remains per scenario tab (source -> current tab).

### 4.5 Chart date range controls

Simple mode includes user-editable date windows:

- Scenario cumulative chart: `Display date range`
- Comparison chart: `Display date range`

Comparison default x-axis range:

- Start = earliest available date in merged included scenarios.
- End = latest solved completion timeline across included scenarios + 30 days.

### 4.6 Save/load (Simple)

In `Comparison` tab:

- Download: saved comparison JSON.
- Load: restores scenario state.
- Loaded scenarios clear prior results and require rerun.

Legacy compatibility:

- If loaded data has primary period `Completed`, it auto-converts to `Randomized`.

## 5) Advanced mode

### 5.1 Defaults and global inputs

Advanced defaults on first initialization:

- `Default FSFV = today`
- `Default LSFV = today + 1 year`
- `Default Sites = 10`
- `Lag Screened -> Randomized = 14`
- `Lag Randomized -> Completed = 60`

Input labels and options:

- `Goal Type` -> `Solve For`
- Value display: `Total Randomized` / `Total Completed`
- `Recruitment period type (primary)` -> `Recruitment Rate type (primary)`
- Primary-period options: `Screened`, `Randomized`

### 5.2 Country configuration

- Country table date editors use `dd-mm-yyyy` entry format.
- Derived global FSFV informational message uses `dd-mmm-yyyy` display.

### 5.3 Chart date range controls

Advanced mode includes user-editable date windows:

- Global + country cumulative curves: `Display date range`
- Site activation chart: `Display site activation date range`
- Country drill-down chart: `Display country date range`

### 5.4 Save/load and compatibility

- Save/load advanced scenario JSON via `Save / Load` section.
- Loading clears prior advanced results.
- Legacy loaded `adv_period_type=Completed` auto-converts to `Randomized`.

### 5.5 Export

- PDF export preserves `dd-mmm-yyyy` date display.

## 6) Guardrails and common errors

- Screen-fail and discontinuation rates must be in `[0,1)`.
- `LSFV` must be after `FSFV`.
- SAR must have 6 values in `0-100`.
- RR must have 6 numeric values `>= 0`.
- Solver guardrails apply (`max_sites`, `max_duration_days`).

If target is unreachable, adjust one or more:

- Increase sites.
- Extend timeline.
- Increase SAR/RR assumptions.
- Lower target.
- Reduce lag/failure/discontinuation assumptions.

## 7) Key files

- App entry: `/Users/stevensweeney/Desktop/Codex/ui/app.py`
- Simple mode orchestration: `/Users/stevensweeney/Desktop/Codex/ui/app_simple.py`
- Shared simple components: `/Users/stevensweeney/Desktop/Codex/ui/components.py`
- Advanced mode: `/Users/stevensweeney/Desktop/Codex/ui/app_advanced.py`
- Persistence and load compatibility: `/Users/stevensweeney/Desktop/Codex/ui/persistence.py`
- Advanced PDF export: `/Users/stevensweeney/Desktop/Codex/export/advanced_pdf.py`
- Engine orchestration: `/Users/stevensweeney/Desktop/Codex/engine/core/run_simple.py`
