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
    category?: string | null;
    sourceUrl?: string | null;
    /** How the headline draw relates to this profile: "matched" (a draw relevant to the
     *  applicant), "reference" (no recent draw matched, shown for comparison), or null on the
     *  override path. */
    relevance?: "matched" | "reference" | null;
    /** Cited reason the headline draw is (or is not) relevant to this profile. */
    matchReason?: string | null;
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
    /** The other recent draws, each flagged for relevance to this profile so specialty rounds
     *  the applicant is not in read as secondary rather than as the headline. */
    others?: RecentDraw[];
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

/** One recent draw in the hero's comparison list. `relevant` is true/false/null (null =
 *  eligibility not derivable from the profile, e.g. an occupation category with no NOC on file). */
export type RecentDraw = {
  score: number;
  date: string;
  name: string;
  round: string;
  kind: string | null;
  category: string | null;
  sourceUrl?: string | null;
  relevant: boolean | null;
  reason: string;
};

/** The bundled `demo.json` is a `DashboardData`; the alias keeps the older name working. */
export type DemoData = DashboardData;

// ----------------------------------------------------------- pathways (POST /pathways)
/** A single lever that would close a pathway's gap, cheapest first. */
export type ClosingMove = {
  move: string;
  effort: string;
  new_score: number;
  closes_gap: boolean;
};

/** One pathway's cited verdict for the candidate, plus their standing against its latest draw.
 *  `eligible` is the NARROW official test: true (in-category / meets the language rule), false
 *  (not in the published list / below NCLC 7), or null (cannot decide without more input, e.g. an
 *  occupation category with no NOC on file). It is never a claim of overall PR eligibility. */
export type PathwayStanding = {
  slug: string;
  title: string;
  rule_kind: "language" | "noc_list" | "general" | "pnp" | string;
  eligible: boolean | null;
  eligibility_reason: string;
  source_url: string;
  source_date: string;
  additional_requirements: string;
  score_kind: "CRS" | "SIRS" | string;
  your_score: number | null;
  latest_cutoff: number | null;
  latest_draw_date: string | null;
  latest_draw_source: string | null;
  clears: boolean | null;
  gap: number | null;
  closing_moves: ClosingMove[];
  note: string;
};

/** The `POST /pathways` response: every pathway's standing for one candidate, plus the shortlist
 *  they qualify for. Coverage is the federal general pool, the 2026 category selections, and BC
 *  PNP only. Other provincial programs (Ontario OINP, etc.) are NOT modelled yet. */
export type PathwaysData = {
  as_of: string;
  crs_total: number;
  qualifying: string[];
  pathways: PathwayStanding[];
};

// ----------------------------------------------------------- alerts (GET /profiles/{id}/alerts)
// Shapes verified against the real monitor payload (agent/monitor.py Alert.to_dict + _impact),
// not guessed: new_draws carry `cutoff` (not `score`) and their source in `provenance`, and each
// `impact` row is the deterministic standing against that draw (your_score vs cutoff, gap, moves).

/** A raw cited draw the monitor saw as new. */
export type AlertDraw = {
  kind: string;
  name: string;
  cutoff: number;
  date: string;
  source?: string | null;
  category?: string | null;
  provenance?: { source_url?: string | null; round_number?: string | null; round_url?: string | null } | null;
};

/** How one new draw affects this candidate: the pathway, their standing, and the cheapest move. */
export type AlertImpact = {
  draw: string;
  round_number?: string | null;
  category?: string | null;
  eligible: boolean | null;
  eligibility_reason?: string;
  your_score?: number | null;
  cutoff?: number | null;
  clears?: boolean | null;
  gap?: number | null;
  closing_moves?: ClosingMove[];
};

/** One cited notification the autonomous monitor recorded for a profile. */
export type Alert = {
  profile_id: string;
  as_of: string;
  kind: "draw" | "deadline" | "policy" | string;
  event_id: string;
  summary: string;
  new_draws: AlertDraw[];
  impact: AlertImpact[];
  reachable_alternatives: Record<string, unknown>[];
  deadlines: { age_cliffs?: unknown[]; test_expiry?: string | null; test_expiry_cliff?: unknown } | null;
  citations: string[];
  crs?: Record<string, unknown> | null;
  letter_gaps?: { duty: string; status: string }[] | null;
  policy_change?: { summary?: string; source_url?: string } | null;
};

/** The `GET /profiles/{id}/alerts` response is an object, not a bare array. */
export type AlertsFeed = {
  profile_id: string;
  alerts: Alert[];
};

// ----------------------------------------------------------- consultant brief (POST /brief)
// Every number and citation below is a deterministic-core result copied unchanged into the brief
// (see server/api/brief.py::assemble_brief). Only `prose` is model-written, and it is screened for
// an eligibility verdict before inclusion — so it is a plain string, possibly empty.

/** One cited draw from `GET /draws`, ready to rank next moves against. */
export type DrawRecord = {
  kind: string;
  name: string;
  cutoff: number;
  date: string;
  source?: string | null;
  category?: string | null;
  round_number?: string | null;
  invitations?: number | null;
  provenance?: Record<string, unknown> | null;
};

/** The `GET /draws` response: usable cited draws plus records refused for a manual check. */
export type DrawsFeed = {
  draws: DrawRecord[];
  needs_manual_check: Record<string, unknown>[];
};

/** A dated cliff in the brief's deadlines block (serde `_cliff_to_dict`). */
export type BriefCliff = { date: string; kind: string; label: string; delta: number };

/** One ranked next move with its date, the candidate's standing, and the cheapest levers. */
export type BriefMove = {
  draw: string | null;
  date: string | null;
  kind: string | null;
  cutoff: number | null;
  your_score: number | null;
  clears: boolean | null;
  gap: number | null;
  closing_moves: ClosingMove[];
  source: string | null;
  bucket: string;
};

/** The reference-letter audit block (server `AuditReport.to_dict`). */
export type BriefLetterAudit = {
  noc_code: string;
  needs_verification: boolean;
  verification_note: string;
  elements: { name: string; status: string; evidence: string }[];
  duties: {
    lead_statement_covered: boolean;
    coverage: number;
    threshold: number;
    passed: boolean;
    covered: number;
    required: number;
    gaps: { noc_code: string; version: string; source: string; text: string }[];
  };
};

/** The corrected-letter draft (server `draft_corrected_letter`). */
export type BriefCorrection = {
  letter_text: string;
  placeholders: string[];
  has_open_gaps: boolean;
};

/** The `POST /brief` response: the consultant brief, every number/citation from the core. */
export type BriefData = {
  as_of: string | null;
  profile_summary: Record<string, unknown> & { crs_total?: number };
  crs: {
    total: number;
    core: number;
    spouse: number;
    skill_transfer: number;
    additional: number;
    breakdown: { factor: string; points: number }[];
  };
  deadlines: {
    age_cliffs: BriefCliff[];
    test_expiry: string | null;
    test_expiry_cliff: BriefCliff | null;
  } | null;
  next_moves: BriefMove[];
  letter_audit: BriefLetterAudit | null;
  correction_draft: BriefCorrection | null;
  prose: string;
  disclaimer: string;
};
