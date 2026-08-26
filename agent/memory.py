"""The cited-corpus memory layer, with a dev mirror and a marked Bedrock KB seam.

MapleGuard's trust story is "every claim carries a real source". Today the NOC lead
statements and duties live as cited strings in `noc/data.py`. This layer lets the agent
RETRIEVE that reference text at question time and quote the retrieved passage, so a citation
is a live lookup rather than a transcription the model could drift from.

Two backends behind one `strands.memory.MemoryManager` interface:
  - dev:  `TestMemoryStore` (keyword recall, `persist=False`), seeded from `noc.OCCUPATIONS`.
          No AWS, fully offline, so retrieval-shaped code is testable here.
  - deploy: `BedrockKnowledgeBaseStore` over a provisioned Knowledge Base. This is a real
          seam, not faked: `build_kb_memory` constructs the actual store, which needs live
          Bedrock to answer. Swapping dev->deploy is a one-call change.

THE BRIGHT LINE: only reference TEXT goes in the corpus (NOC prose, rule prose). Cutoff and
score NUMBERS never come from semantic search into `crs()` / `reachable_paths()`. Those stay
in the deterministic `ingest.rounds` path, which refuses an unparseable value rather than
guessing. A KB can return an approximate or reworded number; the engine must never read one
from it. Memory cites the rule; deterministic ingest owns the cutoff.

Strands is imported lazily inside each builder, so this module imports with or without the
SDK. The async store methods are wrapped in small sync helpers for seeding and tests.
"""
from __future__ import annotations

from typing import Any, Optional

from noc import OCCUPATIONS
from noc.models import NocOccupation

CORPUS_NAME = "ircc_corpus"
CORPUS_DESCRIPTION = (
    "IRCC reference text: NOC 2021 lead statements and main duties (and, once ingested, rule "
    "prose and draw-history narrative). The passages the agent quotes and cites. Never the "
    "cutoff numbers the engine scores against."
)


def noc_seed_passages(occupations: Optional[dict[str, NocOccupation]] = None
                      ) -> list[tuple[str, dict]]:
    """Reference passages to seed the corpus with, as (content, metadata) pairs.

    One passage per occupation lead statement and one per main duty, each stamped with the
    NOC code, version, and source URL, so a retrieved passage carries its own citation. Seeds
    from `noc.OCCUPATIONS` (NOC 21234 and any other seeded codes) by default.
    """
    occupations = OCCUPATIONS if occupations is None else occupations
    passages: list[tuple[str, dict]] = []
    for occ in occupations.values():
        base = {"noc_code": occ.code, "version": occ.version, "source": occ.source,
                "verified": occ.verified}
        passages.append((f"NOC {occ.code} {occ.title} — lead statement: {occ.lead_statement}",
                         {**base, "kind": "lead_statement"}))
        for duty in occ.main_duties:
            passages.append((f"NOC {occ.code} main duty {duty.id}: {duty.text}",
                             {**base, "kind": "duty", "duty_id": duty.id,
                              "optional": duty.optional}))
    return passages


# ------------------------------------------------------------------- async wrappers
def seed_store(store: Any, passages: list[tuple[str, dict]]) -> int:
    """Add passages to a writable store. Sync wrapper over the async `store.add`. Returns the
    number added."""
    import asyncio

    async def _add_all() -> int:
        for content, meta in passages:
            await store.add(content, meta)
        return len(passages)

    return asyncio.run(_add_all())


def search_sync(store: Any, query: str, max_results: int = 3) -> list:
    """Query a store synchronously (for tests / seeding checks). Returns MemoryEntry list;
    each entry's `.metadata` carries the passage's `source` (and `_relevanceScore`, plus
    `_sourceLocation` from a real KB) — the citation surface."""
    import asyncio
    from strands.memory.types import SearchOptions

    return asyncio.run(store.search(query, SearchOptions(max_search_results=max_results)))


# ----------------------------------------------------------------------- dev backend
def build_test_memory(persist: bool = False, seed: bool = True, name: str = CORPUS_NAME):
    """Dev memory: a seeded `TestMemoryStore` behind a `MemoryManager`. No AWS.

    Returns (MemoryManager, store). The manager auto-provides the agent a memory-search tool
    and injects retrieved context (SDK defaults), so the agent retrieves and cites on its own.
    """
    from strands.memory import MemoryManager
    from strands.vended_memory_stores.test_memory_store import TestMemoryStore

    store = TestMemoryStore(name=name, persist=persist, writable=True)
    if seed:
        seed_store(store, noc_seed_passages())
    return MemoryManager(stores=[store]), store


# -------------------------------------------------------------- deploy backend (seam)
def build_kb_memory(knowledge_base_id: str, name: str = CORPUS_NAME,
                    description: str = CORPUS_DESCRIPTION, **kb_config: Any):
    """Deploy memory: a `BedrockKnowledgeBaseStore` over a provisioned Knowledge Base.

    This is a real seam, not a stub: it constructs the actual store, which needs live Bedrock
    (IAM: bedrock:Retrieve, bedrock:GetKnowledgeBase, and bedrock:IngestKnowledgeBaseDocuments
    for writes). Extra `config` keys (knowledge_base_type, data_source_type, region_name, ...)
    pass through. Verified against SDK 1.53.0: `BedrockKnowledgeBaseStore(name, description,
    config={"knowledge_base_id": ...})`.

    Returns (MemoryManager, store).
    """
    from strands.memory import MemoryManager
    from strands.vended_memory_stores import BedrockKnowledgeBaseStore

    store = BedrockKnowledgeBaseStore(
        name=name, description=description,
        config={"knowledge_base_id": knowledge_base_id, **kb_config},
    )
    return MemoryManager(stores=[store]), store
