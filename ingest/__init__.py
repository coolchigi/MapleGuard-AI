"""Feature 1 — research / ingestion. Fetch official immigration data into cited records.

Currently: Express Entry rounds-of-invitations draws (`ingest.rounds`). Fetch is thin and
separable from parsing; parsing is pure, deterministic, and cites every value.
"""
from .models import DrawCitation, DrawRecord
from .rounds import (ROUNDS_JSON_URL, ROUND_PAGE_BASE, classify, fetch_rounds_json,
                     parse_round, parse_rounds, parse_rounds_json, round_sort_key,
                     sort_records, to_draws)

__all__ = [
    "DrawCitation", "DrawRecord",
    "ROUNDS_JSON_URL", "ROUND_PAGE_BASE", "classify",
    "parse_round", "parse_rounds", "parse_rounds_json", "to_draws", "fetch_rounds_json",
    "round_sort_key", "sort_records",
]
