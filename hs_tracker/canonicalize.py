"""Canonicalization and alias matching utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass

PUNCT_RE = re.compile(r"[^a-z0-9\s]")
SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class NormalizedText:
    normalized: str
    compact: str


def normalize_text(value: str) -> str:
    lowered = value.lower().strip()
    no_punct = PUNCT_RE.sub(" ", lowered)
    return SPACE_RE.sub(" ", no_punct).strip()


def normalize_for_match(value: str) -> NormalizedText:
    normalized = normalize_text(value)
    compact = normalized.replace(" ", "")
    return NormalizedText(normalized=normalized, compact=compact)


def alias_matches_text(alias: str, text: str) -> bool:
    if not alias or not text:
        return False

    alias_norm = normalize_for_match(alias)
    text_norm = normalize_for_match(text)
    if alias_norm.normalized == text_norm.normalized:
        return True

    bounded = f" {text_norm.normalized} "
    token = f" {alias_norm.normalized} "
    if token in bounded:
        return True

    return alias_norm.compact in text_norm.compact
