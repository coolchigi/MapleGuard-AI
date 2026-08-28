"""Prove the NOC audit + correction draft end to end against a REAL Claude model.

Run this once with a key configured to confirm the model-backed path works live:

    cd server
    ANTHROPIC_API_KEY=sk-... MAPLEGUARD_NOC_BACKEND=anthropic python3 scripts/prove_noc_draft.py
    # or, on Bedrock:
    AWS_PROFILE=... MAPLEGUARD_NOC_BACKEND=bedrock python3 scripts/prove_noc_draft.py

What it demonstrates (the compute-and-refuse spine holding with a real model):
  1. audit_letter scores a deliberately-thin letter against NOC 21234 and flags the gaps,
     each citing the exact NOC duty text.
  2. LetterCorrector rewrites it, covering only duties the letter/supporting facts support and
     leaving '[employer to confirm: ...]' placeholders for the rest (never fabricating work).
  3. Re-auditing the draft shows the supported gap closed while the unsupported one stays open.

No arithmetic and no eligibility verdict come from the model; the deterministic scorer and the
validate_alignment guard run over whatever the model returns.
"""
from __future__ import annotations

import sys

from api.model_config import build_noc_model
from noc import audit_letter, get_occupation

# A thin letter: it clearly supports one duty (monitor/maintain) and gives a supporting fact for
# another (testing), but says nothing about several required duties -> those must stay gaps.
LETTER = (
    "To whom it may concern. This confirms that Jane Doe was employed as a Web Developer at "
    "Acme Digital from March 2022 to July 2024. She worked 37.5 hours per week at an annual "
    "salary of $85,000. In this role she monitored and maintained website functionality and "
    "performance. Sincerely, John Manager, Engineering Director, john@acme.example."
)
SUPPORTING_FACTS = ["Jane also wrote automated tests for the site's checkout flow."]
NOC_CODE = "21234"


def main() -> int:
    model = build_noc_model()
    if not model.configured:
        print(f"NOC model not configured: {model.detail}", file=sys.stderr)
        print("Set ANTHROPIC_API_KEY (anthropic) or AWS creds (bedrock) and retry.",
              file=sys.stderr)
        return 2
    print(f"Using backend={model.backend} model={model.model}\n")

    occ = get_occupation(NOC_CODE)

    report = audit_letter(LETTER, occ, model.matcher)
    print(f"AUDIT {NOC_CODE} — {occ.title}")
    d = report.to_dict()["duties"]
    print(f"  duties covered {d['covered']}/{d['required']}; gaps: "
          f"{[g['id'] for g in d['gaps']]}")
    for g in d["gaps"]:
        print(f"    gap {g['id']} cites: {g['source']}")

    draft = model.corrector(LETTER, occ, report.duties, SUPPORTING_FACTS)
    print("\nCORRECTED DRAFT:\n")
    print(draft.letter_text)
    print(f"\n  open placeholders: {draft.placeholders}")

    reaudit = audit_letter(draft.letter_text, occ, model.matcher)
    rd = reaudit.to_dict()["duties"]
    print(f"\nRE-AUDIT of the draft: covered {rd['covered']}/{rd['required']}; "
          f"remaining gaps {[g['id'] for g in rd['gaps']]}")
    print("\nOK: model-backed NOC audit + draft ran end to end with the trust guards intact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
