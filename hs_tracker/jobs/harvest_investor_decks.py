"""Harvest latest investor/pipeline decks from sponsor-specific public sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse
import xml.etree.ElementTree as ET

import pdfplumber
import requests
from bs4 import BeautifulSoup

from hs_tracker.config import load_config
from hs_tracker.db import connect, init_db


SEARCH_URL = "https://duckduckgo.com/html/"
REQUEST_TIMEOUT = (6, 10)
PDF_TIMEOUT = (6, 14)
ACTIVE_PLANNED_STATUSES = (
    "RECRUITING",
    "ACTIVE_NOT_RECRUITING",
    "NOT_YET_RECRUITING",
    "ENROLLING_BY_INVITATION",
)

DATE_PATTERNS = [
    re.compile(r"(20\d{2})[\-_/.](0[1-9]|1[0-2])[\-_/.](0[1-9]|[12]\d|3[01])"),
    re.compile(r"(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])"),
    re.compile(r"(20\d{2})[\-_/.](0[1-9]|1[0-2])"),
    re.compile(r"(20\d{2})"),
]

PIPELINE_HINTS = {
    "pipeline",
    "portfolio",
    "late-stage",
    "clinical development",
    "clinical pipeline",
    "r&d",
    "investor presentation",
    "corporate presentation",
}

DECK_LINK_HINTS = {
    "presentation",
    "deck",
    "pipeline",
    "earnings",
    "investor",
    "slides",
    "r&d",
    "capital markets",
    "conference",
    "quarterly results",
    "financial results",
}

DECK_REJECT_HINTS = {
    "annual report",
    "form 10",
    "10-k",
    "10q",
    "20-f",
    "proxy",
    "prepared remarks",
    "transcript",
    "announcement",
}

COMMON_SPONSOR_TOKENS = {
    "and",
    "biopharmaceutical",
    "biopharma",
    "biopharmaceuticals",
    "co",
    "company",
    "corporation",
    "inc",
    "incorporated",
    "limited",
    "ltd",
    "llc",
    "pharmaceutical",
    "pharmaceuticals",
    "research",
    "sa",
    "srl",
    "therapeutics",
}

REJECT_HOST_TOKENS = {
    "sec.gov",
    "scribd.com",
    "seekingalpha.com",
    "pharmacompass.com",
    "monexa.ai",
    "worldcupnut.com",
    "stocklight.com",
    "cmich.edu",
    "marketwatch.com",
    "fool.com",
    "simplywall.st",
}

KNOWN_PAGE_SEEDS = {
    "abbvie": [
        "https://investors.abbvie.com/events-and-presentations/default.aspx",
        "https://investors.abbvie.com/financial-results-and-filings/default.aspx",
    ],
    "almirall": [
        "https://www.almirall.com/investors",
        "https://www.almirall.com/investors/financial-results",
    ],
    "avalo": [
        "https://ir.avalotx.com/news-events/presentations",
    ],
    "citryll": [
        "https://www.citryll.com/news",
    ],
    "incyte": [
        "https://investor.incyte.com/events-and-presentations/default.aspx",
        "https://investor.incyte.com/news-releases/",
    ],
    "insmed": [
        "https://investor.insmed.com/events-and-presentations",
        "https://investor.insmed.com/financial-information/quarterly-results",
    ],
    "lilly": [
        "https://investor.lilly.com/events-and-presentations/default.aspx",
    ],
    "merck": [
        "https://investors.merck.com/events-and-presentations/default.aspx",
        "https://www.merck.com/investor-relations/",
    ],
    "moonlake": [
        "https://ir.moonlaketx.com/events-and-presentations",
        "https://ir.moonlaketx.com/news-releases",
    ],
    "novartis": [
        "https://www.novartis.com/investors/events-calendar",
        "https://www.novartis.com/investors/financial-data/quarterly-results",
    ],
    "sanofi": [
        "https://www.sanofi.com/en/investors",
        "https://www.sanofi.com/en/investors/events-presentations",
    ],
    "takeda": [
        "https://www.takeda.com/investors/reports/",
        "https://www.takeda.com/investors/events/",
    ],
    "ucb": [
        "https://www.ucb.com/investors/financial-reports",
        "https://www.ucb.com/investors/calendar-and-presentations",
    ],
    "zura": [
        "https://investors.zurabio.com/news-events/events-presentations",
    ],
}


@dataclass(frozen=True)
class CandidatePdf:
    url: str
    referrer: str
    source_label: str
    score: int


@dataclass
class EvaluatedPdf:
    url: str
    local_path: Path
    detected_date: date
    pipeline_bearing: bool
    hs_mentioned: bool
    title_hint: str
    source_label: str


def _ssl_verify_setting() -> bool | str:
    ca_bundle = os.getenv("HS_TRACKER_CA_BUNDLE", "").strip()
    skip_verify = os.getenv("HS_TRACKER_SKIP_SSL_VERIFY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if skip_verify:
        return False
    if ca_bundle:
        return ca_bundle
    return True


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0 Safari/537.36"
            )
        }
    )
    return s


def _disable_insecure_request_warning(verify: bool | str) -> None:
    if verify is not False:
        return
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        return


def _sponsor_slug(sponsor: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", sponsor.lower()).strip("-")


def _sponsor_key(sponsor: str) -> str:
    return sponsor.strip().lower()


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return cleaned[:180] or "deck.pdf"


def _dedupe_key(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path}"


def _decode_ddg_link(href: str) -> str | None:
    if not href:
        return None
    if href.startswith("//"):
        href = "https:" + href
    if href.startswith("/"):
        href = "https://duckduckgo.com" + href

    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        return unquote(target) if target else None

    if parsed.scheme in {"http", "https"}:
        return href
    return None


def _get_url(
    session: requests.Session,
    url: str,
    verify: bool | str,
    *,
    params: dict[str, str] | None = None,
    timeout: tuple[int, int] = REQUEST_TIMEOUT,
) -> requests.Response | None:
    try:
        response = session.get(url, params=params, timeout=timeout, verify=verify)
        response.raise_for_status()
        return response
    except Exception:
        return None


def _search_urls(
    session: requests.Session,
    verify: bool | str,
    query: str,
    limit: int,
) -> list[str]:
    resp = _get_url(session, SEARCH_URL, verify, params={"q": query})
    if resp is None:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    urls: list[str] = []
    for a in soup.select("a.result__a, a[data-testid='result-title-a']"):
        decoded = _decode_ddg_link(str(a.get("href") or ""))
        if decoded:
            urls.append(decoded)
        if len(urls) >= limit:
            break
    return urls


def _pdf_candidate_score(text: str, url: str) -> int:
    hay = f"{text} {url}".lower()
    score = 0
    if ".pdf" in url.lower():
        score += 3
    for token in DECK_LINK_HINTS:
        if token in hay:
            score += 1
    for token in DECK_REJECT_HINTS:
        if token in hay:
            score -= 2
    return score


def _page_score(url: str) -> int:
    hay = url.lower()
    score = 0
    for token in ("investor", "events", "presentation", "results", "pipeline", "financial"):
        if token in hay:
            score += 1
    return score


def _extract_pdf_links_from_html(html: str, page_url: str) -> list[tuple[str, str, int]]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str, int]] = []
    for a in soup.select("a[href]"):
        href = str(a.get("href") or "").strip()
        if not href:
            continue
        abs_url = urljoin(page_url, href)
        text = a.get_text(" ", strip=True)
        score = _pdf_candidate_score(text, abs_url)
        lower = abs_url.lower()
        if ".pdf" in lower or score >= 5:
            out.append((abs_url, text, score))
    out.sort(key=lambda x: x[2], reverse=True)
    return out


def _extract_sitemap_locs(xml_text: str) -> list[str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    urls: list[str] = []
    for elem in root.iter():
        if elem.tag.lower().endswith("loc") and elem.text:
            urls.append(elem.text.strip())
    return urls


def _sitemap_roots(page_urls: list[str]) -> list[str]:
    roots: dict[str, None] = {}
    for raw in page_urls:
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        root = f"{parsed.scheme}://{parsed.netloc}"
        roots[root] = None
    return list(roots.keys())


def _collect_sitemap_pdf_candidates(
    session: requests.Session,
    verify: bool | str,
    root_url: str,
    sponsor: str,
    max_candidates: int = 120,
) -> list[CandidatePdf]:
    candidates: dict[str, CandidatePdf] = {}
    queue = [urljoin(root_url, "/sitemap.xml"), urljoin(root_url, "/sitemap_index.xml")]
    visited: set[str] = set()

    while queue and len(visited) <= 6:
        sitemap_url = queue.pop(0)
        if sitemap_url in visited:
            continue
        visited.add(sitemap_url)

        resp = _get_url(session, sitemap_url, verify)
        if resp is None:
            continue

        for loc in _extract_sitemap_locs(resp.text)[:1500]:
            lower = loc.lower()
            if lower.endswith(".xml"):
                if len(visited) + len(queue) < 8 and urlparse(loc).netloc == urlparse(root_url).netloc:
                    queue.append(loc)
                continue

            if ".pdf" not in lower:
                continue
            if not _url_relevant_for_sponsor(loc, sponsor):
                continue

            score = _pdf_candidate_score("", loc) + 1
            if score < 2:
                continue
            key = _dedupe_key(loc)
            current = candidates.get(key)
            if current is None or score > current.score:
                candidates[key] = CandidatePdf(
                    url=loc,
                    referrer=sitemap_url,
                    source_label="sitemap",
                    score=score,
                )
            if len(candidates) >= max_candidates:
                break

    return sorted(candidates.values(), key=lambda item: item.score, reverse=True)


def _last_modified_date(headers: requests.structures.CaseInsensitiveDict) -> date | None:
    raw = headers.get("Last-Modified")
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).date()
    except Exception:
        return None


def _date_from_text(text: str) -> date | None:
    for idx, pat in enumerate(DATE_PATTERNS):
        match = pat.search(text)
        if not match:
            continue
        parts = match.groups()
        try:
            if idx <= 1:
                y, m, d = parts[:3]
                return date(int(y), int(m), int(d))
            if idx == 2:
                y, m = parts[:2]
                return date(int(y), int(m), 1)
            y = parts[0]
            return date(int(y), 1, 1)
        except Exception:
            continue
    return None


def _detect_pdf_signals(path: Path) -> tuple[bool, bool]:
    text_chunks: list[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages[:25]:
                text = (page.extract_text() or "").strip()
                if text:
                    text_chunks.append(text)
    except Exception:
        return False, False

    corpus = "\n".join(text_chunks).lower()
    pipeline_bearing = any(token in corpus for token in PIPELINE_HINTS)
    hs_mentioned = (
        "hidradenitis" in corpus
        or "hidradenitis suppurativa" in corpus
        or re.search(r"\bhs\b", corpus) is not None
    )
    return pipeline_bearing, hs_mentioned


def _download_pdf(
    session: requests.Session,
    verify: bool | str,
    candidate: CandidatePdf,
    dest_dir: Path,
) -> EvaluatedPdf | None:
    resp = _get_url(session, candidate.url, verify, timeout=PDF_TIMEOUT)
    if resp is None:
        return None

    content_type = str(resp.headers.get("Content-Type", "")).lower()
    body = resp.content
    is_pdf_like = (
        "pdf" in content_type
        or ".pdf" in candidate.url.lower()
        or body[:5] == b"%PDF-"
    )
    if not is_pdf_like:
        return None

    if not body or len(body) < 1024:
        return None
    if len(body) > 25 * 1024 * 1024:
        return None

    url_path = urlparse(resp.url).path
    basename = Path(url_path).name or "deck.pdf"
    if not basename.lower().endswith(".pdf"):
        basename = f"{basename}.pdf"

    text_date = _date_from_text(resp.url) or _date_from_text(basename)
    mod_date = _last_modified_date(resp.headers)
    detected_date = text_date or mod_date or datetime.now(tz=UTC).date()

    hash_prefix = hashlib.sha1(resp.url.encode("utf-8")).hexdigest()[:8]
    filename = _safe_filename(f"{detected_date.isoformat()}_{hash_prefix}_{basename}")
    out_path = dest_dir / filename
    out_path.write_bytes(body)

    pipeline_bearing, hs_mentioned = _detect_pdf_signals(out_path)
    if not pipeline_bearing:
        out_path.unlink(missing_ok=True)
        return None

    return EvaluatedPdf(
        url=resp.url,
        local_path=out_path,
        detected_date=detected_date,
        pipeline_bearing=pipeline_bearing,
        hs_mentioned=hs_mentioned,
        title_hint=basename,
        source_label=candidate.source_label,
    )


def _seed_pages_for_sponsor(sponsor: str) -> list[str]:
    slug = _sponsor_slug(sponsor)
    seeds: list[str] = []
    for key, urls in KNOWN_PAGE_SEEDS.items():
        if key in slug:
            seeds.extend(urls)
    return seeds


def _sponsor_tokens(sponsor: str) -> set[str]:
    slug = _sponsor_slug(sponsor)
    tokens = {
        token
        for token in slug.split("-")
        if len(token) >= 4 and token not in COMMON_SPONSOR_TOKENS
    }
    return tokens or {slug}


def _url_relevant_for_sponsor(url: str, sponsor: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False

    host = parsed.netloc.lower()
    path = parsed.path.lower()
    hay = f"{host}{path}"

    if any(token in host for token in REJECT_HOST_TOKENS):
        return False

    tokens = _sponsor_tokens(sponsor)
    return any(token in hay for token in tokens)


def _active_sponsors(conn) -> list[str]:
    rows = conn.execute(
        """
        SELECT sponsor_display
        FROM trials
        WHERE inclusion_flag = 1
          AND status IN (?, ?, ?, ?)
          AND sponsor_display IS NOT NULL
          AND trim(sponsor_display) <> ''
        GROUP BY sponsor_display
        ORDER BY COUNT(*) DESC, sponsor_display
        """,
        ACTIVE_PLANNED_STATUSES,
    ).fetchall()
    return [str(row["sponsor_display"]).strip() for row in rows]


def _load_source_page_seeds(path: Path | None) -> dict[str, list[str]]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        sponsors = payload.get("sponsors", [])
    elif isinstance(payload, list):
        sponsors = payload
    else:
        sponsors = []

    source_seeds: dict[str, list[str]] = {}
    for entry in sponsors:
        if not isinstance(entry, dict):
            continue
        sponsor = str(entry.get("company") or entry.get("sponsor") or "").strip()
        if not sponsor:
            continue
        urls: list[str] = []
        for key in ("pipeline_pages", "press_release_pages"):
            val = entry.get(key, [])
            if isinstance(val, list):
                urls.extend(str(item).strip() for item in val if str(item).strip())
        if urls:
            source_seeds[_sponsor_key(sponsor)] = sorted(set(urls))
    return source_seeds


def _search_queries(sponsor: str) -> list[str]:
    return [
        f'"{sponsor}" investor presentation pdf',
        f'"{sponsor}" earnings presentation pdf',
        f'"{sponsor}" pipeline presentation pdf',
    ]


def _collect_candidates_for_sponsor(
    session: requests.Session,
    verify: bool | str,
    sponsor: str,
    source_page_seeds: list[str],
    use_search_fallback: bool,
    max_pages: int = 12,
    max_candidates: int = 28,
    search_results_per_query: int = 6,
) -> list[CandidatePdf]:
    def _upsert(candidate: CandidatePdf) -> None:
        key = _dedupe_key(candidate.url)
        current = pdf_candidates.get(key)
        if current is None or candidate.score > current.score:
            pdf_candidates[key] = candidate

    page_urls: dict[str, int] = {}
    for seed in _seed_pages_for_sponsor(sponsor):
        if _url_relevant_for_sponsor(seed, sponsor):
            page_urls[seed] = _page_score(seed)
    for seed in source_page_seeds:
        if _url_relevant_for_sponsor(seed, sponsor):
            page_urls[seed] = max(page_urls.get(seed, 0), _page_score(seed) + 1)

    pdf_candidates: dict[str, CandidatePdf] = {}

    for root in _sitemap_roots(list(page_urls.keys())):
        for candidate in _collect_sitemap_pdf_candidates(session, verify, root, sponsor):
            _upsert(candidate)
            if len(pdf_candidates) >= max_candidates:
                break
        if len(pdf_candidates) >= max_candidates:
            break

    if use_search_fallback and len(pdf_candidates) < 8:
        for query in _search_queries(sponsor):
            for url in _search_urls(session, verify, query, limit=search_results_per_query):
                if not _url_relevant_for_sponsor(url, sponsor):
                    continue
                score = _pdf_candidate_score("", url)
                lower = url.lower()
                if lower.endswith(".pdf") or ".pdf?" in lower:
                    if score >= 2:
                        _upsert(
                            CandidatePdf(
                            url=url,
                            referrer=query,
                            source_label="search",
                            score=score,
                            )
                        )
                elif _page_score(url) >= 1:
                    page_urls[url] = max(page_urls.get(url, 0), _page_score(url))

    ranked_pages = sorted(page_urls.items(), key=lambda item: item[1], reverse=True)[:max_pages]
    for page_url, _score in ranked_pages:
        resp = _get_url(session, page_url, verify)
        if resp is None:
            continue

        ctype = str(resp.headers.get("Content-Type", "")).lower()
        if "pdf" in ctype:
            score = _pdf_candidate_score("", resp.url)
            if score >= 2:
                _upsert(
                    CandidatePdf(
                    url=resp.url,
                    referrer=page_url,
                    source_label="direct-page",
                    score=score,
                    )
                )
            continue

        for pdf_url, text, score in _extract_pdf_links_from_html(resp.text, resp.url)[:40]:
            if score < 2:
                continue
            if not _url_relevant_for_sponsor(pdf_url, sponsor):
                continue
            _upsert(
                CandidatePdf(
                    url=pdf_url,
                    referrer=page_url,
                    source_label="page-link",
                    score=score,
                )
            )
            if len(pdf_candidates) >= max_candidates:
                break
        if len(pdf_candidates) >= max_candidates:
            break

    ranked = sorted(pdf_candidates.values(), key=lambda item: item.score, reverse=True)
    return ranked[:max_candidates]


def _prune_to_latest_four(dest_dir: Path, picked: list[EvaluatedPdf]) -> None:
    picked_set = {item.local_path.resolve().as_posix() for item in picked}
    for existing in dest_dir.glob("*.pdf"):
        if existing.resolve().as_posix() not in picked_set:
            existing.unlink(missing_ok=True)


def harvest_investor_decks(
    deck_root: Path,
    max_per_sponsor: int = 4,
    source_config_path: Path | None = None,
    use_search_fallback: bool = False,
) -> dict[str, Any]:
    cfg = load_config()
    verify = _ssl_verify_setting()
    _disable_insecure_request_warning(verify)
    session = _session()
    source_seed_map = _load_source_page_seeds(source_config_path)

    stats = {
        "sponsors_targeted": 0,
        "sponsors_with_decks": 0,
        "candidate_pdfs": 0,
        "pipeline_pdfs_downloaded": 0,
    }
    manifest: dict[str, Any] = {}

    with connect(cfg.db_path) as conn:
        init_db(conn)
        sponsors = _active_sponsors(conn)

    stats["sponsors_targeted"] = len(sponsors)

    for sponsor in sponsors:
        sponsor_dir = deck_root / sponsor
        sponsor_dir.mkdir(parents=True, exist_ok=True)

        candidates = _collect_candidates_for_sponsor(
            session=session,
            verify=verify,
            sponsor=sponsor,
            source_page_seeds=source_seed_map.get(_sponsor_key(sponsor), []),
            use_search_fallback=use_search_fallback,
        )
        stats["candidate_pdfs"] += len(candidates)

        evaluated: list[EvaluatedPdf] = []
        for candidate in candidates:
            item = _download_pdf(session, verify, candidate, sponsor_dir)
            if item:
                evaluated.append(item)

        evaluated.sort(
            key=lambda x: (x.detected_date, 1 if x.hs_mentioned else 0),
            reverse=True,
        )
        picked = evaluated[:max_per_sponsor]
        _prune_to_latest_four(sponsor_dir, picked)

        if picked:
            stats["sponsors_with_decks"] += 1
            stats["pipeline_pdfs_downloaded"] += len(picked)

        print(
            f"[harvest] sponsor={sponsor} candidates={len(candidates)} "
            f"pipeline_pdfs={len(picked)}"
        )

        manifest[sponsor] = {
            "picked_count": len(picked),
            "picked": [
                {
                    "local_path": item.local_path.as_posix(),
                    "url": item.url,
                    "detected_date": item.detected_date.isoformat(),
                    "hs_mentioned": item.hs_mentioned,
                    "source_label": item.source_label,
                }
                for item in picked
            ],
            "candidate_count": len(candidates),
        }

    manifest_path = deck_root / "harvest_manifest.json"
    manifest_payload = {
        "stats": stats,
        "meta": {
            "source_config_path": source_config_path.as_posix() if source_config_path else None,
            "use_search_fallback": use_search_fallback,
            "generated_at": datetime.now(tz=UTC).isoformat(),
        },
        "sponsors": manifest,
    }
    manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
    stats["manifest_path"] = manifest_path.as_posix()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Harvest investor decks for active/planned HS sponsors")
    parser.add_argument("--deck-root", default="data/pipeline_decks")
    parser.add_argument("--max-per-sponsor", type=int, default=4)
    parser.add_argument(
        "--source-config",
        default="data/source_configs/sponsor_sources.comprehensive.json",
        help="Optional sponsor source config to provide per-sponsor seed pages",
    )
    parser.add_argument(
        "--use-search-fallback",
        action="store_true",
        help="Use limited web search fallback for sponsors without useful seed pages",
    )
    args = parser.parse_args()

    source_config_path = Path(args.source_config) if args.source_config else None
    stats = harvest_investor_decks(
        deck_root=Path(args.deck_root),
        max_per_sponsor=args.max_per_sponsor,
        source_config_path=source_config_path,
        use_search_fallback=args.use_search_fallback,
    )
    print(stats)


if __name__ == "__main__":
    main()
