# ruff: noqa: E402
from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hs_tracker.config import load_config
from hs_tracker.constants import DEFAULT_ROLLING_YEARS, EVENT_TYPE_TO_CATEGORY
from hs_tracker.db import connect, init_db
from hs_tracker.ingestion.clinicaltrials import refresh_clinicaltrials
from hs_tracker.ingestion.decks import scan_all_sponsors
from hs_tracker.ingestion.sources import scan_sponsor_sources
from hs_tracker.qc import build_qc_report
from hs_tracker.seed import seed_default_products
from hs_tracker.service import (
    add_manual_event,
    compute_program_metrics,
    ensure_default_settings,
    get_program_detail,
    list_products_with_aliases,
    list_trials,
    upsert_product,
)


st.set_page_config(page_title="HS CI Tracker", layout="wide")
st.title("HS Clinical Trial Competitive Intelligence Tracker")


def _load_state(rolling_years: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = load_config()
    with connect(cfg.db_path) as conn:
        init_db(conn)
        ensure_default_settings(conn)
        programs = compute_program_metrics(
            conn, as_of=date.today(), rolling_years=rolling_years
        )
        trials = list_trials(conn, included_only=False)

    program_columns = [
        "product_id",
        "canonical_name",
        "company",
        "modality",
        "target_class",
        "highest_phase_hs",
        "status_summary",
        "activity_score_12m",
        "last_event_date",
        "last_high_signal_date",
        "days_since_high_signal",
        "staleness_flag",
        "quiet_but_advancing",
        "hs_activity_5y",
        "all_names_display",
        "geographies",
    ]
    trial_columns = [
        "trial_id",
        "product_id",
        "sponsor_display",
        "phase",
        "status",
        "study_start_date",
        "last_update_posted",
        "results_first_posted",
        "inclusion_flag",
        "exclusion_reason",
        "url",
    ]

    programs_df = pd.DataFrame(programs).reindex(columns=program_columns)
    trials_df = pd.DataFrame(trials).reindex(columns=trial_columns)

    if rolling_years and not trials_df.empty:
        cutoff_year = date.today().year - rolling_years
        trials_df["study_start_date"] = pd.to_datetime(
            trials_df["study_start_date"], errors="coerce"
        )
        trials_df = trials_df[trials_df["study_start_date"].dt.year >= cutoff_year]

    return programs_df, trials_df


def _to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def _heatmap_pdf(df: pd.DataFrame) -> bytes:
    fig, ax = plt.subplots(figsize=(11, max(4, 0.35 * len(df))))
    if df.empty:
        ax.text(0.5, 0.5, "No heatmap rows", ha="center", va="center")
        ax.axis("off")
    else:
        chart = df[["activity_score_12m", "days_since_high_signal"]].fillna(0).to_numpy()
        im = ax.imshow(chart, aspect="auto", cmap="YlOrRd")
        ax.set_yticks(range(len(df)))
        ax.set_yticklabels(df["canonical_name"].tolist(), fontsize=8)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["Activity Score (12M)", "Days Since High Signal"])
        ax.set_title("HS Executive Heatmap")
        fig.colorbar(im, ax=ax, shrink=0.6)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="pdf")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _program_filters(df: pd.DataFrame) -> pd.DataFrame:
    def _unique(col: str) -> list[str]:
        if col not in df.columns:
            return []
        return sorted(df[col].dropna().unique())

    with st.sidebar:
        st.header("Filters")
        companies = st.multiselect("Company", _unique("company"))
        modalities = st.multiselect("Modality", _unique("modality"))
        target_classes = st.multiselect("Target class", _unique("target_class"))
        phases = st.multiselect("Highest phase", _unique("highest_phase_hs"))
        staleness = st.multiselect("Staleness", _unique("staleness_flag"))
        quiet_filter = st.selectbox("Quiet but advancing", ["All", "Yes", "No"])
        geo_filter = st.text_input("Geography contains")

    out = df.copy()
    if companies:
        out = out[out["company"].isin(companies)]
    if modalities:
        out = out[out["modality"].isin(modalities)]
    if target_classes and "target_class" in out:
        out = out[out["target_class"].isin(target_classes)]
    if phases and "highest_phase_hs" in out:
        out = out[out["highest_phase_hs"].isin(phases)]
    if staleness and "staleness_flag" in out:
        out = out[out["staleness_flag"].isin(staleness)]
    if quiet_filter != "All":
        out = out[out["quiet_but_advancing"] == (quiet_filter == "Yes")]
    if geo_filter:
        out = out[
            out["geographies"].apply(
                lambda g: geo_filter.lower() in " ".join(g if isinstance(g, list) else []).lower()
            )
        ]
    return out


