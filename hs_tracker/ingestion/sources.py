"""Source-specific sponsor scraper ingestion (press releases + pipeline pages)."""

from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

from hs_tracker.canonicalize import alias_matches_text
from hs_tracker.db import get_json_setting, set_json_setting
from hs_tracker.service import insert_event


@dataclass(frozen=True)
class FetchResponse:
    text: str
    url: str
    status_code: int
    headers: dict[str, str]


Fetcher = Callable[[str], FetchResponse]
SIMPLE_SELECTOR_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


def _default_fetcher(url: str) -> FetchResponse:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError(
            "requests is required for source scanning. Install from requirements.txt"
        ) from exc

    response = requests.get(  # noqa: S113
        url,
        timeout=30,
        headers={
            "User-Agent": "hs-tracker-bot/1.0 (+https://example.local/hs-tracker)",
        },
    )
    return FetchResponse(
        text=response.text,
        url=response.url,
        status_code=response.status_code,
        headers={k.lower(): v for k, v in response.headers.items()},
    )


def _strip_tags(raw_html: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", raw_html)
    return " ".join(html.unescape(no_tags).split())


def _first_simple_selector(selector: str) -> str | None:
    if not selector:
        return None
    for part in selector.split(","):
        candidate = part.strip()
        if SIMPLE_SELECTOR_RE.fullmatch(candidate):
            return candidate.lower()
    return None


def _select_simple_blocks(raw_html: str, selector: str) -> list[str]:
    tag = _first_simple_selector(selector)
    if not tag:
        return []
    pattern = re.compile(fr"<{tag}\b[^>]*>(.*?)</{tag}>", flags=re.IGNORECASE | re.DOTALL)
    return [match.group(0) for match in pattern.finditer(raw_html)]


def _extract_simple_tag_text(raw_html: str, selector: str) -> str:
    block = _select_simple_blocks(raw_html, selector)
    if not block:
        return ""
    return _strip_tags(block[0])


def _extract_simple_link(raw_html: str, selector: str, link_attr: str) -> str:
    tag = _first_simple_selector(selector) or "a"
    pattern = re.compile(
        fr"<{tag}\b[^>]*{re.escape(link_attr)}=['\"]([^'\"]+)['\"][^>]*>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(raw_html)
    return match.group(1).strip() if match else ""


def _extract_simple_attr_or_text(raw_html: str, selector: str, attr: str | None) -> str:
    tag = _first_simple_selector(selector)
    if not tag:
        return ""
    pattern = re.compile(fr"<{tag}\b([^>]*)>(.*?)</{tag}>", flags=re.IGNORECASE | re.DOTALL)
    match = pattern.search(raw_html)
    if not match:
        return ""
    attrs, body = match.groups()
    if attr:
        attr_match = re.search(
            fr"{re.escape(attr)}=['\"]([^'\"]+)['\"]",
            attrs,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return attr_match.group(1).strip() if attr_match else ""
    return _strip_tags(body)


def _remove_simple_tag_blocks(raw_html: str, selector: str) -> str:
    tag = _first_simple_selector(selector)
    if not tag:
        return raw_html
    pattern = re.compile(fr"<{tag}\b[^>]*>.*?</{tag}>", flags=re.IGNORECASE | re.DOTALL)
    return pattern.sub(" ", raw_html)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None

    raw = value.strip()
    if not raw:
        return None

    try:
        parsed = parsedate_to_datetime(raw)
        return parsed.date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass

    normalized = raw.replace("Z", "+00:00")
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m",
        "%Y",
        "%Y/%m/%d",
        "%d-%b-%Y",
        "%b %d, %Y",
    ):
        try:
            parsed = datetime.strptime(raw[: len(fmt)], fmt)
            if fmt == "%Y":
                return date(parsed.year, 1, 1).isoformat()
            if fmt == "%Y-%m":
                return date(parsed.year, parsed.month, 1).isoformat()
            return parsed.date().isoformat()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(normalized).date().isoformat()
    except ValueError:
        return None


def _load_sponsor_products(conn: sqlite3.Connection, company: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT p.product_id, p.canonical_name,
               COALESCE(json_group_array(a.alias), json('[]')) AS aliases_json
        FROM products p
        LEFT JOIN product_aliases a ON p.product_id = a.product_id
        WHERE lower(p.company) = lower(?)
        GROUP BY p.product_id
        """,
        (company,),
    ).fetchall()

    products: list[dict[str, Any]] = []
    for row in rows:
        aliases = json.loads(row["aliases_json"] or "[]")
        aliases = sorted({item for item in aliases if item})
        products.append(
            {
                "product_id": row["product_id"],
                "canonical_name": row["canonical_name"],
                "aliases": aliases,
            }
        )
    return products


def _load_source_config(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "sponsors" in payload:
        sponsors = payload.get("sponsors", [])
        if not isinstance(sponsors, list):
            raise ValueError("'sponsors' must be a list")
        return sponsors

    if isinstance(payload, dict):
        sponsors = []
        for sponsor_name, cfg in payload.items():
            if not isinstance(cfg, dict):
                continue
            sponsors.append({"sponsor": sponsor_name, **cfg})
        return sponsors

    if isinstance(payload, list):
        return payload

    raise ValueError("Source config must be a dict or list")


def _normalize_entry_date(value: str | None, fallback_date: date) -> str:
    parsed = _parse_date(value)
    return parsed or fallback_date.isoformat()


def _rss_entries(feed_text: str, fallback_source_name: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    try:
        root = ET.fromstring(feed_text)
    except ET.ParseError:
        return entries

    def _item_text(elem: ET.Element, tag_names: list[str]) -> str:
        for tag_name in tag_names:
            found = elem.find(tag_name)
            if found is not None and found.text:
                return found.text.strip()
        return ""

    # RSS 2.0
    for item in root.findall("./channel/item"):
        title = _item_text(item, ["title"])
        link = _item_text(item, ["link"])
        pub_date = _item_text(item, ["pubDate", "date"])
        summary = _item_text(item, ["description", "summary"])
        entries.append(
            {
                "title": title,
                "url": link,
                "date": pub_date,
                "summary": summary,
                "source_name": fallback_source_name,
            }
        )

    # Atom
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("./atom:entry", ns):
        title = _item_text(entry, ["atom:title"])
        updated = _item_text(entry, ["atom:updated", "atom:published"])
        summary = _item_text(entry, ["atom:summary", "atom:content"])
        link = ""
        link_node = entry.find("atom:link", ns)
        if link_node is not None:
            link = _safe_text(link_node.attrib.get("href"))

        entries.append(
            {
                "title": title,
                "url": link,
                "date": updated,
                "summary": summary,
                "source_name": fallback_source_name,
            }
        )

    return [entry for entry in entries if entry["url"] or entry["title"]]


def _press_page_entries(page_html: str, rule: dict[str, Any], page_url: str) -> list[dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        BeautifulSoup = None  # type: ignore[assignment]

    item_selector = _safe_text(rule.get("item_selector"))
    if not item_selector:
        return []

    title_selector = _safe_text(rule.get("title_selector"))
    summary_selector = _safe_text(rule.get("summary_selector"))
    link_selector = _safe_text(rule.get("link_selector"))
    link_attr = _safe_text(rule.get("link_attr")) or "href"
    date_selector = _safe_text(rule.get("date_selector"))
    date_attr = _safe_text(rule.get("date_attr"))
    source_name = _safe_text(rule.get("name")) or _safe_text(rule.get("source_name"))
    if not source_name:
        source_name = page_url

    max_items = int(rule.get("max_items", 30))

    if BeautifulSoup is None:
        items = _select_simple_blocks(page_html, item_selector)[:max_items]
        entries: list[dict[str, str]] = []
        for item_html in items:
            title = (
                _extract_simple_tag_text(item_html, title_selector)
                if title_selector
                else _strip_tags(item_html)
            )
            summary = (
                _extract_simple_tag_text(item_html, summary_selector) if summary_selector else ""
            )
            url = _extract_simple_link(item_html, link_selector or "a", link_attr)
            if url:
                url = urljoin(page_url, url)
            date_value = (
                _extract_simple_attr_or_text(item_html, date_selector, date_attr)
                if date_selector
                else ""
            )
            if title or summary or url:
                entries.append(
                    {
                        "title": title,
                        "summary": summary,
                        "url": url,
                        "date": date_value,
                        "source_name": source_name,
                    }
                )
        return entries

    soup = BeautifulSoup(page_html, "html.parser")

    entries: list[dict[str, str]] = []
    for item in soup.select(item_selector)[:max_items]:
        title = item.get_text(" ", strip=True)
        if title_selector:
            title_node = item.select_one(title_selector)
            if title_node:
                title = title_node.get_text(" ", strip=True)

        summary = ""
        if summary_selector:
            summary_node = item.select_one(summary_selector)
            if summary_node:
                summary = summary_node.get_text(" ", strip=True)

        url = ""
        if link_selector:
            link_node = item.select_one(link_selector)
        else:
            link_node = item.find("a")
        if link_node is not None:
            raw_href = _safe_text(link_node.get(link_attr))
            if raw_href:
                url = urljoin(page_url, raw_href)

        date_value = ""
        if date_selector:
            date_node = item.select_one(date_selector)
            if date_node is not None:
                if date_attr:
                    date_value = _safe_text(date_node.get(date_attr))
                else:
                    date_value = date_node.get_text(" ", strip=True)

        if title or summary or url:
            entries.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": url,
                    "date": date_value,
                    "source_name": source_name,
                }
            )

    return entries


def _pipeline_page_text(page_html: str, rule: dict[str, Any]) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        BeautifulSoup = None  # type: ignore[assignment]

    if BeautifulSoup is None:
        trimmed = page_html
        for selector in rule.get(
            "exclude_selectors",
            ["script", "style", "noscript", "nav", "footer"],
        ):
            trimmed = _remove_simple_tag_blocks(trimmed, selector)
        include_selectors = rule.get("include_selectors", [])
        if include_selectors:
            fragments = []
            for selector in include_selectors:
                fragments.extend(_select_simple_blocks(trimmed, selector))
            return _strip_tags(" ".join(fragments))
        return _strip_tags(trimmed)

    soup = BeautifulSoup(page_html, "html.parser")
    for selector in rule.get(
        "exclude_selectors",
        ["script", "style", "noscript", "nav", "footer"],
    ):
        for node in soup.select(selector):
            node.decompose()

    include_selectors = rule.get("include_selectors", [])
    if include_selectors:
        selected_text = []
        for selector in include_selectors:
            for node in soup.select(selector):
                selected_text.append(node.get_text(" ", strip=True))
        return " ".join(selected_text)

    body = soup.find("body")
    if body:
        return body.get_text(" ", strip=True)
    return soup.get_text(" ", strip=True)


def _mentions_product(text: str, aliases: list[str]) -> tuple[bool, list[str]]:
    matched_aliases = [alias for alias in aliases if alias_matches_text(alias, text)]
    return bool(matched_aliases), matched_aliases


def _state_key(prefix: str, *parts: str) -> str:
    hashed_parts = [hashlib.sha1(part.encode("utf-8")).hexdigest() for part in parts]
    return "::".join([prefix, *hashed_parts])


def _emit_press_release_events(
    conn: sqlite3.Connection,
    products: list[dict[str, Any]],
    entries: list[dict[str, str]],
    fallback_source_name: str,
    fallback_date: date,
) -> int:
    emitted = 0
    for entry in entries:
        entry_date = _normalize_entry_date(entry.get("date"), fallback_date)
        text_blob = " ".join([entry.get("title", ""), entry.get("summary", "")])
        source_name = _safe_text(entry.get("source_name")) or fallback_source_name
        source_url = _safe_text(entry.get("url")) or None

        for product in products:
            mentioned, matched_aliases = _mentions_product(text_blob, product["aliases"])
            if not mentioned:
                continue
            eid = insert_event(
                conn,
                {
                    "product_id": product["product_id"],
                    "event_date": entry_date,
                    "event_type": "press_release_pipeline_update",
                    "event_summary": (
                        f"{product['canonical_name']} mentioned in PR/source item: "
                        f"{entry.get('title', '').strip()[:180]}"
                    ),
                    "source_type": "press_release",
                    "source_name": source_name,
                    "source_url": source_url,
                    "confidence": "Medium",
                    "impact": "Medium",
                    "source_snapshot_meta": {
                        "title": entry.get("title", ""),
                        "matched_aliases": matched_aliases,
                    },
                },
            )
            if eid:
                emitted += 1
    return emitted


def _emit_pipeline_page_events(
    conn: sqlite3.Connection,
    products: list[dict[str, Any]],
    page_rule: dict[str, Any],
    page_text: str,
    page_url: str,
    as_of: date,
) -> int:
    emitted = 0
    source_name = _safe_text(page_rule.get("name")) or page_url
    content_hash = hashlib.sha1(page_text.encode("utf-8")).hexdigest()
    hash_key = _state_key("pipeline_page_hash", page_url)
    prev_hash = get_json_setting(conn, hash_key, None)
    changed = prev_hash != content_hash

    for product in products:
        mentioned, matched_aliases = _mentions_product(page_text, product["aliases"])
        mention_key = _state_key("pipeline_page_mention", product["product_id"], page_url)
        prev_mentioned = get_json_setting(conn, mention_key, None)

        transition_event: str | None = None
        if prev_mentioned is None:
            transition_event = "pipeline_mention_added" if mentioned else "pipeline_mention_absent"
        elif bool(prev_mentioned) and not mentioned:
            transition_event = "pipeline_mention_removed"
        elif not bool(prev_mentioned) and mentioned:
            transition_event = "pipeline_mention_added"
        elif not mentioned and changed:
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
                    "event_date": as_of.isoformat(),
                    "event_type": transition_event,
                    "event_summary": (
                        f"Pipeline page check ({source_name}): {product['canonical_name']} "
                        f"{transition_event.replace('_', ' ')}."
                    ),
                    "source_type": "pipeline_page",
                    "source_name": source_name,
                    "source_url": page_url,
                    "confidence": "Medium",
                    "impact": impact,
                    "source_snapshot_meta": {
                        "matched_aliases": matched_aliases,
                        "content_hash": content_hash,
                        "changed": changed,
                    },
                },
            )
            if eid:
                emitted += 1

        if mentioned and changed:
            eid = insert_event(
                conn,
                {
                    "product_id": product["product_id"],
                    "event_date": as_of.isoformat(),
                    "event_type": "press_release_pipeline_update",
                    "event_summary": (
                        f"Pipeline page updated and includes {product['canonical_name']} ({source_name})."
                    ),
                    "source_type": "pipeline_page",
                    "source_name": source_name,
                    "source_url": page_url,
                    "confidence": "Medium",
                    "impact": "Medium",
                    "source_snapshot_meta": {
                        "matched_aliases": matched_aliases,
                        "content_hash": content_hash,
                        "changed": changed,
                    },
                },
            )
            if eid:
                emitted += 1

        set_json_setting(conn, mention_key, bool(mentioned))

    set_json_setting(conn, hash_key, content_hash)
    return emitted


def scan_sponsor_sources(
    conn: sqlite3.Connection,
    config_path: Path,
    as_of: date | None = None,
    fetcher: Fetcher | None = None,
) -> dict[str, int]:
    if not config_path.exists():
        raise FileNotFoundError(f"Source config file not found: {config_path}")

    run_date = as_of or date.today()
    fetch = fetcher or _default_fetcher

    stats = {
        "sponsors_scanned": 0,
        "feeds_scanned": 0,
        "press_pages_scanned": 0,
        "pipeline_pages_scanned": 0,
        "events_emitted": 0,
    }

    sponsors = _load_source_config(config_path)
    for sponsor_cfg in sponsors:
        sponsor_name = _safe_text(sponsor_cfg.get("sponsor")) or _safe_text(
            sponsor_cfg.get("company")
        )
        if not sponsor_name:
            continue

        company = _safe_text(sponsor_cfg.get("company")) or sponsor_name
        products = _load_sponsor_products(conn, company=company)
        if not products:
            continue

        stats["sponsors_scanned"] += 1

        for feed_cfg in sponsor_cfg.get("press_release_feeds", []):
            if isinstance(feed_cfg, str):
                feed_cfg = {"url": feed_cfg, "name": sponsor_name}
            feed_url = _safe_text(feed_cfg.get("url"))
            if not feed_url:
                continue

            response = fetch(feed_url)
            if response.status_code >= 400:
                continue

            source_name = _safe_text(feed_cfg.get("name")) or sponsor_name
            entries = _rss_entries(response.text, fallback_source_name=source_name)
            stats["feeds_scanned"] += 1
            stats["events_emitted"] += _emit_press_release_events(
                conn,
                products=products,
                entries=entries,
                fallback_source_name=source_name,
                fallback_date=run_date,
            )

        for page_cfg in sponsor_cfg.get("press_release_pages", []):
            page_url = _safe_text(page_cfg.get("url"))
            if not page_url:
                continue
            response = fetch(page_url)
            if response.status_code >= 400:
                continue

            entries = _press_page_entries(response.text, page_cfg, response.url)
            stats["press_pages_scanned"] += 1
            stats["events_emitted"] += _emit_press_release_events(
                conn,
                products=products,
                entries=entries,
                fallback_source_name=_safe_text(page_cfg.get("name")) or sponsor_name,
                fallback_date=run_date,
            )

        for pipeline_cfg in sponsor_cfg.get("pipeline_pages", []):
            page_url = _safe_text(pipeline_cfg.get("url"))
            if not page_url:
                continue
            response = fetch(page_url)
            if response.status_code >= 400:
                continue

            page_text = _pipeline_page_text(response.text, pipeline_cfg)
            stats["pipeline_pages_scanned"] += 1
            stats["events_emitted"] += _emit_pipeline_page_events(
                conn,
                products=products,
                page_rule=pipeline_cfg,
                page_text=page_text,
                page_url=response.url,
                as_of=run_date,
            )

    return stats
