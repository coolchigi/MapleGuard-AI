"use client";

/**
 * The candidate profile form — the input side of the dashboard.
 *
 * It owns one piece of state: the working `Profile`, shaped exactly like the Python dataclass it
 * will be deserialized into. Submitting hands that object to the parent, which sends it to
 * `POST /dashboard`; this component computes nothing. Every number on the other two tabs comes
 * back from the engine.
 *
 * Two behaviours worth knowing about:
 *  - Conditional sections (spouse, second language) are *revealed*, not gated: unticking a
 *    toggle hides the detail but keeps what was typed, and `toRequestProfile` strips it on the
 *    way out so a hidden field can never score.
 *  - Validation is inline and advisory; `agent/serde.py` remains the authority and its 422
 *    detail is surfaced by the caller.
 */
import React, { useMemo, useState } from "react";

import type { EducationLevel, LanguageScores, Profile } from "@/data/types";
import {
  CLB_LEVELS,
  DEFAULT_PROFILE,
  EDUCATION_OPTIONS,
  LANGUAGE_ABILITIES,
  MARITAL_OPTIONS,
  STUDY_YEAR_OPTIONS,
  WORK_YEAR_OPTIONS,
  ageOn,
  evenLanguage,
  spouseIsScored,
  testExpiryOf,
  validateProfile,
  type ProfileErrors,
} from "@/lib/profile";
import { Cite, Masthead } from "./atoms";
import { DateField, Fieldset, LanguageGrid, SelectField, ToggleField } from "./FormControls";

const YEAR_OPTIONS = WORK_YEAR_OPTIONS.map((n) => ({
  value: n,
  label: n === 0 ? "None" : n === 1 ? "1 year" : n === 5 ? "5 years or more" : `${n} years`,
}));

const STUDY_OPTIONS = STUDY_YEAR_OPTIONS.map((n) => ({
  value: n,
  label: n === 0 ? "None" : n === 3 ? "3 years or more" : n === 1 ? "1 year" : `${n} years`,
}));

const EDUCATION_SELECT = EDUCATION_OPTIONS.map(({ value, label }) => ({ value, label }));

