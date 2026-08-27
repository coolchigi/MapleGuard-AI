"""Feature 1 — research / ingestion. Fetch official immigration data into cited records.

- Express Entry rounds-of-invitations draws (`ingest.rounds`): fetch is thin and separable
  from parsing; parsing is pure, deterministic, and cites every value.
- 2026 category-based selection rules (`ingest.categories`): verified NOC lists + the French
  language rule, with a deterministic, cited eligibility check that `paths` consumes.
"""
from .models import DrawCitation, DrawRecord
from .rounds import (ROUNDS_JSON_URL, ROUND_PAGE_BASE, classify, fetch_rounds_json,
                     parse_round, parse_rounds, parse_rounds_json, round_sort_key,
                     sort_records, to_draws)
from .categories import (CATEGORY_RULES, CATEGORY_SOURCE_URL, CATEGORY_SOURCE_DATE,
                         CANONICAL_SLUGS, CategoryRule, CategoryEligibility,
                         category_eligibility, categories_for_noc, resolve_category)

__all__ = [
    "DrawCitation", "DrawRecord",
    "ROUNDS_JSON_URL", "ROUND_PAGE_BASE", "classify",
    "parse_round", "parse_rounds", "parse_rounds_json", "to_draws", "fetch_rounds_json",
    "round_sort_key", "sort_records",
    "CATEGORY_RULES", "CATEGORY_SOURCE_URL", "CATEGORY_SOURCE_DATE", "CANONICAL_SLUGS",
    "CategoryRule", "CategoryEligibility", "category_eligibility", "categories_for_noc",
    "resolve_category",
]
