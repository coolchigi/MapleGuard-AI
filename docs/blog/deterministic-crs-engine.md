# A deterministic CRS engine, checked against the government's own calculator

The Comprehensive Ranking System (CRS) is the score that ranks Express Entry candidates. It is arithmetic over published point grids: so many points for age, for education, for language, for Canadian work, plus a skill-transferability block and an additional-points block. The arithmetic is not hard. Getting it exactly right, and keeping it right as the rules change, is.

MapleGuard's CRS engine is a pure function of the profile. It reads no files, calls no network, and never asks a language model for the number. This post is about how it is built and, more importantly, how it proves itself correct.

## The shape: a pure function returning a breakdown

The engine returns a score split into its four blocks plus a line-item breakdown, so every point is traceable to a factor.

```python
@dataclass(frozen=True)
class LineItem:
    factor: str
    points: int


@dataclass(frozen=True)
class Score:
    core: int
    spouse: int
    skill_transfer: int
    additional: int
    breakdown: list[LineItem]

    @property
    def total(self) -> int:
        return self.core + self.spouse + self.skill_transfer + self.additional
```

The top-level function takes the profile and an optional date, computes each block, applies the official caps, and returns the total with its parts. The caps matter, because CRS is full of them.

```python
def crs(profile: Profile, as_of: date | None = None) -> Score:
    spouse_scored = profile.scored_with_spouse()
    age = profile.age_at(as_of)

    core_items = _core(profile, spouse_scored, age)
    spouse_items = _spouse(profile)
    transfer_items = _skill_transfer(profile)
    additional_items = _additional(profile)

    core_cap = T.CORE_MAX_SPOUSE if spouse_scored else T.CORE_MAX_SINGLE
    core = min(core_cap, sum(i.points for i in core_items))
    spouse = min(T.SPOUSE_MAX, sum(i.points for i in spouse_items))
    skill_transfer = min(T.SKILL_TRANSFER_MAX, sum(i.points for i in transfer_items))
    additional = min(T.ADDITIONAL_MAX, sum(i.points for i in additional_items))
    ...
```

Note that the core ceiling depends on whether a spouse is scored (460 with a spouse, 500 without). That is one of the places a naive calculator quietly gets the wrong number.

## The rules live in data, not in logic

The engine holds no magic numbers. Every point value lives in a `tables.py` module as a `Table` carrying its own name and a `verified` flag. A block function is just a lookup:

```python
items = [
    LineItem("age", age_t.values.get(age, 0)),
    LineItem("education", edu_t.values[profile.education]),
    LineItem("first_language", _lang_points(profile.first_language, first_t.values)),
    ...
]
```

Keeping the numbers in data has a payoff: a policy change is a data edit, and a test can police the data. This one fails if any table is not marked verified against its source:

```python
def test_table_provenance():
    """Every point table must be marked verified against the official source."""
    unverified = [t.name for t in T.ALL_TABLES if not t.verified]
    assert not unverified, f"Tables not yet verified against the source: {unverified}"
```

The same idea guards a rule that changed. Job-offer points were removed on 2025-03-25, and there is a regression test whose only job is to make sure they never silently return:

```python
def test_arranged_employment_is_zero():
    assert T.MAX_ADDITIONAL.values["arranged_employment"] == 0
```

## Skill transferability, and the over-count trap

Skill transferability is where CRS engines go wrong. There are three groups (education, foreign work, certificate of qualification). Each group sums two components and caps at 50, the whole block caps at 100, and the values are graduated by education tier and by whether the candidate clears the CLB 7 or CLB 9 language threshold. Miss any of those and you over-count.

The engine mirrors that structure literally, capping per group:

```python
edu_lang = T.EDU_LANG.values[edu_tier].get(b, 0) if (edu_tier and b) else 0
edu_work = T.EDU_WORK.values[edu_tier].get(cdn, 0) if edu_tier else 0
edu_group = min(50, edu_lang + edu_work)
```

The classic trap is the lone bachelor's degree. A single credential sits in the lower graduated tier, not the tier used for two or more credentials. It is an easy factor to get wrong, so it is pinned by an arithmetic anchor test with the value worked out by hand from the grid:

```python
def test_anchor_lone_bachelor_clb9_transfer_is_25():
    # A single bachelor's degree is one credential, so it sits in the 13/25 skill-transfer
    # tier rather than the 25/50 tier used for two-or-more credentials.
    p = Profile(education="bachelors-or-three-year", first_language=L(9), age=20)
    s = crs(p)
    assert s.core == 354
    assert s.skill_transfer == 25
    assert s.total == 379
```

A related anchor guards the other direction: maxed language on a secondary education still yields zero education skill-transfer points, because language alone does not unlock that group without a post-secondary credential. Both anchors exist so a refactor that "simplifies" the tiers gets caught immediately.

## The golden oracle: matching IRCC's own tool

Unit anchors prove the arithmetic in isolation. They do not prove the whole pipeline reproduces the government's result. For that there is a golden-oracle case: a full profile whose official number, taken from IRCC's own "Check your score" tool, is 474. It is loaded from a fixture and asserted on every run.

```python
@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c.get("name", "case"))
def test_golden_oracle(case):
    """Each case: a profile + the number IRCC's official tool gives. Engine must match."""
    if case.get("expected_total") is None:
        pytest.skip(f"{case['name']}: fill expected_total from the official IRCC tool")
    p = _profile_from_case(case["profile"])
    assert crs(p).total == case["expected_total"], case.get("note", "")
```

The oracle is the anchor for any claim that the engine is correct. Without a number confirmed against IRCC's own calculator, "our CRS is right" is an assertion. With it, the claim is checked on every test run, and a change that broke the arithmetic would fail before it could ship.

## Why build it this way

The engine is a pure function so it is trivial to test and impossible to make non-deterministic. The numbers live in data so a rule change is a reviewable edit and a provenance test can insist every value is sourced. The arithmetic is anchored by hand-computed cases at the exact spots calculators get wrong, and the whole pipeline is pinned to the government's own tool by the oracle.

That combination is what lets everything above the engine trust the number. The timeline, the reachable-path classification, and the alerting all recompute through this one function, so they inherit its correctness for free. The engine is the floor everything else stands on, which is exactly why it is the part that has to prove itself.

The model never touches any of this arithmetic. The engine reaches the model only as a Strands `@tool`, `compute_crs`, which deserializes the profile, calls `crs()`, and returns the total, the four subtotals, and the breakdown unchanged. The model picks the tool and reads the result. It is not asked to produce the number, so it cannot get it wrong. How that tool boundary is built, and how two deterministic gates keep the model from computing or asserting anything below it, is the subject of a separate post on the Strands layer.
