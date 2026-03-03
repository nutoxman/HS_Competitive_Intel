"""Seed helpers for known HS programs."""

from __future__ import annotations

import sqlite3

from hs_tracker.service import upsert_product


SEED_PRODUCTS = [
    {
        "canonical_name": "Remibrutinib",
        "company": "Novartis",
        "modality": "Small molecule",
        "aliases": ["LOU064", "LYS006"],
        "target_class": "BTK inhibitor",
    },
    {
        "canonical_name": "Povorcitinib",
        "company": "Incyte",
        "modality": "Small molecule",
        "aliases": ["INCB054707"],
        "target_class": "JAK1 inhibitor",
    },
    {
        "canonical_name": "Sonelokimab",
        "company": "MoonLake",
        "modality": "Antibody",
        "aliases": ["M1095"],
        "target_class": "IL-17A/F",
    },
]


def seed_default_products(conn: sqlite3.Connection) -> int:
    created = 0
    for item in SEED_PRODUCTS:
        upsert_product(
            conn,
            canonical_name=item["canonical_name"],
            company=item["company"],
            modality=item["modality"],
            aliases=item.get("aliases"),
            target_class=item.get("target_class"),
        )
        created += 1
    return created