export function ProfileForm({
  initialProfile = DEFAULT_PROFILE,
  onSubmit,
  onReset,
  loading = false,
  submitLabel = "COMPUTE MY POSITION",
  /** A server-side rejection (422 detail), shown above the submit button. */
  serverError,
  /** Free-form status line under the header, e.g. which document is currently on screen. */
  status,
}: {
  initialProfile?: Profile;
  onSubmit: (profile: Profile) => void;
  onReset?: () => void;
  loading?: boolean;
  submitLabel?: string;
  serverError?: string | null;
  status?: React.ReactNode;
}) {
  const [profile, setProfile] = useState<Profile>(initialProfile);
  const [showErrors, setShowErrors] = useState(false);

  // A second language is "on" when the profile carries one at all; the object doubles as the
  // toggle so there is no second source of truth to keep in sync.
  const [secondLanguageOn, setSecondLanguageOn] = useState(initialProfile.second_language !== null);

  const errors: ProfileErrors = useMemo(() => validateProfile(profile), [profile]);
  const visible = (field: keyof Profile) => (showErrors ? errors[field] : undefined);

  const set = <K extends keyof Profile>(key: K, value: Profile[K]) =>
    setProfile((p) => ({ ...p, [key]: value }));

  const scoresSpouse = spouseIsScored(profile);
  const hasPartner =
    profile.marital_status === "married" || profile.marital_status === "common-law";
  const age = ageOn(profile.date_of_birth);
  const expiry = testExpiryOf(profile);

  const secondLanguage: LanguageScores = profile.second_language ?? evenLanguage(0);
  const spouseLanguage: LanguageScores = profile.spouse_first_language ?? evenLanguage(0);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setShowErrors(true);
    if (Object.keys(errors).length > 0) {
      document.querySelector<HTMLElement>('[data-invalid="true"]')?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
      return;
    }
    onSubmit(profile);
  };

  const resetAll = () => {
    setProfile(DEFAULT_PROFILE);
    setSecondLanguageOn(DEFAULT_PROFILE.second_language !== null);
    setShowErrors(false);
    onReset?.();
  };

  return (
    <div className="sheet">
      <div className="sheet-inner">
        <Masthead label="Candidate particulars" />

        <div className="mg-form-head">
          <h1 className="mg-form-title">
            Your profile, as the grid reads it.
          </h1>
          <p className="mg-form-lede">
            Every field below is an input to the published IRCC grids — nothing here is scored in
            the browser. Submit and the Python engine returns the breakdown and the dated cliffs.
          </p>
          {status && <div className="mg-form-status">{status}</div>}
        </div>

        <form onSubmit={submit} noValidate>
          {/* ---------------------------------------------------------- A · identity */}
          <Fieldset code="A" title="AGE & EDUCATION">
            <DateField
              label="Date of birth"
              hint={age !== null ? `age ${age} today` : "YYYY-MM-DD"}
              error={visible("date_of_birth")}
              value={profile.date_of_birth}
              onChange={(v) => set("date_of_birth", v)}
            />
            <SelectField<EducationLevel>
              label="Highest credential"
              hint="Canadian, or foreign with an ECA"
              value={profile.education}
              options={EDUCATION_SELECT}
              onChange={(v) => set("education", v)}
            />
            <SelectField
              label="Marital status"
              value={profile.marital_status}
              options={MARITAL_OPTIONS}
              onChange={(v) => set("marital_status", v)}
            />
          </Fieldset>

          {/* ---------------------------------------------------------- B · language */}
          <Fieldset
            code="B"
            title="LANGUAGE"
            hint="Canadian Language Benchmark per ability. IELTS/CELPIP/TEF results convert to CLB; the grid awards nothing below CLB 4 and stops rising at CLB 10."
          >
            <LanguageGrid
              title="First official language"
              abilities={LANGUAGE_ABILITIES}
              levels={CLB_LEVELS}
              value={profile.first_language}
              error={visible("first_language")}
              onChange={(v) => set("first_language", v)}
            />
            <DateField
              label="Test taken on"
              hint={
                expiry
                  ? `results lapse ${expiry} — the time machine's steepest cliff`
                  : "optional; without it there is no expiry cliff"
              }
              error={visible("first_language_test_date")}
              value={profile.first_language_test_date ?? ""}
              onChange={(v) => set("first_language_test_date", v || null)}
            />

            <ToggleField
              label="I have a second official language result"
              value={secondLanguageOn}
              onChange={(on) => {
                setSecondLanguageOn(on);
                set("second_language", on ? (profile.second_language ?? evenLanguage(7)) : null);
              }}
            />
            {secondLanguageOn && (
              <div className="mg-reveal">
                <LanguageGrid
                  title="Second official language"
                  abilities={LANGUAGE_ABILITIES}
                  levels={CLB_LEVELS}
                  value={secondLanguage}
                  onChange={(v) => set("second_language", v)}
                />
                <ToggleField
                  label="That second language is French"
                  hint="NCLC 7+ across all four abilities unlocks the additional French bonus"
                  value={profile.second_language_is_french}
                  onChange={(v) => set("second_language_is_french", v)}
                  worth="+25–50"
                />
              </div>
            )}
          </Fieldset>

          {/* ---------------------------------------------------------- C · work */}
          <Fieldset
            code="C"
            title="WORK EXPERIENCE"
            hint="Full-time skilled work, or the part-time equivalent. Both feed skill transferability, where each factor-group is capped at 50."
          >
            <SelectField
              label="Canadian work experience"
              value={profile.canadian_work_years}
              options={YEAR_OPTIONS}
              onChange={(v) => set("canadian_work_years", v)}
            />
            <SelectField
              label="Foreign work experience"
              value={profile.foreign_work_years}
              options={YEAR_OPTIONS}
              onChange={(v) => set("foreign_work_years", v)}
            />
            <ToggleField
              label="Certificate of qualification in a trade"
              hint="issued by a Canadian province, territory or federal body"
              value={profile.has_certificate_of_qualification}
              onChange={(v) => set("has_certificate_of_qualification", v)}
            />
          </Fieldset>

          {/* ---------------------------------------------------------- D · spouse */}
          {hasPartner && (
            <Fieldset
              code="D"
              title="SPOUSE OR PARTNER"
              hint="Your partner is only scored if they come with you and are not already a citizen or permanent resident — and when they are, your own core grid caps lower, at 460."
            >
              <ToggleField
                label="My partner is coming with me"
                value={profile.spouse_accompanying}
                onChange={(v) => set("spouse_accompanying", v)}
              />
              <ToggleField
                label="My partner is already a Canadian citizen or permanent resident"
                value={profile.spouse_is_pr_or_citizen}
                onChange={(v) => set("spouse_is_pr_or_citizen", v)}
              />
              {scoresSpouse && (
                <div className="mg-reveal">
                  <SelectField<EducationLevel>
                    label="Partner’s highest credential"
                    error={visible("spouse_education")}
                    value={profile.spouse_education ?? "secondary"}
                    options={EDUCATION_SELECT}
                    onChange={(v) => set("spouse_education", v)}
                  />
                  <LanguageGrid
                    title="Partner’s first official language"
                    abilities={LANGUAGE_ABILITIES}
                    levels={CLB_LEVELS}
                    value={spouseLanguage}
                    onChange={(v) => set("spouse_first_language", v)}
                  />
                  <SelectField
                    label="Partner’s Canadian work experience"
                    value={profile.spouse_canadian_work_years}
                    options={YEAR_OPTIONS}
                    onChange={(v) => set("spouse_canadian_work_years", v)}
                  />
                </div>
              )}
            </Fieldset>
          )}

          {/* ---------------------------------------------------------- E · additional */}
          <Fieldset
            code={hasPartner ? "E" : "D"}
            title="ADDITIONAL FACTORS"
            hint="The levers. A provincial nomination alone is worth more than every other additional factor combined; the category is capped at 600."
          >
            <ToggleField
              label="I hold a provincial nomination"
              value={profile.has_provincial_nomination}
              onChange={(v) => set("has_provincial_nomination", v)}
              worth="+600"
            />
            <ToggleField
              label="I have a sibling in Canada (citizen or PR)"
              value={profile.has_sibling_in_canada}
              onChange={(v) => set("has_sibling_in_canada", v)}
              worth="+15"
            />
            <SelectField
              label="Canadian post-secondary study"
              hint="a credential earned in Canada"
              value={profile.canadian_post_secondary_years}
              options={STUDY_OPTIONS}
              onChange={(v) => set("canadian_post_secondary_years", v)}
            />
          </Fieldset>

          {/* ---------------------------------------------------------- submit */}
          {serverError && (
            <div className="mg-server-error" role="alert">
              <strong>The engine refused this profile.</strong> {serverError}
            </div>
          )}

          <div className="mg-actions">
            <button type="submit" className="mg-submit" disabled={loading}>
              {loading ? "COMPUTING…" : submitLabel}
            </button>
            <button type="button" className="mg-secondary" onClick={resetAll} disabled={loading}>
              RESET TO DEMO PROFILE
            </button>
            <span className="mg-actions-note">
              <Cite>computed by the Python CRS engine · canada.ca/crs-criteria</Cite>
            </span>
          </div>
        </form>
      </div>
    </div>
  );
}