def _render_program_list(programs_df: pd.DataFrame) -> pd.DataFrame:
    st.subheader("Program List")
    filtered = _program_filters(programs_df)

    sort_col = st.selectbox(
        "Sort by",
        ["activity_score_12m", "days_since_high_signal", "highest_phase_hs", "company"],
        index=0,
    )
    ascending = st.checkbox("Ascending", value=False)

    display = filtered.copy()
    if sort_col in display.columns:
        display = display.sort_values(by=sort_col, ascending=ascending, na_position="last")

    columns = [
        "canonical_name",
        "company",
        "modality",
        "highest_phase_hs",
        "status_summary",
        "activity_score_12m",
        "last_event_date",
        "last_high_signal_date",
        "days_since_high_signal",
        "staleness_flag",
        "quiet_but_advancing",
        "hs_activity_5y",
        "all_names_display",
    ]
    cols = [col for col in columns if col in display.columns]
    st.dataframe(display[cols], use_container_width=True)

    st.download_button(
        "Export Programs CSV",
        data=_to_csv_bytes(display[cols]),
        file_name="hs_programs.csv",
        mime="text/csv",
    )
    return display


def _render_program_detail() -> None:
    st.subheader("Program Detail")
    cfg = load_config()
    with connect(cfg.db_path) as conn:
        init_db(conn)
        ensure_default_settings(conn)
        products = list_products_with_aliases(conn)

    if not products:
        st.info("No products loaded yet. Use Admin tab to add products or seed defaults.")
        return

    id_to_label = {item["product_id"]: f"{item['canonical_name']} ({item['company']})" for item in products}
    product_id = st.selectbox("Select program", options=list(id_to_label.keys()), format_func=id_to_label.get)

    with connect(cfg.db_path) as conn:
        detail = get_program_detail(conn, product_id)

    if not detail:
        st.warning("Program not found.")
        return

    product = detail["product"]
    st.markdown(
        f"**{product['canonical_name']}** | Company: {product['company']} | Modality: {product['modality']}"
    )

    overview_tab, trials_tab, timeline_tab, sources_tab = st.tabs(
        ["Overview", "Trials", "Activity timeline", "Sources"]
    )

    with overview_tab:
        st.json(
            {
                "canonical_name": product["canonical_name"],
                "aliases": product.get("aliases", []),
                "target_class": product.get("target_class"),
                "targets": product.get("targets"),
                "dosing_route": product.get("dosing_route"),
                "notes": product.get("notes"),
            }
        )

    with trials_tab:
        trials_df = pd.DataFrame(detail["trials"])
        if trials_df.empty:
            st.info("No trials linked.")
        else:
            st.dataframe(
                trials_df[
                    [
                        "trial_id",
                        "phase",
                        "status",
                        "study_start_date",
                        "last_update_posted",
                        "results_first_posted",
                        "inclusion_flag",
                        "exclusion_reason",
                        "url",
                    ]
                ],
                use_container_width=True,
            )

    with timeline_tab:
        events_df = pd.DataFrame(detail["events"])
        if events_df.empty:
            st.info("No activity events linked.")
        else:
            event_types = st.multiselect(
                "Event type filter",
                sorted(events_df["event_type"].dropna().unique()),
                default=[],
                key=f"event_filter_{product_id}",
            )
            if event_types:
                events_df = events_df[events_df["event_type"].isin(event_types)]
            events_df = events_df.sort_values(by="event_date", ascending=False)
            st.dataframe(
                events_df[
                    [
                        "event_date",
                        "event_type",
                        "signal_category",
                        "event_summary",
                        "source_name",
                        "source_url",
                        "weight",
                        "high_signal",
                    ]
                ],
                use_container_width=True,
            )

    with sources_tab:
        sources_df = pd.DataFrame(detail["sources"])
        if sources_df.empty:
            st.info("No sources available.")
        else:
            st.dataframe(sources_df, use_container_width=True)


