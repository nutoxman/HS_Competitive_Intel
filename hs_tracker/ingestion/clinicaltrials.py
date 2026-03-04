"""ClinicalTrials.gov ingestion and normalization."""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

import requests

from hs_tracker.constants import (
    ACADEMIC_KEYWORDS,
    CRO_KEYWORDS,
    DEVICE_INTERVENTION_TYPES,
    INCLUDED_PHASES,
    PROCEDURAL_INTERVENTION_TYPES,
    PROCEDURAL_KEYWORDS,
    SYSTEMIC_INTERVENTION_TYPES,
    TOPICAL_KEYWORDS,
    US_ONLY_COUNTRIES,
)
from hs_tracker.service import (
    emit_trial_change_events,
    get_trial,
    resolve_product_id,
    upsert_trial,
)

CTGOV_BASE = "https://clinicaltrials.gov/api/v2/studies"

PHASE_MAP = {
    "EARLY_PHASE1": "Phase 1",
    "PHASE1": "Phase 1",
    "PHASE1_PHASE2": "Phase 1/Phase 2",
    "PHASE2": "Phase 2",
    "PHASE2_PHASE3": "Phase 2/Phase 3",
    "PHASE3": "Phase 3",
    "PHASE4": "Phase 4",
    "NA": None,
}


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    clean = value.strip()
    if len(clean) >= 10:
        return clean[:10]
    if len(clean) == 7:
        return f"{clean}-01"
    if len(clean) == 4:
        return f"{clean}-01-01"
    return None


def _ssl_verify_setting() -> bool | str:
    # Preferred: point to org CA bundle if outbound TLS is intercepted.
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


def _to_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize_phase(phases: list[str]) -> str | None:
    mapped = [PHASE_MAP.get(item, item) for item in phases if PHASE_MAP.get(item, item)]
    mapped = sorted(set(mapped), key=lambda x: (x or ""))
    if not mapped:
        return None
    if len(mapped) == 1:
        return mapped[0]
    if "Phase 1" in mapped and "Phase 2" in mapped:
        return "Phase 1/Phase 2"
    if "Phase 2" in mapped and "Phase 3" in mapped:
        return "Phase 2/Phase 3"
    return mapped[-1]


def _contains_keywords(texts: list[str], keywords: set[str]) -> bool:
    corpus = " ".join(texts).lower()
    return any(keyword in corpus for keyword in keywords)


def _sponsor_is_industry_or_cro(
    sponsor_class: str | None,
    sponsor_name: str | None,
    responsible_party_type: str | None,
) -> bool:
    sponsor_class = (sponsor_class or "").upper()
    sponsor_name_l = (sponsor_name or "").lower()
    resp_l = (responsible_party_type or "").lower()

    if sponsor_class == "INDUSTRY":
        return True
    if any(term in sponsor_name_l for term in CRO_KEYWORDS):
        return True
    if any(term in sponsor_name_l for term in ACADEMIC_KEYWORDS):
        return False
    return "sponsor" in resp_l and sponsor_class in {"OTHER", "UNKNOWN"}


def _extract_intervention_flags(interventions: list[dict[str, Any]]) -> dict[str, bool]:
    types = {str(item.get("type", "")).upper() for item in interventions}
    names = [str(item.get("name", "")) for item in interventions]

    has_systemic = bool(types.intersection(SYSTEMIC_INTERVENTION_TYPES))
    has_device = bool(types.intersection(DEVICE_INTERVENTION_TYPES))
    has_procedural = bool(types.intersection(PROCEDURAL_INTERVENTION_TYPES))

    has_topical_name = _contains_keywords(names, TOPICAL_KEYWORDS)
    has_procedural_name = _contains_keywords(names, PROCEDURAL_KEYWORDS)

    return {
        "has_systemic": has_systemic,
        "has_device": has_device,
        "has_procedural": has_procedural or has_procedural_name,
        "has_topical": has_topical_name,
    }


def _is_within_window(study_start_date: str | None, rolling_years: int, today: date) -> bool:
    if not study_start_date:
        return False
    try:
        parsed = date.fromisoformat(study_start_date[:10])
    except ValueError:
        return False
    cutoff = today - timedelta(days=365 * rolling_years)
    return parsed >= cutoff


def _is_non_us_only(countries: list[str]) -> bool:
    if not countries:
        return True
    normalized = {country.strip() for country in countries if country and country.strip()}
    if not normalized:
        return True
    return not normalized.issubset(US_ONLY_COUNTRIES)


