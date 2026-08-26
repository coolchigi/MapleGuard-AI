"""Resolve NOC audit citations from the retrieved corpus, not from hardcoded strings.

The deterministic `noc.audit_letter` already cites every gap to the NOC text it scored
against, taking the source from the seeded `NocOccupation` in `noc/data.py`. That is honest
but static: the citation is a string we transcribed. This module closes the last link of
"every claim cited" as a LIVE retrieval — for each flagged gap it looks the duty up in the
cited corpus (a `TestMemoryStore` in dev, a Bedrock Knowledge Base in deploy) and attaches
the source of the passage the corpus actually returned.

What changes and what does not: the audit result (which duties are covered, coverage, pass/
fail, the NOC text of each gap) is unchanged and still fully deterministic. Only the gap's
`source` is upgraded from "the string in data.py" to "the source of the retrieved passage",
and a `cited_via` field records which path produced it. When retrieval finds nothing, the
seed citation stands and `cited_via` says so — retrieval never invents or replaces text, it
only re-sources what the deterministic scorer already flagged.

This stays on the right side of the bright line: retrieval sources reference TEXT. It never
feeds a number into the engine.
"""
from __future__ import annotations

from typing import Any, Optional

from .memory import search_sync


def retrieve_citation(store: Any, noc_code: str, duty_text: str,
                      max_results: int = 3) -> Optional[dict]:
    """Retrieve the corpus passage backing one NOC duty, or None if the corpus has no match
    for this occupation. Returns the retrieved source, the passage text, and its relevance."""
    hits = search_sync(store, f"NOC {noc_code} {duty_text}", max_results=max_results)
    for hit in hits:
        meta = getattr(hit, "metadata", None) or {}
        if meta.get("noc_code") == noc_code:
            return {
                "source": meta.get("source"),
                "retrieved_text": getattr(hit, "content", ""),
                "relevance_score": meta.get("_relevanceScore"),
                "source_location": meta.get("_sourceLocation"),
            }
    return None


def cite_gaps_from_corpus(report_dict: dict, store: Any) -> dict:
    """Re-source every gap citation in a serialized audit report from the corpus, in place.

    For each gap, retrieve the passage for its (noc_code, duty text). On a hit, set the gap's
    `source` to the retrieved passage's source and stamp `cited_via="corpus_retrieval"` with
    the retrieved text and relevance. On a miss, keep the seed citation and stamp
    `cited_via="seed"`. Returns the same dict (mutated) for convenience.
    """
    gaps = report_dict.get("duties", {}).get("gaps", [])
    for gap in gaps:
        found = retrieve_citation(store, gap.get("noc_code", ""), gap.get("text", ""))
        if found and found.get("source"):
            gap["cited_via"] = "corpus_retrieval"
            gap["source"] = found["source"]
            gap["retrieved_text"] = found["retrieved_text"]
            if found.get("relevance_score") is not None:
                gap["relevance_score"] = found["relevance_score"]
            if found.get("source_location") is not None:
                gap["source_location"] = found["source_location"]
        else:
            gap["cited_via"] = "seed"
    report_dict.setdefault("citations", {})["resolved_from"] = (
        "corpus_retrieval" if any(g.get("cited_via") == "corpus_retrieval" for g in gaps)
        else "seed"
    )
    return report_dict
