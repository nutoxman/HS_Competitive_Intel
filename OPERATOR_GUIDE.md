# Recruitment Scenario Planner - Operator Guide

This guide describes day-to-day operation of the app.

## 1) Launch and Verification

From `/Users/stevensweeney/Desktop/Codex`:

```bash
make run
```

Optional test pass:

```bash
make test
```

When app is running, verify:

- Sidebar title: `Mode`
- Mode selector label: `Select one`
- Available modes:
  - `Simple Scenario: # of Sites Drives Timeline`
  - `Simple Scenario: Timeline Drives # of Sites`
  - `Advanced`

## 2) Global Behavior

- App baseline typography is tuned to 10pt.
- Displayed dates use `dd-mmm-yyyy` in charts/tables.
- Date input widgets use `dd-mm-yyyy`.
- Switching between Simple and Advanced preserves mode-specific state.

## 3) Simple Mode Operations

### 3.1 Scenario Setup and Run

1. Choose one of the two Simple modes in sidebar.
2. Open scenario tab `S1`-`S5`.
3. Enter scenario inputs.
4. Expand `Site Activation and Enrollment Rate Ramp Tuning` if needed.
5. Click `Run Sx`.

Notes:

- `Recruitment Rate type (primary)` supports `Screened` and `Randomized`.
- Copy controls are available when prior scenario results exist.

### 3.2 Review Results

After run, review in order:

1. `Summary`
2. `Cumulative recruitment over time`
3. Bucket and milestone tables

Chart controls:

- `Show active sites by month`
- `Show timeline markers`
- `X-axis date range`

### 3.3 Use Edit Chart

Below the `X-axis date range` slider, click `Edit chart`.

The control panel is arranged in 4 columns:

1. Reset / palette / font controls
2. Title + legend text/position controls
3. Line and opacity/bar-width controls
4. Manual color selectors

Default behavior:

- Default palette is `High contrast`.
- `Reset chart style` restores defaults (including `High contrast`).

### 3.4 Comparison View

Open `Comparison` tab.

- Choose state to compare (`Screened`, `Randomized`, `Completed`).
- Included scenarios are controlled by each scenario's `Include in comparison` checkbox.

Save/load:

- Section: `Save / Load Comparison`
- Workflow: JSON import/export (`Download saved comparison (.json)` / `Load saved comparison (.json)`)

## 4) Advanced Mode Operations

### 4.1 Configure and Run

1. Select `Advanced` mode.
2. Set `Recruitment Rate type (primary)` first.
3. Select countries (up to 20).
4. Edit `Country Configuration` table:
   - FSFV, Sites, Target, SAR milestones, RR milestones
5. Optional: configure `Global Inputs` and uncertainty.
6. Click `Run Advanced Scenario`.

### 4.2 Review Advanced Outputs

Primary sections:

1. `Run Inputs Used`
2. `Country Summary`
3. `Global Roll-up`
4. `Global + Country Cumulative Curves`
5. `Site Activation Over Time`
6. `Country Drill-down` (collapsible)
7. `Pie View` (collapsible)
8. `Map View` (collapsible)

Chart controls:

- Date range sliders are available on global, site activation, and drill-down charts.
- Chart Options panel controls global and country line colors.

### 4.3 Save/Load and Export

- Save/load section: `Save / Load` expander
- Workflow: JSON import/export only
- PDF output: `Export PDF` expander

## 5) Data and Persistence Behavior

Current operator-facing persistence is JSON import/export.

- Loading a JSON scenario resets prior solved results and requires rerun.
- Compatibility normalization is applied for legacy values where needed.

## 6) Common Validation Rules

Expect validation errors when:

- Required country fields are blank
- Sites/targets are non-integer or non-positive
- SAR values are outside `[0, 100]`
- RR values are negative

Resolution workflow:

1. Correct highlighted inputs.
2. Re-run scenario.

## 7) Key Files

- App entry: `/Users/stevensweeney/Desktop/Codex/ui/app.py`
- Simple mode page: `/Users/stevensweeney/Desktop/Codex/ui/app_simple.py`
- Shared simple components/charts: `/Users/stevensweeney/Desktop/Codex/ui/components.py`
- Advanced mode page: `/Users/stevensweeney/Desktop/Codex/ui/app_advanced.py`
- Save/load serialization: `/Users/stevensweeney/Desktop/Codex/ui/persistence.py`
- PDF export: `/Users/stevensweeney/Desktop/Codex/export/advanced_pdf.py`
