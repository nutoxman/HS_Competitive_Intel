from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from hs_tracker.db import init_db
from hs_tracker.ingestion.sources import FetchResponse, scan_sponsor_sources
from hs_tracker.service import ensure_default_settings, upsert_product


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    ensure_default_settings(conn)
    return conn


def _write_config(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_scan_sponsor_sources_rss_feed_emits_press_release_event(tmp_path: Path) -> None:
    conn = _conn()
    upsert_product(
        conn,
        canonical_name="Remibrutinib",
        company="Novartis",
        modality="Small molecule",
        aliases=["LYS006"],
    )

    config_path = _write_config(
        tmp_path / "sources.json",
        {
            "sponsors": [
                {
                    "sponsor": "Novartis",
                    "company": "Novartis",
                    "press_release_feeds": [
                        {"name": "Novartis RSS", "url": "https://example.com/rss.xml"}
                    ],
                }
            ]
        },
    )

    rss = """
    <rss><channel>
      <item>
        <title>Novartis update on LYS006 in HS</title>
        <link>https://example.com/pr/1</link>
        <pubDate>Mon, 01 Feb 2026 12:00:00 GMT</pubDate>
        <description>Program update</description>
      </item>
    </channel></rss>
    """

    def fetcher(url: str) -> FetchResponse:
        return FetchResponse(text=rss, url=url, status_code=200, headers={})

    stats = scan_sponsor_sources(
        conn,
        config_path=config_path,
        as_of=date(2026, 3, 3),
        fetcher=fetcher,
    )

    assert stats["feeds_scanned"] == 1
    assert stats["events_emitted"] == 1

    row = conn.execute(
        "SELECT event_type, source_type, source_url FROM activity_events"
    ).fetchone()
    assert row is not None
    assert row["event_type"] == "press_release_pipeline_update"
    assert row["source_type"] == "press_release"
    assert row["source_url"] == "https://example.com/pr/1"


def test_scan_sponsor_sources_press_release_page_selectors(tmp_path: Path) -> None:
    conn = _conn()
    upsert_product(
        conn,
        canonical_name="Sonelokimab",
        company="MoonLake",
        modality="Antibody",
        aliases=["M1095"],
    )

    config_path = _write_config(
        tmp_path / "sources.json",
        {
            "sponsors": [
                {
                    "sponsor": "MoonLake",
                    "company": "MoonLake",
                    "press_release_pages": [
                        {
                            "name": "MoonLake News",
                            "url": "https://moon.example/news",
                            "item_selector": "article",
                            "title_selector": "h2",
                            "link_selector": "a",
                            "date_selector": "time",
                            "date_attr": "datetime",
                            "summary_selector": "p",
                        }
                    ],
                }
            ]
        },
    )

    html = """
    <html><body>
      <article>
        <h2>MoonLake reports progress for M1095 in HS</h2>
        <a href="/news/m1095">Open</a>
        <time datetime="2026-01-20"></time>
        <p>Clinical update.</p>
      </article>
    </body></html>
    """

    def fetcher(url: str) -> FetchResponse:
        return FetchResponse(text=html, url=url, status_code=200, headers={})

    stats = scan_sponsor_sources(
        conn,
        config_path=config_path,
        as_of=date(2026, 3, 3),
        fetcher=fetcher,
    )

    assert stats["press_pages_scanned"] == 1
    assert stats["events_emitted"] == 1

    row = conn.execute(
        "SELECT source_url, event_date FROM activity_events"
    ).fetchone()
    assert row is not None
    assert row["source_url"] == "https://moon.example/news/m1095"
    assert row["event_date"] == "2026-01-20"


def test_scan_sponsor_sources_pipeline_page_transition_events(tmp_path: Path) -> None:
    conn = _conn()
    upsert_product(
        conn,
        canonical_name="Povorcitinib",
        company="Incyte",
        modality="Small molecule",
        aliases=["INCB054707"],
    )

    config_path = _write_config(
        tmp_path / "sources.json",
        {
            "sponsors": [
                {
                    "sponsor": "Incyte",
                    "company": "Incyte",
                    "pipeline_pages": [
                        {
                            "name": "Incyte Pipeline",
                            "url": "https://incyte.example/pipeline",
                            "include_selectors": ["main"],
                        }
                    ],
                }
            ]
        },
    )

    html_states = [
        "<html><main>Pipeline includes INCB054707 for HS.</main></html>",
        "<html><main>Pipeline includes INCB054707 for HS.</main></html>",
        "<html><main>Pipeline includes other assets only.</main></html>",
    ]
    idx = {"value": 0}

    def fetcher(url: str) -> FetchResponse:
        current = html_states[idx["value"]]
        return FetchResponse(text=current, url=url, status_code=200, headers={})

    stats1 = scan_sponsor_sources(
        conn,
        config_path=config_path,
        as_of=date(2026, 3, 3),
        fetcher=fetcher,
    )
    idx["value"] = 1
    stats2 = scan_sponsor_sources(
        conn,
        config_path=config_path,
        as_of=date(2026, 3, 3),
        fetcher=fetcher,
    )
    idx["value"] = 2
    stats3 = scan_sponsor_sources(
        conn,
        config_path=config_path,
        as_of=date(2026, 3, 4),
        fetcher=fetcher,
    )

    assert stats1["events_emitted"] == 2
    assert stats2["events_emitted"] == 0
    assert stats3["events_emitted"] == 1

    event_types = [
        row["event_type"]
        for row in conn.execute(
            "SELECT event_type FROM activity_events ORDER BY created_at"
        ).fetchall()
    ]
    assert event_types == [
        "pipeline_mention_added",
        "press_release_pipeline_update",
        "pipeline_mention_removed",
    ]