def _render_trial_explorer(trials_df: pd.DataFrame) -> None:
    st.subheader("Trial Explorer")
    if trials_df.empty:
        st.info("No trials ingested yet.")
        return

    include_only = st.checkbox("Included trials only", value=True)
    search = st.text_input("Search trial ID/sponsor/product ID")

    df = trials_df.copy()
    if include_only and "inclusion_flag" in df:
        df = df[df["inclusion_flag"] == 1]
    if search:
        q = search.lower()
        df = df[
            df["trial_id"].fillna("").str.lower().str.contains(q)
            | df["sponsor_display"].fillna("").str.lower().str.contains(q)
            | df["product_id"].fillna("").str.lower().str.contains(q)
        ]

    st.dataframe(
        df[
            [
                "trial_id",
                "product_id",
                "sponsor_display",
                "phase",
                "status",
                "study_start_date",
                "last_update_posted",
                "results_first_posted",
                "inclusion_flag",
                "exclusion_reason",
                "url",
            ]
        ],
        use_container_width=True,
    )

    st.download_button(
        "Export Trials CSV",
        data=_to_csv_bytes(df),
        file_name="hs_trials.csv",
        mime="text/csv",
    )


def _render_heatmap(programs_df: pd.DataFrame) -> None:
    st.subheader("Executive Heatmap")
    if programs_df.empty:
        st.info("No programs available.")
        return

    heat = programs_df[
        [
            "canonical_name",
            "modality",
            "activity_score_12m",
            "days_since_high_signal",
            "staleness_flag",
            "quiet_but_advancing",
            "included_trial_count",
        ]
    ].copy()
    heat = heat.sort_values(by=["activity_score_12m", "days_since_high_signal"], ascending=[False, True])

    st.dataframe(heat, use_container_width=True)

    now = pd.Timestamp.today().normalize()
    events_recent_30 = []
    events_recent_90 = []
    if "last_event_date" in programs_df:
        dates = pd.to_datetime(programs_df["last_event_date"], errors="coerce")
        events_recent_30 = programs_df[dates >= now - pd.Timedelta(days=30)]["canonical_name"].tolist()
        events_recent_90 = programs_df[dates >= now - pd.Timedelta(days=90)]["canonical_name"].tolist()

    stagnant = programs_df[
        programs_df["staleness_flag"].str.startswith("Red")
        & (~programs_df["status_summary"].str.contains("RECRUITING|ACTIVE", case=False, na=False))
    ]["canonical_name"].tolist()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Top movers (30d)**")
        st.write(events_recent_30[:10] or ["None"])
    with col2:
        st.markdown("**Top movers (90d)**")
        st.write(events_recent_90[:10] or ["None"])
    with col3:
        st.markdown("**Stagnant candidates**")
        st.write(stagnant[:10] or ["None"])

    st.download_button(
        "Export Heatmap CSV",
        data=_to_csv_bytes(heat),
        file_name="hs_heatmap.csv",
        mime="text/csv",
    )
    st.download_button(
        "Export Heatmap PDF",
        data=_heatmap_pdf(heat),
        file_name="hs_heatmap_snapshot.pdf",
        mime="application/pdf",
    )


def _render_qc_dashboard() -> None:
    st.subheader("QC Dashboard")
    cfg = load_config()
    with connect(cfg.db_path) as conn:
        report = build_qc_report(conn)

    summary_df = pd.DataFrame(
        [{"check": key, "count": value} for key, value in report.get("summary", {}).items()]
    )
    st.dataframe(summary_df, use_container_width=True)

    check_key = st.selectbox(
        "Inspect QC check",
        [key for key in report.keys() if key not in {"summary"}],
    )
    details = report.get(check_key, [])
    if isinstance(details, list):
        st.dataframe(pd.DataFrame(details), use_container_width=True)
    else:
        st.json(details)

    st.download_button(
        "Export QC Report (JSON)",
        data=json.dumps(report, indent=2).encode("utf-8"),
        file_name="hs_qc_report.json",
        mime="application/json",
    )


