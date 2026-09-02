/**
 * The wire contract with the Python backend.
 *
 * Two halves, and they are deliberately separate:
 *
 *  - `Profile` is the *request*. Its field names are snake_case because they are the Python
 *    `crs.Profile` field names, read by `agent/serde.py::profile_from_dict`. Renaming anything
 *    here breaks deserialization silently-ish (serde raises, so it surfaces as a 422), so this
 *    interface mirrors the dataclass one-to-one on purpose.
 *
 *  - `DashboardData` is the *response* of `POST /dashboard`, and it is camelCase because the
 *    server already assembled it for rendering (see server/api/dashboard.py). The precomputed
 *    `demo.json` is the identical document for a fixed profile, which is why the offline
 *    fallback needs no separate type and no conversion.
 */

// ---------------------------------------------------------------- request side
export type EducationLevel =
  | "none-or-less-than-secondary"
  | "secondary"
  | "one-year-post-secondary"
  | "two-year-post-secondary"
  | "bachelors-or-three-year"
  | "two-or-more-certificates"
  | "masters-or-professional"
  | "doctoral";

export type MaritalStatus =
  | "single"
  | "married"
  | "common-law"
  | "divorced"
  | "widowed"
  | "separated";

/** Canadian Language Benchmark level per ability (NCLC maps onto the same scale for French). */
export type LanguageScores = {
  speaking: number;
  listening: number;
  reading: number;
  writing: number;
};

export type LanguageAbility = keyof LanguageScores;

export type Profile = {
  education: EducationLevel;
  first_language: LanguageScores;
  /** ISO `YYYY-MM-DD`. Required by /dashboard — a static age cannot be run forward over dates. */
  date_of_birth: string;
  marital_status: MaritalStatus;

  /** Only scored when the partner accompanies you AND is not already a citizen/PR. */
  spouse_accompanying: boolean;
  spouse_is_pr_or_citizen: boolean;
  spouse_education: EducationLevel | null;
  spouse_first_language: LanguageScores | null;
  spouse_canadian_work_years: number;

  second_language: LanguageScores | null;
  second_language_is_french: boolean;
  /** ISO date the first-language test was taken; results lapse two years later. */
  first_language_test_date: string | null;

  canadian_work_years: number;
  foreign_work_years: number;
  canadian_post_secondary_years: number;

  has_certificate_of_qualification: boolean;
  has_provincial_nomination: boolean;
  has_sibling_in_canada: boolean;
};

export type DashboardRequest = {
  profile: Profile;
  /** ISO date the assessment is dated to. Omitted = the server's today. */
  as_of?: string;
  horizon_years?: number;
  last_draw_score?: number;
  last_draw_date?: string;
};

// --------------------------------------------------------------- response side
export type LineItem = {
  label: string;
  meta?: string;
  points: number;
  muted?: boolean;
};

export type Lever = { label: string; points: string };

export type Category = {
  /** "A" core · "S" spouse (present only when scored) · "B" transfer · "C" additional. */
  code: string;
  label: string;
  cap: number;
  subtotal: number;
  items?: LineItem[];
  levers?: Lever[];
  note: string;
  cite: string;
};

export type TrajectoryPoint = { date: string; dateHuman: string; total: number };

export type Cliff = {
  date: string;
  dateHuman: string;
  kind: "age" | "test_expiry";
  delta: number;
  total: number;
  label: string;
};

export type DashboardData = {
  generatedBy: string;
  asOf: string;
  asOfHuman: string;
  position: {
    total: number;
    core: number;
    spouse: number;
    skillTransfer: number;
    additional: number;
    categories: Category[];
  };
  lastDraw: {
    /** False when the live rounds feed was unreachable: no benchmark is shown, none is invented. */
    available: boolean;
    /** The benchmarked round's cutoff and the candidate's gap to it. Null when unavailable. */
    score: number | null;
    delta: number | null;
    cite: string;
    date: string | null;
    /** The real round the score comes from (IRCC draws are all category-based now). */
    name?: string | null;
    round?: string | null;
    kind?: string | null;
    sourceUrl?: string | null;
    /** Set only when unavailable: why there is no benchmark. */
    note?: string;
    /** The last all-program (general) draw, shown explicitly since none has run since 2024. */
    general?: {
      score: number;
      round: string;
      date: string;
      sourceUrl?: string | null;
      note: string;
    } | null;
  };
  trajectory: {
    points: TrajectoryPoint[];
    cliffs: Cliff[];
    testExpiry: string | null;
    testExpiryHuman: string | null;
    testExpiryDelta: number | null;
    daysToExpiry: number | null;
    endTotal: number;
  };
};

/** The bundled `demo.json` is a `DashboardData`; the alias keeps the older name working. */
export type DemoData = DashboardData;
