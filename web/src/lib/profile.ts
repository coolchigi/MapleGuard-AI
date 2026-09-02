/**
 * Profile defaults, the option lists the form renders, and the small derivations the UI needs.
 *
 * The option *values* here are the Python `Literal` members from `crs/models.py` — they travel
 * to the server verbatim, so they are not free text. The option *labels* are UI copy and match
 * `EDUCATION_LABELS` in `server/api/dashboard.py` so the form and the scored breakdown name the
 * same credential the same way.
 */
import type {
  EducationLevel,
  LanguageAbility,
  LanguageScores,
  MaritalStatus,
  Profile,
} from "@/data/types";

export const EDUCATION_OPTIONS: { value: EducationLevel; label: string }[] = [
  { value: "none-or-less-than-secondary", label: "Less than secondary school" },
  { value: "secondary", label: "Secondary school (high school)" },
  { value: "one-year-post-secondary", label: "One-year post-secondary credential" },
  { value: "two-year-post-secondary", label: "Two-year post-secondary credential" },
  { value: "bachelors-or-three-year", label: "Bachelor’s degree (or 4-year post-secondary program)" },
  { value: "two-or-more-certificates", label: "Two or more credentials (one 3+ years)" },
  { value: "masters-or-professional", label: "Master’s or professional degree" },
  { value: "doctoral", label: "Doctoral degree (PhD)" },
];

export const MARITAL_OPTIONS: { value: MaritalStatus; label: string }[] = [
  { value: "single", label: "Single" },
  { value: "married", label: "Married" },
  { value: "common-law", label: "Common-law" },
  { value: "divorced", label: "Divorced" },
  { value: "separated", label: "Separated" },
  { value: "widowed", label: "Widowed" },
];

export const LANGUAGE_ABILITIES: { key: LanguageAbility; label: string; short: string }[] = [
  { key: "speaking", label: "Speaking", short: "SPK" },
  { key: "listening", label: "Listening", short: "LSN" },
  { key: "reading", label: "Reading", short: "RDG" },
  { key: "writing", label: "Writing", short: "WRT" },
];

/** CLB 0–10. The grids award nothing below CLB 4 and stop rising at CLB 10, so 10 is the top of
 *  the scale for scoring purposes even though real tests go higher. */
export const CLB_LEVELS = [0, 4, 5, 6, 7, 8, 9, 10] as const;

export const WORK_YEAR_OPTIONS = [0, 1, 2, 3, 4, 5] as const;
export const STUDY_YEAR_OPTIONS = [0, 1, 2, 3] as const;

export function evenLanguage(clb: number): LanguageScores {
  return { speaking: clb, listening: clb, reading: clb, writing: clb };
}

/**
 * The starting profile: the same candidate `web/scripts/precompute.py` bakes into `demo.json`.
 * Opening the form on the profile the fallback document describes means the first render is
 * coherent whether or not the server is up — the numbers on screen always belong to the inputs
 * beside them.
 */
export const DEFAULT_PROFILE: Profile = {
  education: "bachelors-or-three-year",
  first_language: evenLanguage(9),
  date_of_birth: "1994-11-03",
  marital_status: "single",

  spouse_accompanying: false,
  spouse_is_pr_or_citizen: false,
  spouse_education: null,
  spouse_first_language: null,
  spouse_canadian_work_years: 0,

  second_language: null,
  second_language_is_french: false,
  first_language_test_date: "2025-03-01",

  canadian_work_years: 2,
  foreign_work_years: 3,
  canadian_post_secondary_years: 0,

  has_certificate_of_qualification: false,
  has_provincial_nomination: false,
  has_sibling_in_canada: false,
};

/** Mirrors `Profile.scored_with_spouse()` in crs/models.py — the condition under which the
 *  spouse block is scored at all, and therefore whether the form should ask for spouse detail. */
export function spouseIsScored(profile: Profile): boolean {
  if (profile.marital_status !== "married" && profile.marital_status !== "common-law") {
    return false;
  }
  return profile.spouse_accompanying && !profile.spouse_is_pr_or_citizen;
}

export function ageOn(dateOfBirth: string, asOf: Date = new Date()): number | null {
  const parts = dateOfBirth.split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) return null;
  const [y, m, d] = parts;
  let age = asOf.getFullYear() - y;
  if (asOf.getMonth() + 1 < m || (asOf.getMonth() + 1 === m && asOf.getDate() < d)) age -= 1;
  return age;
}

/** Language results are valid two years; this is what the time machine's expiry cliff is built
 *  from. Returns null when no test date is on the profile. */
export function testExpiryOf(profile: Profile): string | null {
  const taken = profile.first_language_test_date;
  if (!taken) return null;
  const parts = taken.split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) return null;
  const [y, m, d] = parts;
  return `${y + 2}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

/**
 * Client-side validation, run before the request leaves the browser.
 *
 * This is a courtesy, not the gate: `agent/serde.py` is the authority and refuses a malformed
 * profile with a 422 regardless of what happens here. The point is to name the bad field inline
 * instead of showing a server error for something the form could see itself.
 */
export type ProfileErrors = Partial<Record<keyof Profile, string>>;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function validateProfile(profile: Profile): ProfileErrors {
  const errors: ProfileErrors = {};

  if (!ISO_DATE.test(profile.date_of_birth)) {
    errors.date_of_birth = "Enter a date of birth (the trajectory runs the grids over dates).";
  } else {
    const age = ageOn(profile.date_of_birth);
    if (age === null || age < 16 || age > 100) {
      errors.date_of_birth = "That date of birth gives an age outside 16–100.";
    }
  }

  if (profile.first_language_test_date && !ISO_DATE.test(profile.first_language_test_date)) {
    errors.first_language_test_date = "Use a YYYY-MM-DD date, or leave it blank.";
  }

  const first = profile.first_language;
  if (LANGUAGE_ABILITIES.every(({ key }) => first[key] === 0)) {
    errors.first_language = "A first-language result is required to score anything.";
  }

  if (spouseIsScored(profile) && !profile.spouse_education) {
    errors.spouse_education = "Choose your partner’s highest credential.";
  }

  return errors;
}

/**
 * Normalise the form's working state into exactly what the backend expects.
 *
 * The form keeps some fields populated while their toggle is off (so unticking and re-ticking a
 * box does not lose what was typed). This strips those back out, so an off toggle sends `null`
 * and never scores. Anything sent here is what gets scored — that is why this is one function
 * and not scattered across the submit handler.
 */
export function toRequestProfile(profile: Profile): Profile {
  const scoresSpouse = spouseIsScored(profile);
  const hasSecond =
    profile.second_language !== null &&
    LANGUAGE_ABILITIES.some(({ key }) => profile.second_language![key] > 0);

  return {
    ...profile,
    second_language: hasSecond ? profile.second_language : null,
    second_language_is_french: hasSecond ? profile.second_language_is_french : false,
    first_language_test_date: profile.first_language_test_date || null,
    spouse_education: scoresSpouse ? profile.spouse_education : null,
    spouse_first_language: scoresSpouse ? profile.spouse_first_language : null,
    spouse_canadian_work_years: scoresSpouse ? profile.spouse_canadian_work_years : 0,
  };
}
