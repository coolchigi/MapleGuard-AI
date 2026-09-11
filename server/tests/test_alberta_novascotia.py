"""Alberta (AAIP) and Nova Scotia (NSNP), modelled as job-offer / EOI gate models, like Ontario.

Neither publishes a candidate self-score grid: AAIP mostly requires an Alberta job offer (or
selection through the Alberta Express Entry Worker EOI), and NSNP selects from an Expression of
Interest pool in discretionary, priority-based draws. We never assert eligibility for either (it
turns on a job offer or a discretionary province selection we do not collect); eligible stays None,
cited to each province's official page.

Run:  cd server && PYTHONPATH=. python3 -m pytest -q tests/test_alberta_novascotia.py
"""
from crs import LanguageScores, Profile
from paths import eligible_pathways


def L(clb):
    return LanguageScores(clb, clb, clb, clb)


def _profile():
    return Profile(age=30, education="masters-or-professional", first_language=L(9))


def test_alberta_is_a_cited_gate_model_never_asserted_eligible():
    m = eligible_pathways(_profile())
    ab = next(p for p in m.pathways if p.slug == "pnp-alberta")
    assert ab.rule_kind == "pnp"
    assert ab.eligible is None
    assert ab.score_kind == "none"
    assert "alberta.ca" in ab.source_url


def test_nova_scotia_is_a_cited_gate_model_never_asserted_eligible():
    m = eligible_pathways(_profile())
    ns = next(p for p in m.pathways if p.slug == "pnp-nova-scotia")
    assert ns.rule_kind == "pnp"
    assert ns.eligible is None
    assert ns.score_kind == "none"
    assert "liveinnovascotia.com" in ns.source_url


def test_pnp_pathway_count_is_still_eleven():
    # BC, Saskatchewan, Ontario, Manitoba, Alberta, Nova Scotia (each modelled directly) plus the
    # 5 remaining eligibility-only provinces/territories (New Brunswick, Newfoundland and Labrador,
    # Northwest Territories, Prince Edward Island, Yukon).
    m = eligible_pathways(_profile())
    pnp_slugs = [p.slug for p in m.pathways if p.rule_kind == "pnp"]
    assert len(pnp_slugs) == 11
