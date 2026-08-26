# Letting a language model help without letting it invent facts

Reviewing a reference letter against the National Occupational Classification (NOC) is genuinely a reading task. You have a letter written in one company's words, and an official occupation with a lead statement and a list of main duties, and you have to decide which sentences describe which duties. This is the one place in MapleGuard where a language model is the right tool, because the job is understanding prose.

It is also the place where a language model is most dangerous, because a paraphrase or a confident summary can create coverage that is not really there. So the NOC audit pipeline is built to get the model's help on the reading while giving it no authority over the verdict. This post shows how, in code.

## The model does one job: propose verbatim matches

The model is asked for exactly one thing. For each required duty, quote the sentence in the letter that covers it, character for character, or omit it. Its instructions are explicit that a missing duty is a correct answer and that fabrication is not:

```
- Quote sentences EXACTLY as they appear in the letter, character for character. Never
  paraphrase, summarise, correct, or stitch fragments together. Copy the substring.
- Only map a duty when a sentence genuinely describes that work. If nothing covers a
  duty, omit it. A missing duty is a correct and useful answer.
- Never assert, imply, or comment on the applicant's eligibility, and never invent work
  that is not written in the letter.
```

The result is treated as a set of claims, not as truth. Each claim is a duty paired with the sentence that supposedly covers it. Nothing downstream trusts those claims until they are checked.

## validate_alignment: the quote has to be in the letter

The check is blunt and effective. Every quoted sentence must appear literally in the letter text. If it does not, the claimed coverage is dropped.

```python
def validate_alignment(letter_text, alignment, lead_evidence):
    """Drop any claimed coverage whose evidence is not actually present in the letter."""
    haystack = " ".join(letter_text.split()).lower()

    def present(snippet):
        snippet = " ".join((snippet or "").split()).lower()
        return bool(snippet) and snippet in haystack

    validated = {duty_id: ev for duty_id, ev in alignment.items() if present(ev)}
    return validated, present(lead_evidence)
```

This is the load-bearing line of the whole feature. A model that paraphrases loses that coverage, because the paraphrase is not a substring of the letter. A model that invents a sentence loses it for the same reason. The only way to earn coverage is to quote real text, so coverage can be cited but never fabricated. Whitespace and case are normalized first so a real quote is not rejected over formatting, but the substring itself has to be there.

## The deterministic scorer owns the verdict

Only after validation does a plain function decide coverage and pass or fail. The model never sees this step and never influences the threshold.

```python
def score_duties(occupation, alignment, lead_statement_covered, threshold=DEFAULT_THRESHOLD):
    required = occupation.required_duties()
    matches = [DutyMatch(duty, duty.id in alignment, alignment.get(duty.id, "")) for duty in required]
    covered = sum(1 for match in matches if match.covered)
    coverage = covered / len(required) if required else 1.0
    passed = lead_statement_covered and coverage >= threshold
    gaps = [Citation(occupation.code, occupation.version, occupation.source, duty.text)
            for duty in required if duty.id not in alignment]
    return DutyCoverageResult(
        lead_statement_covered=lead_statement_covered, matches=matches, threshold=threshold,
        coverage=coverage, passed=passed, gaps=gaps,
    )
```

DEFAULT_THRESHOLD is 0.8, the 80%-of-main-duties bar. Passing also requires the lead statement to be covered, not just enough duties. And every gap is a Citation back to the official NOC duty text, so a missing duty is reported as "this exact published duty is not covered," not as a vague suggestion.

Keeping the model out of scoring is what makes this a separate, testable step. The scorer can be exercised on its own with alignments injected directly, so the arithmetic of coverage and the pass/fail rule are verified without any model in the loop.

## The verification guard: unverified text is stamped, not hidden

The audit is only as trustworthy as the NOC reference text it scores against. Some occupation text has been seeded but not yet checked line by line against the official source. When that is the case, the report is stamped, deterministically, so no caller can mistake it for a verified result.

```python
def audit_letter(letter_text, occupation, matcher, threshold=DEFAULT_THRESHOLD):
    elements = check_mandatory_elements(letter_text)
    raw_alignment, lead_evidence = matcher(letter_text, occupation)
    alignment, lead_covered = validate_alignment(letter_text, raw_alignment, lead_evidence)
    duties = score_duties(occupation, alignment, lead_covered, threshold)
    needs_verification = not occupation.verified
    note = (f"NOC {occupation.code} reference text is not line-verified against the official "
            f"source ({occupation.source}); this audit is not a trustworthy result until it is."
            if needs_verification else "")
    return AuditReport(noc_code=occupation.code, elements=elements, duties=duties,
                       needs_verification=needs_verification, verification_note=note)
```

The guard sits below the model, in plain code, so it cannot be reasoned around. The audit still computes, but it carries an honest label about what it rests on.

## The correction draft, under the same rule, and re-auditable

Once the gaps are known, a second step drafts a corrected letter for the employer to sign. It runs under the same discipline as the matcher. It never asserts eligibility, and it never invents work. A duty it describes has to trace to a passage in the original letter or a fact the caller supplied, and titles, dates, hours, and salary are carried over unchanged. When a required duty has no support anywhere, the draft leaves a visible placeholder rather than fabricating coverage. The placeholder reads "employer to confirm" and names the duty.

That placeholder is the honest output. It tells the employer exactly what still needs confirming instead of quietly filling the gap with something plausible.

The payoff is that the draft is re-auditable. Run audit_letter on the corrected draft and the duties that had real support now validate as covered, because the draft quotes real supporting text, while any duty still resting on an unconfirmed placeholder stays flagged. The audit does not soften because a draft went through it. It re-checks from scratch.

## The posture, shown rather than claimed

This is what "compute and refuse" looks like in code. The model contributes where it is strong, at reading prose and proposing matches. Every proposal is validated against the source before it counts, so paraphrase and fabrication fail by construction. A deterministic scorer owns the pass/fail verdict at a fixed threshold, with every gap cited. A deterministic guard labels any result that rests on unverified text. And the draft refuses to invent work, leaving honest blanks instead.

None of this is enforced by asking the model nicely. It is enforced by the substring check, the separate scorer, and the verification stamp, which sit underneath the model and do not depend on it behaving. That is the difference between a tool that hopes the model did not make something up and one that cannot count it if it did.

The audit and the draft reach the orchestrating model as two Strands tools, `audit_reference_letter` and `draft_corrected_letter`. They run under the same policy layer as everything else: a hook that would cancel any tool that looked like filing an application, and a screen over the final response that refuses an eligibility verdict. So even the one feature where a model reads and rewrites prose stays inside the compute-and-refuse boundary. The Strands machinery that draws that boundary is covered in the post on the agent layer.
