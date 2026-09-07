"""Tests for the KB corpus builder (agent/kb_corpus.py).

Offline: it writes files, no network, no AWS. The corpus is the cited passages the hosted agent
retrieves and quotes, built from the SAME source-verified NOC records as the dev store, so the KB
carries provenance (every chunk knows its canada.ca source) rather than the model's memory.

Run:  cd server && PYTHONPATH=. python3 -m pytest -q tests/test_kb_corpus.py
"""
import json

from agent import kb_documents, write_kb_corpus


def test_documents_carry_content_and_a_cited_source():
    docs = kb_documents()
    assert docs, "the corpus should not be empty"
    for doc_id, content, attrs in docs:
        assert doc_id and content
        assert attrs.get("source", "").startswith("http")  # every passage cites its source
        assert attrs.get("noc_code")
        # metadata is flat scalars only (Bedrock KB metadataAttributes contract).
        assert all(isinstance(v, (str, int, float, bool)) for v in attrs.values())


def test_lead_and_duty_passages_are_present_for_a_verified_occupation():
    kinds = {attrs.get("kind") for _id, _c, attrs in kb_documents()}
    assert {"lead_statement", "duty"} <= kinds


def test_write_kb_corpus_emits_txt_plus_metadata_sidecars(tmp_path):
    n = write_kb_corpus(str(tmp_path))
    assert n == len(kb_documents())
    txts = list(tmp_path.glob("*.txt"))
    metas = list(tmp_path.glob("*.txt.metadata.json"))
    assert len(txts) == n and len(metas) == n
    # A sidecar is the Bedrock KB shape and its attributes round-trip.
    sample = json.loads(metas[0].read_text())
    assert "metadataAttributes" in sample and sample["metadataAttributes"].get("source")


def test_rerun_overwrites_cleanly(tmp_path):
    write_kb_corpus(str(tmp_path))
    first = sorted(p.name for p in tmp_path.iterdir())
    write_kb_corpus(str(tmp_path))
    assert sorted(p.name for p in tmp_path.iterdir()) == first  # stable ids, no duplication