def _build_trial_record(study: dict[str, Any], rolling_years: int, today: date) -> dict[str, Any]:
    protocol = study.get("protocolSection", {})
    id_mod = protocol.get("identificationModule", {})
    status_mod = protocol.get("statusModule", {})
    sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
    design_mod = protocol.get("designModule", {})
    contacts_mod = protocol.get("contactsLocationsModule", {})
    arms_mod = protocol.get("armsInterventionsModule", {})

    nct_id = id_mod.get("nctId")
    title = id_mod.get("briefTitle") or id_mod.get("officialTitle") or ""

    lead_sponsor = sponsor_mod.get("leadSponsor", {})
    sponsor_name = lead_sponsor.get("name")
    sponsor_class = lead_sponsor.get("class")

    phase = _normalize_phase(_to_list(design_mod.get("phases")))
    status = status_mod.get("overallStatus")
    start_date = _parse_date((status_mod.get("startDateStruct") or {}).get("date"))
    primary_completion = _parse_date(
        (status_mod.get("primaryCompletionDateStruct") or {}).get("date")
    )
    completion_date = _parse_date((status_mod.get("completionDateStruct") or {}).get("date"))

    first_posted = _parse_date((status_mod.get("studyFirstPostDateStruct") or {}).get("date"))
    last_update = _parse_date((status_mod.get("lastUpdatePostDateStruct") or {}).get("date"))
    results_posted = _parse_date((status_mod.get("resultsFirstPostDateStruct") or {}).get("date"))

    responsible_party_type = (
        protocol.get("responsiblePartyModule", {}) or {}
    ).get("responsiblePartyType")
    study_type = design_mod.get("studyType", "")

    enrollment_info = design_mod.get("enrollmentInfo", {})
    enrollment = enrollment_info.get("count") if isinstance(enrollment_info, dict) else None
    try:
        enrollment_int = int(enrollment) if enrollment is not None else None
    except (ValueError, TypeError):
        enrollment_int = None

    locations = _to_list(contacts_mod.get("locations"))
    countries = sorted(
        {
            location.get("country", "").strip()
            for location in locations
            if isinstance(location, dict) and location.get("country")
        }
    )

    interventions = _to_list(arms_mod.get("interventions"))
    interventions = [item for item in interventions if isinstance(item, dict)]
    intervention_flags = _extract_intervention_flags(interventions)

    inclusion_flag = True
    exclusion_reason = None

    if "INTERVENTIONAL" not in str(study_type).upper():
        inclusion_flag = False
        exclusion_reason = "other"

    if phase == "Phase 4":
        inclusion_flag = False
        exclusion_reason = "phase_4"
    elif phase not in INCLUDED_PHASES:
        inclusion_flag = False
        exclusion_reason = "other"

    if not _is_within_window(start_date, rolling_years, today):
        inclusion_flag = False
        exclusion_reason = "out_of_window"

    if not _sponsor_is_industry_or_cro(sponsor_class, sponsor_name, responsible_party_type):
        inclusion_flag = False
        exclusion_reason = "academic"

    if intervention_flags["has_topical"]:
        inclusion_flag = False
        exclusion_reason = "topical"

    if intervention_flags["has_device"] and not intervention_flags["has_systemic"]:
        inclusion_flag = False
        exclusion_reason = "device_only"

    if intervention_flags["has_systemic"] and intervention_flags["has_procedural"]:
        inclusion_flag = False
        exclusion_reason = "procedural_hybrid"

    if not _is_non_us_only(countries):
        inclusion_flag = False
        exclusion_reason = "other"

    intervention_names = [str(item.get("name", "")) for item in interventions]

    return {
        "trial_id": nct_id,
        "title": title,
        "sponsor_display": sponsor_name,
        "responsible_party_type": responsible_party_type,
        "phase": phase,
        "status": status,
        "study_start_date": start_date,
        "primary_completion_date": primary_completion,
        "completion_date": completion_date,
        "enrollment": enrollment_int,
        "countries": countries,
        "url": f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else None,
        "first_posted": first_posted,
        "last_update_posted": last_update,
        "results_first_posted": results_posted,
        "inclusion_flag": inclusion_flag,
        "exclusion_reason": exclusion_reason,
        "intervention_names": intervention_names,
        "raw_payload": study,
    }


def _fetch_page(next_page_token: str | None, page_size: int) -> dict[str, Any]:
    params = {
        "query.cond": "Hidradenitis Suppurativa",
        "format": "json",
        "pageSize": str(page_size),
    }
    if next_page_token:
        params["pageToken"] = next_page_token

    url = f"{CTGOV_BASE}?{urlencode(params)}"
    verify = _ssl_verify_setting()
    try:
        response = requests.get(  # noqa: S113
            url,
            timeout=60,
            verify=verify,
            headers={
                "User-Agent": "hs-tracker-bot/1.0 (+https://example.local/hs-tracker)",
            },
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.SSLError as exc:
        raise RuntimeError(
            "ClinicalTrials.gov SSL verification failed. Set HS_TRACKER_CA_BUNDLE "
            "to your trusted CA bundle path, or set HS_TRACKER_SKIP_SSL_VERIFY=1 "
            "for local testing only."
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"ClinicalTrials.gov fetch failed: {exc}") from exc


def refresh_clinicaltrials(
    conn,
    rolling_years: int,
    page_size: int = 100,
    max_pages: int = 30,
) -> dict[str, int]:
    stats = {
        "fetched": 0,
        "upserted": 0,
        "with_product_mapping": 0,
        "without_product_mapping": 0,
        "events_emitted": 0,
    }

    today = date.today()
    next_page_token: str | None = None

    for _ in range(max_pages):
        payload = _fetch_page(next_page_token, page_size)
        studies = payload.get("studies", [])
        if not studies:
            break

        for study in studies:
            trial = _build_trial_record(study, rolling_years=rolling_years, today=today)
            if not trial.get("trial_id"):
                continue
            stats["fetched"] += 1

            candidates = [
                trial.get("title", ""),
                *trial.get("intervention_names", []),
                (study.get("protocolSection", {}).get("identificationModule", {}) or {}).get(
                    "acronym", ""
                ),
            ]
            product_id = resolve_product_id(conn, [item for item in candidates if item])
            trial["product_id"] = product_id

            if product_id:
                stats["with_product_mapping"] += 1
            else:
                stats["without_product_mapping"] += 1

            before = get_trial(conn, trial["trial_id"])
            upsert_trial(conn, trial)
            after = get_trial(conn, trial["trial_id"])
            emitted = emit_trial_change_events(conn, before=before, after=after or trial)
            stats["events_emitted"] += len(emitted)
            stats["upserted"] += 1

        next_page_token = payload.get("nextPageToken")
        if not next_page_token:
            break

    return stats
