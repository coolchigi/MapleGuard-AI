"""Build the Knowledge Base corpus: the cited passages the hosted agent RETRIEVES and quotes.

The KB (Amazon Bedrock Knowledge Base on S3 Vectors) sits BESIDE the deterministic rules, never in
front of them (see ARCHITECTURE.md). It does not decide a score or an eligibility verdict, those
stay in pure Python. Its job is to ground the agent's explanations in retrieved, cited government
text and to scale the NOC corpus beyond the hand-picked codes.

This module turns the SAME cited passages the dev store seeds (`memory.noc_seed_passages`, now
sourced from the source-verified NOC 2021 records of the ingestion pipeline) into the on-disk shape
a Bedrock KB S3 data source ingests: one text file per passage plus a `<file>.metadata.json`
sidecar carrying the citation (source URL, NOC code, version, verified flag). A retrieved chunk then
arrives with its own provenance, so the agent quotes cited text, not model memory.

Pure and offline: it writes files, it touches no network and no AWS. The credentialed provisioning
(create the S3 vector bucket + index and the KB, upload this corpus, run the ingestion job) lives in
`infra/kb/provision_s3_vectors_kb.py`, which the project lead runs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional


def _doc_id(meta: dict, index: int) -> str:
    """A stable, filesystem-safe id for one passage: NOC code + kind (+ duty id)."""
    parts = [f"noc-{meta.get('noc_code', 'x')}", str(meta.get("kind", "passage"))]
    if meta.get("duty_id"):
        parts.append(str(meta["duty_id"]))
    else:
        parts.append(str(index))
    return re.sub(r"[^A-Za-z0-9._-]+", "-", "-".join(parts)).strip("-")


def kb_documents(occupations: Optional[dict] = None) -> list[tuple[str, str, dict]]:
    """The KB corpus as (doc_id, content, metadata_attributes) triples. `content` is the passage
    the agent retrieves and quotes; `metadata_attributes` are the flat citation fields Bedrock KB
    stores per chunk (used for filtered retrieval and to surface the source)."""
    from .memory import noc_seed_passages
    docs: list[tuple[str, str, dict]] = []
    for i, (content, meta) in enumerate(noc_seed_passages(occupations)):
        # Keep only JSON-scalar metadata (Bedrock KB metadataAttributes are flat scalars).
        attrs = {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))}
        docs.append((_doc_id(meta, i), content, attrs))
    return docs


def write_kb_corpus(out_dir: str, occupations: Optional[dict] = None) -> int:
    """Write the corpus to `out_dir` as `<doc_id>.txt` + `<doc_id>.txt.metadata.json` (the shape a
    Bedrock KB S3 data source ingests). Returns the number of passages written. Overwrites the
    directory's prior corpus files so a re-run reflects the current source-verified records."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    for doc_id, content, attrs in kb_documents(occupations):
        txt = out / f"{doc_id}.txt"
        txt.write_text(content + "\n", encoding="utf-8")
        # Bedrock KB metadata sidecar: {"metadataAttributes": {<flat scalars>}}.
        (out / f"{doc_id}.txt.metadata.json").write_text(
            json.dumps({"metadataAttributes": attrs}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        count += 1
    return count
