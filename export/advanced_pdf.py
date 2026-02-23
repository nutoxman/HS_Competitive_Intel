from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


DATE_DISPLAY_FORMAT = "%d-%b-%Y"


def _max_cumulative(series: dict) -> float:
    return max(series.values()) if series else 0.0


def _format_date(value):
    if isinstance(value, date):
        return value.strftime(DATE_DISPLAY_FORMAT)
    return value


def _format_number(value):
    if value is None:
        return ""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return round(value, 2)
    return value


def _build_map_df(results: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for r in results:
        if not r.get("result"):
            continue
        out = r["result"]
        rows.append(
            {
                "iso3": r["iso3"],
                "country": r["country"],
                "region": r["region"],
                "screened_total": _max_cumulative(out.states.screened.cumulative),
                "randomized_total": _max_cumulative(out.states.randomized.cumulative),
                "completed_total": _max_cumulative(out.states.completed.cumulative),
                "sites": out.solve.solved_sites or 0,
            }
        )
    return pd.DataFrame(rows)


def _apply_metric(map_df: pd.DataFrame, metric: str, totals: dict[str, float]) -> pd.DataFrame:
    df = map_df.copy()
    if metric == "Randomized total":
        df["metric"] = df["randomized_total"]
    elif metric == "Completed total":
        df["metric"] = df["completed_total"]
    elif metric == "Screened total":
        df["metric"] = df["screened_total"]
    elif metric == "Sites":
        df["metric"] = df["sites"]
    elif metric == "Randomized % of global":
        denom = totals["randomized"] or 1.0
        df["metric"] = df["randomized_total"] / denom * 100.0
    elif metric == "Completed % of global":
        denom = totals["completed"] or 1.0
        df["metric"] = df["completed_total"] / denom * 100.0
    else:
        denom = totals["screened"] or 1.0
        df["metric"] = df["screened_total"] / denom * 100.0
    return df


def _fig_to_png(fig) -> bytes:
    return fig.to_image(format="png", engine="kaleido", scale=2)


def _build_global_chart(global_states, global_uncertainty, state: str) -> bytes | None:
    if global_states is None:
        return None

    series_map = {
        "Screened": global_states.screened.cumulative,
        "Randomized": global_states.randomized.cumulative,
        "Completed": global_states.completed.cumulative,
    }
    series = series_map[state]
    if not series:
        return None

    dates = sorted(series.keys())
    values = [series[d] for d in dates]

    fig = go.Figure()

    if global_uncertainty:
        lower_series = {
            "Screened": global_uncertainty["lower"].screened.cumulative,
            "Randomized": global_uncertainty["lower"].randomized.cumulative,
            "Completed": global_uncertainty["lower"].completed.cumulative,
        }[state]
        upper_series = {
            "Screened": global_uncertainty["upper"].screened.cumulative,
            "Randomized": global_uncertainty["upper"].randomized.cumulative,
            "Completed": global_uncertainty["upper"].completed.cumulative,
        }[state]

        band_dates = sorted(lower_series.keys())
        upper_vals = [upper_series.get(d, 0.0) for d in band_dates]
        lower_vals = [lower_series.get(d, 0.0) for d in band_dates]

        fig.add_trace(
            go.Scatter(
                x=band_dates,
                y=upper_vals,
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=band_dates,
                y=lower_vals,
                fill="tonexty",
                fillcolor="rgba(99,110,250,0.2)",
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
            )
        )

    fig.add_trace(
        go.Scatter(
            x=dates,
            y=values,
            mode="lines",
            name=state,
        )
    )

    fig.update_layout(
        title=f"Global {state} Cumulative",
        xaxis_title="Date",
        yaxis_title="Cumulative",
        margin=dict(l=20, r=20, t=40, b=20),
        height=300,
    )
    fig.update_xaxes(tickformat=DATE_DISPLAY_FORMAT)

    return _fig_to_png(fig)


def build_advanced_pdf(res: dict, session_state: dict, countries_df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch)
    styles = getSampleStyleSheet()

    story = []
    story.append(Paragraph("Recruitment Scenario Planner — Advanced Mode", styles["Title"]))
    story.append(Spacer(1, 0.2 * inch))

    driver = session_state.get("adv_driver", "")
    goal_type = session_state.get("adv_goal_type", "")
    goal_n = session_state.get("adv_goal_n", "")

    countries = res.get("countries", [])
    failed = [c for c in countries if c.get("status") != "ok"]
    ok = [c for c in countries if c.get("status") == "ok"]

    global_lslv = res.get("global_lslv")
    global_lslv_str = _format_date(global_lslv) if isinstance(global_lslv, date) else "N/A"

    exec_text = (
        f"Driver: {driver}. Goal: {goal_type} = {goal_n}. "
        f"Countries: {len(countries)} (failed: {len(failed)}). "
        f"Global LSLV: {global_lslv_str}."
    )
    story.append(Paragraph(exec_text, styles["BodyText"]))
    story.append(Spacer(1, 0.2 * inch))

    # Global timeline metrics
    fsfvs = []
    lsfvs = []
    config = session_state.get("adv_country_config", {})
    for row in config.values():
        if isinstance(row.get("FSFV"), date):
            fsfvs.append(row["FSFV"])
        if driver == "Fixed Timeline" and isinstance(row.get("LSFV"), date):
            lsfvs.append(row["LSFV"])

    if driver == "Fixed Sites":
        for c in ok:
            solved_lsfv = c.get("result").solve.solved_lsfv if c.get("result") else None
            if isinstance(solved_lsfv, date):
                lsfvs.append(solved_lsfv)

    global_fsfv = _format_date(min(fsfvs)) if fsfvs else "N/A"
    global_lsfv = _format_date(max(lsfvs)) if lsfvs else "N/A"

    timeline_table = Table(
        [
            ["Global FSFV", "Global LSFV", "Global LSLV"],
            [global_fsfv, global_lsfv, global_lslv_str],
        ]
    )
    timeline_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]
        )
    )
    story.append(timeline_table)
    story.append(Spacer(1, 0.2 * inch))

    # Country table
    rows = [
        [
            "Country",
            "Region",
            "Target Rand",
            "Target Comp",
            "Solved Sites",
            "Solved LSFV",
            "LSLV",
            "Status",
        ]
    ]
    for r in countries:
        if r.get("result"):
            out = r["result"]
            rows.append(
                [
                    r["country"],
                    r["region"],
                    _format_number(out.targets.randomized),
                    _format_number(out.targets.completed),
                    out.solve.solved_sites or "",
                    _format_date(out.solve.solved_lsfv) if out.solve.solved_lsfv else "",
                    _format_date(out.timelines.completed_lslv) if out.timelines.completed_lslv else "",
                    r.get("status"),
                ]
            )
        else:
            rows.append(
                [
                    r["country"],
                    r["region"],
                    "",
                    "",
                    "",
                    "",
                    "",
                    r.get("status"),
                ]
            )

    table = Table(rows, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(Paragraph("Country Summary", styles["Heading2"]))
    story.append(table)
    story.append(Spacer(1, 0.2 * inch))

    # Global chart
    global_chart_png = _build_global_chart(
        res.get("global_states"),
        res.get("global_uncertainty"),
        session_state.get("adv_global_state", "Randomized"),
    )
    if global_chart_png:
        story.append(Paragraph("Global Cumulative Chart", styles["Heading2"]))
        img_reader = ImageReader(BytesIO(global_chart_png))
        iw, ih = img_reader.getSize()
        width = 6.5 * inch
        height = ih * (width / iw)
        story.append(Image(img_reader, width=width, height=height))
        story.append(Spacer(1, 0.2 * inch))

    # Map + Pie
    map_df = _build_map_df(countries)
    if not map_df.empty:
        totals = {
            "screened": map_df["screened_total"].sum(),
            "randomized": map_df["randomized_total"].sum(),
            "completed": map_df["completed_total"].sum(),
        }
        metric = session_state.get("adv_map_metric", "Randomized total")
        view = session_state.get("adv_map_view", "World")

        map_df = _apply_metric(map_df, metric, totals)
        if view != "World":
            map_df = map_df[map_df["region"] == view]

        if not map_df.empty:
            fig = px.choropleth(
                map_df,
                locations="iso3",
                color="metric",
                hover_name="country",
                color_continuous_scale="YlOrRd",
            )
            if view != "World":
                fig.update_geos(fitbounds="locations", visible=False)
            fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=400)

            map_png = _fig_to_png(fig)
            story.append(Paragraph("Map View", styles["Heading2"]))
            img_reader = ImageReader(BytesIO(map_png))
            iw, ih = img_reader.getSize()
            width = 6.5 * inch
            height = ih * (width / iw)
            story.append(Image(img_reader, width=width, height=height))
            story.append(Spacer(1, 0.2 * inch))

            if session_state.get("adv_pie_enabled"):
                pie_df = map_df.copy()
                pie_scope = session_state.get("adv_pie_scope", "Region")
                pie_family = session_state.get("adv_pie_metric_family", "Enrollment")
                pie_state = session_state.get("adv_pie_state", "Randomized")
                pie_label = session_state.get("adv_pie_label_mode", "Both")

                if pie_scope == "Region" and view == "World":
                    pie_df = pie_df.groupby("region", as_index=False).sum(numeric_only=True)
                    names_col = "region"
                else:
                    names_col = "country"

                if pie_family == "Sites":
                    pie_df["pie_value"] = pie_df["sites"]
                else:
                    if pie_state == "Screened":
                        pie_df["pie_value"] = pie_df["screened_total"]
                    elif pie_state == "Completed":
                        pie_df["pie_value"] = pie_df["completed_total"]
                    else:
                        pie_df["pie_value"] = pie_df["randomized_total"]

                if not pie_df.empty:
                    fig_pie = px.pie(pie_df, names=names_col, values="pie_value")
                    if pie_label == "Percent":
                        fig_pie.update_traces(textinfo="percent")
                    elif pie_label == "Value":
                        fig_pie.update_traces(textinfo="value")
                    else:
                        fig_pie.update_traces(textinfo="percent+value")

                    fig_pie.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=300)
                    pie_png = _fig_to_png(fig_pie)

                    story.append(Paragraph("Pie Overlay", styles["Heading2"]))
                    img_reader = ImageReader(BytesIO(pie_png))
                    iw, ih = img_reader.getSize()
                    width = 4.5 * inch
                    height = ih * (width / iw)
                    story.append(Image(img_reader, width=width, height=height))
                    story.append(Spacer(1, 0.2 * inch))

    # Warnings
    warnings = res.get("warnings", [])
    if warnings:
        story.append(Paragraph("Warnings", styles["Heading2"]))
        for w in warnings:
            story.append(Paragraph(w, styles["BodyText"]))

    doc.build(story)
    return buf.getvalue()