def _render_admin() -> None:
    st.subheader("Admin + Ingestion")
    cfg = load_config()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Seed default products"):
            with connect(cfg.db_path) as conn:
                count = seed_default_products(conn)
            st.success(f"Seeded/updated {count} products")

    with col2:
        rolling_years = st.number_input(
            "Rolling years",
            min_value=1,
            max_value=10,
            value=DEFAULT_ROLLING_YEARS,
            step=1,
        )
        if st.button("Run ClinicalTrials refresh"):
            try:
                with connect(cfg.db_path) as conn:
                    stats = refresh_clinicaltrials(conn, rolling_years=int(rolling_years))
                st.success(f"ClinicalTrials refresh complete: {stats}")
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
                st.info(
                    "If your network uses SSL interception, set "
                    "`HS_TRACKER_CA_BUNDLE=/path/to/ca-bundle.pem` or, for local "
                    "testing only, `HS_TRACKER_SKIP_SSL_VERIFY=1`."
                )

    col3, col4 = st.columns(2)
    with col3:
        source_config = st.text_input(
            "Source config file",
            value="data/source_configs/sponsor_sources.json",
        )
        if st.button("Run sponsor PR/pipeline-page scan"):
            try:
                with connect(cfg.db_path) as conn:
                    stats = scan_sponsor_sources(conn, config_path=Path(source_config))
                st.success(f"Source scan complete: {stats}")
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))

    with col4:
        deck_root = st.text_input("Deck root directory", value="data/pipeline_decks")
        if st.button("Run sponsor deck scan"):
            try:
                with connect(cfg.db_path) as conn:
                    stats = scan_all_sponsors(conn, Path(deck_root))
                st.success(f"Deck scan complete: {stats}")
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))

    st.markdown("### Add or update product")
    with st.form("product_form"):
        c1, c2, c3 = st.columns(3)
        canonical_name = c1.text_input("Canonical name")
        company = c2.text_input("Company")
        modality = c3.selectbox("Modality", ["Small molecule", "Antibody", "Oligonucleotide", "Other"])
        aliases = st.text_input("Aliases (comma-separated)")
        target_class = st.text_input("Target class")
        targets = st.text_input("Target(s)")
        dosing_route = st.text_input("Dosing route")
        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Save product")
    if submitted:
        with connect(cfg.db_path) as conn:
            pid = upsert_product(
                conn,
                canonical_name=canonical_name,
                company=company,
                modality=modality,
                aliases=[a.strip() for a in aliases.split(",") if a.strip()],
                target_class=target_class or None,
                targets=targets or None,
                dosing_route=dosing_route or None,
                notes=notes or None,
            )
        st.success(f"Saved product {canonical_name} ({pid})")

    st.markdown("### Manual event entry")
    with connect(cfg.db_path) as conn:
        products = list_products_with_aliases(conn)
    if not products:
        st.info("Add at least one product first.")
        return

    label_map = {p["product_id"]: f"{p['canonical_name']} ({p['company']})" for p in products}
    with st.form("event_form"):
        product_id = st.selectbox("Product", list(label_map.keys()), format_func=label_map.get)
        event_date = st.date_input("Event date", value=date.today()).isoformat()
        event_type = st.selectbox("Event type", sorted(EVENT_TYPE_TO_CATEGORY.keys()))
        event_summary = st.text_area("Event summary")
        source_type = st.selectbox(
            "Source type",
            [
                "registry",
                "press_release",
                "pipeline_deck",
                "pipeline_page",
                "publication",
                "conference",
                "news",
                "regulatory_filing",
            ],
        )
        source_name = st.text_input("Source name")
        source_url = st.text_input("Source URL or file path")
        confidence = st.selectbox("Confidence", ["High", "Medium", "Low"])
        impact = st.selectbox("Impact", ["High", "Medium", "Low"])
        manual_weight = st.number_input("Weight override (optional)", min_value=0, max_value=20, value=0)
        high_signal = st.checkbox("High signal")
        submitted = st.form_submit_button("Add event")

    if submitted:
        with connect(cfg.db_path) as conn:
            event_id = add_manual_event(
                conn,
                product_id=product_id,
                event_date=event_date,
                event_type=event_type,
                event_summary=event_summary,
                source_type=source_type,
                source_name=source_name or "Manual",
                source_url=source_url or None,
                confidence=confidence,
                impact=impact,
                weight=None if manual_weight == 0 else int(manual_weight),
                high_signal=high_signal,
            )
        if event_id:
            st.success(f"Added event {event_id}")
        else:
            st.warning("Duplicate event detected; nothing inserted.")


with st.sidebar:
    rolling_years = st.number_input(
        "Study start rolling window (years)", min_value=1, max_value=10, value=DEFAULT_ROLLING_YEARS
    )
    page = st.radio(
        "Page",
        [
            "Program list",
            "Program detail",
            "Trial explorer",
            "Executive heatmap",
            "QC dashboard",
            "Admin",
        ],
    )

programs_df, trials_df = _load_state(rolling_years=int(rolling_years))

if page == "Program list":
    _render_program_list(programs_df)
elif page == "Program detail":
    _render_program_detail()
elif page == "Trial explorer":
    _render_trial_explorer(trials_df)
elif page == "Executive heatmap":
    _render_heatmap(programs_df)
elif page == "QC dashboard":
    _render_qc_dashboard()
else:
    _render_admin()
