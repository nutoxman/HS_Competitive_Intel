"""Shared constants for HS competitive intelligence tracker."""

from __future__ import annotations

from datetime import timedelta

DEFAULT_ROLLING_YEARS = 5
ACTIVITY_WINDOW_DAYS = 365
PIPELINE_QUIET_DAYS = 180
GREEN_DAYS = 90
YELLOW_DAYS = 180

MODALITY_VALUES = {
    "Small molecule",
    "Antibody",
    "Oligonucleotide",
    "Other",
}

PHASE_ORDER = {
    "Phase 1": 1,
    "Phase 1/Phase 2": 2,
    "Phase 2": 3,
    "Phase 2/Phase 3": 4,
    "Phase 3": 5,
}

INCLUDED_PHASES = {
    "Phase 1",
    "Phase 1/Phase 2",
    "Phase 2",
    "Phase 2/Phase 3",
    "Phase 3",
}

ACTIVE_TRIAL_STATUSES = {
    "RECRUITING",
    "ACTIVE_NOT_RECRUITING",
}

PR_PIPELINE_SOURCE_TYPES = {
    "press_release",
    "pipeline_deck",
    "pipeline_page",
}

EVENT_TYPE_TO_CATEGORY = {
    "trial_first_posted": "Registry",
    "study_start": "Registry",
    "trial_registry_update": "Registry",
    "trial_status_change": "Registry",
    "results_posted": "Registry",
    "press_release_pipeline_update": "PR/Pipeline",
    "investor_deck_pipeline_slide": "PR/Pipeline",
    "publication": "Scientific",
    "conference_abstract": "Scientific",
    "news_analysis": "News/Analysis",
    "regulatory_corporate_filing": "Regulatory",
    "pipeline_mention_removed": "PR/Pipeline",
    "pipeline_mention_added": "PR/Pipeline",
    "pipeline_mention_absent": "PR/Pipeline",
}

DEFAULT_EVENT_WEIGHTS = {
    "results_posted": 5,
    "study_start": 5,
    "trial_status_change": 4,
    "pipeline_mention_removed": 6,
    "pipeline_mention_added": 5,
    "press_release_pipeline_update": 3,
    "investor_deck_pipeline_slide": 4,
    "publication": 3,
    "conference_abstract": 2,
    "news_analysis": 1,
    "trial_registry_update": 1,
    "trial_first_posted": 3,
    "regulatory_corporate_filing": 5,
    "pipeline_mention_absent": 1,
}

HIGH_SIGNAL_EVENT_TYPES = {
    "results_posted",
    "trial_status_change",
    "study_start",
    "regulatory_corporate_filing",
    "pipeline_mention_removed",
    "pipeline_mention_added",
}

TOPICAL_KEYWORDS = {
    "topical",
    "cream",
    "gel",
    "ointment",
    "lotion",
    "foam",
}

PROCEDURAL_KEYWORDS = {
    "surgery",
    "surgical",
    "excision",
    "deroofing",
    "procedure",
}

SYSTEMIC_INTERVENTION_TYPES = {"DRUG", "BIOLOGICAL"}
DEVICE_INTERVENTION_TYPES = {"DEVICE"}
PROCEDURAL_INTERVENTION_TYPES = {"PROCEDURE"}

CRO_KEYWORDS = {
    "cro",
    "clinical research",
    "iqvia",
    "parexel",
    "syneos",
    "icon plc",
    "ppd",
    "medpace",
}

ACADEMIC_KEYWORDS = {
    "university",
    "hospital",
    "institute",
    "medical center",
    "college",
}

US_ONLY_COUNTRIES = {"United States", "US", "USA"}

DATE_FMT = "%Y-%m-%d"


def activity_window_delta() -> timedelta:
    return timedelta(days=ACTIVITY_WINDOW_DAYS)


def quiet_window_delta() -> timedelta:
    return timedelta(days=PIPELINE_QUIET_DAYS)
