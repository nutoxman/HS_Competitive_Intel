"""Pipeline deck scanning ingestion workflow."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from hs_tracker.canonicalize import alias_matches_text
from hs_tracker.service import insert_event


DATE_PATTERNS = [
    re.compile(r"(20\d{2})[-_](0[1-9]|1[0-2])[-_](0[1-9]|[12]\d|3[01])"),
    re.compile(r"(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])"),
]


@dataclass
class DeckParseResult:
    text: str
    page_hits: list[int]


def _extract_pdf_text(path: Path) -> DeckParseResult:
    try:
        import pdfplumber  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "pdfplumber is required for deck scan. Install dependencies from requirements.txt"
        ) from exc

    full_text_parts: list[str] = []
    page_hits: list[int] = []
    with pdfplumber.open(path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                full_text_parts.append(text)
                if "pipeline" in text.lower() or "hidradenitis" in text.lower():
                    page_hits.append(idx)
    return DeckParseResult(text="\n".join(full_text_parts), page_hits=page_hits)


def _parse_deck_date(path: Path) -> date:
    name = path.stem
    for pattern in DATE_PATTERNS:
        match = pattern.search(name)
        if not match:
            continue
        year, month, day = match.groups()
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            continue
    return datetime.fromtimestamp(path.stat().st_mtime).date()


def _latest_four_pdfs(deck_dir: Path) -> list[Path]:
    pdfs = [path for path in deck_dir.glob("*.pdf") if path.is_file()]
    return sorted(pdfs, key=lambda p: p.stat().st_mtime, reverse=True)[:4]


def _load_sponsor_products(conn: sqlite3.Connection, sponsor: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT p.product_id, p.canonical_name,
               COALESCE(json_group_array(a.alias), json('[]')) AS aliases_json
        FROM products p
        LEFT JOIN product_aliases a ON p.product_id = a.product_id
        WHERE lower(p.company) = lower(?)
        GROUP BY p.product_id
        """,
        (sponsor,),
    ).fetchall()

    products: list[dict[str, Any]] = []
    for row in rows:
        aliases_json = row["aliases_json"]
        aliases = []
        if aliases_json:
            import json

            aliases = json.loads(aliases_json)
        aliases = sorted({alias for alias in aliases if alias})
        products.append(
            {
                "product_id": row["product_id"],
                "canonical_name": row["canonical_name"],
                "aliases": aliases,
            }
        )
    return products


def _last_pipeline_state(conn: sqlite3.Connection, product_id: str) -> str | None:
    row = conn.execute(
        """
        SELECT event_type
        FROM activity_events
        WHERE product_id = ?
          AND source_type = 'pipeline_deck'
          AND event_type IN ('pipeline_mention_added', 'pipeline_mention_removed', 'pipeline_mention_absent')
        ORDER BY COALESCE(event_date, '0000-00-00') DESC, created_at DESC
        LIMIT 1
        """,
        (product_id,),
    ).fetchone()
    return row["event_type"] if row else None


def scan_sponsor_decks(conn: sqlite3.Connection, sponsor: str, deck_dir: Path) -> dict[str, int]:
    stats = {"decks_scanned": 0, "events_emitted": 0}
    if not deck_dir.exists():
        return stats

    products = _load_sponsor_products(conn, sponsor)
    if not products:
        return stats

    for deck in _latest_four_pdfs(deck_dir):
        parse_result = _extract_pdf_text(deck)
        text = parse_result.text
        is_pipeline_bearing = "pipeline" in text.lower()
        deck_date = _parse_deck_date(deck).isoformat()

        stats["decks_scanned"] += 1
        if not text.strip():
            continue

        for product in products:
            matched_aliases = [
                alias for alias in product["aliases"] if alias_matches_text(alias, text)
            ]
            mentioned = bool(matched_aliases)

            if mentioned:
                eid = insert_event(
                    conn,
                    {
                        "product_id": product["product_id"],
                        "event_date": deck_date,
                        "event_type": "investor_deck_pipeline_slide",
                        "event_summary": (
                            f"{product['canonical_name']} was mentioned in sponsor deck {deck.name}."
                        ),
                        "source_type": "pipeline_deck",
                        "source_name": sponsor,
                        "source_url": deck.resolve().as_posix(),
                        "confidence": "Medium",
                        "impact": "Medium",
                        "source_snapshot_meta": {
                            "page_hits": parse_result.page_hits,
                            "matched_aliases": matched_aliases,
                            "pipeline_bearing": is_pipeline_bearing,
                        },
                    },
                )
                if eid:
                    stats["events_emitted"] += 1

            previous_state = _last_pipeline_state(conn, product["product_id"])
            transition_event: str | None = None
            if mentioned and previous_state in {"pipeline_mention_absent", "pipeline_mention_removed", None}:
                transition_event = "pipeline_mention_added"
            elif not mentioned and previous_state in {"pipeline_mention_added"}:
                transition_event = "pipeline_mention_removed"
            elif not mentioned:
                transition_event = "pipeline_mention_absent"

            if transition_event:
                impact = "High" if transition_event in {
                    "pipeline_mention_added",
                    "pipeline_mention_removed",
                } else "Low"
                eid = insert_event(
                    conn,
                    {
                        "product_id": product["product_id"],
                        "event_date": deck_date,
                        "event_type": transition_event,
                        "event_summary": (
                            f"Deck {deck.name}: {product['canonical_name']} {transition_event.replace('_', ' ')}."
                        ),
                        "source_type": "pipeline_deck",
                        "source_name": sponsor,
                        "source_url": deck.resolve().as_posix(),
                        "confidence": "Medium",
                        "impact": impact,
                        "source_snapshot_meta": {
                            "page_hits": parse_result.page_hits,
                            "matched_aliases": matched_aliases,
                            "pipeline_bearing": is_pipeline_bearing,
                        },
                    },
                )
                if eid:
                    stats["events_emitted"] += 1

    return stats


def scan_all_sponsors(conn: sqlite3.Connection, base_dir: Path) -> dict[str, int]:
    stats = {"sponsors_scanned": 0, "decks_scanned": 0, "events_emitted": 0}
    if not base_dir.exists():
        return stats

    for sponsor_dir in sorted(path for path in base_dir.iterdir() if path.is_dir()):
        sponsor_stats = scan_sponsor_decks(conn, sponsor=sponsor_dir.name, deck_dir=sponsor_dir)
        stats["sponsors_scanned"] += 1
        stats["decks_scanned"] += sponsor_stats["decks_scanned"]
        stats["events_emitted"] += sponsor_stats["events_emitted"]

    return stats
