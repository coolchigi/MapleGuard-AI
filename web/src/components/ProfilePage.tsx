"use client";

/**
 * PROFILE: the inputs, laid out as a two-column ruled form, and the SAVED SCENARIOS — the what-if
 * levers. Every scenario number is computed by the Python engine (POST /position on a mutated
 * profile), never hardcoded and never scored in the browser. "Me — today" is the current profile;
 * the levers (retake language, add French, secure a nomination) are the moves that actually shift a
 * CRS, each shown with the delta the engine returns and whether it clears the benchmark draw.
 *
 * Determinism below the model, unchanged: this component builds candidate profiles and asks the
 * engine to score them. It computes no CRS itself.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";

import type { EducationLevel, MaritalStatus, Profile, Province } from "@/data/types";
import { fetchPosition } from "@/lib/api";
import {
  EDUCATION_OPTIONS,
  MARITAL_OPTIONS,
  PROVINCE_OPTIONS,
  ageOn,
  evenLanguage,
  testExpiryOf,
  toRequestProfile,
} from "@/lib/profile";

const CLB_ALL = [4, 5, 6, 7, 8, 9, 10];
const YEARS = [0, 1, 2, 3, 4, 5];

/** A compact pill control: the label on the left, a bordered mono control on the right, on a
 *  hairline row — the ruled-form language of the comp. */
function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="prof-fld">
      <span className="prof-lbl">
        {label}
        {hint ? <span className="prof-lbl-hint">{hint}</span> : null}
      </span>
      {children}
    </div>
  );
}

function Sel<T extends string | number>({ value, options, onChange }: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  const numeric = typeof value === "number";
  return (
    <select
      className="prof-ctl"
      value={String(value)}
      onChange={(e) => onChange((numeric ? Number(e.target.value) : e.target.value) as T)}
    >
      {options.map((o) => (
        <option key={String(o.value)} value={String(o.value)}>{o.label}</option>
      ))}
    </select>
  );
}

const YESNO = [{ value: "no", label: "no" }, { value: "yes", label: "yes" }];

type Scenario = {
  key: string;
  title: string;
  sub: string;
  total: number | null;
  delta: number | null;
  clears: boolean;
  active?: boolean;
};

/** The what-if levers, as profile mutations. Each is scored by the engine; we never guess a total. */
function buildLevers(profile: Profile): { key: string; title: string; sub: string; mutate: (p: Profile) => Profile }[] {
  const levers: { key: string; title: string; sub: string; mutate: (p: Profile) => Profile }[] = [];
  const minClb = Math.min(
    profile.first_language.speaking, profile.first_language.listening,
    profile.first_language.reading, profile.first_language.writing,
  );
  if (minClb < 10) {
    levers.push({
      key: "clb10", title: "Retake language → CLB 10", sub: "one test sitting",
      mutate: (p) => ({ ...p, first_language: evenLanguage(10) }),
    });
  }
  if (!profile.second_language) {
    levers.push({
      key: "french", title: "Add French → NCLC 7", sub: "opens the French draws",
      mutate: (p) => ({ ...p, second_language: evenLanguage(7), second_language_is_french: true }),
    });
  }
  if (!profile.has_provincial_nomination) {
    levers.push({
      key: "pnp", title: "Provincial nomination", sub: "your province's PNP",
      mutate: (p) => ({ ...p, has_provincial_nomination: true }),
    });
  }
  return levers;
}

export function ProfilePage({ initialProfile, onSubmit, loading, serverError, watched, benchmarkCutoff, benchmarkName }: {
  initialProfile: Profile;
  onSubmit: (p: Profile) => void;
  loading: boolean;
  serverError: string | null;
  watched: boolean;
  benchmarkCutoff: number | null;
  benchmarkName: string | null;
}) {
  const [profile, setProfile] = useState<Profile>(initialProfile);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenState, setScenState] = useState<"idle" | "loading" | "error">("idle");
  const [saved, setSaved] = useState<Scenario[]>([]);

  const set = <K extends keyof Profile>(key: K, value: Profile[K]) =>
    setProfile((p) => ({ ...p, [key]: value }));

  const age = ageOn(profile.date_of_birth);
  const expiry = testExpiryOf(profile);
  const minClb = Math.min(
    profile.first_language.speaking, profile.first_language.listening,
    profile.first_language.reading, profile.first_language.writing,
  );
  const frenchClb = profile.second_language
    ? Math.min(profile.second_language.speaking, profile.second_language.listening,
      profile.second_language.reading, profile.second_language.writing)
    : 0;

  const shortName = (benchmarkName ?? "the last draw").replace("Canadian Experience Class", "CEC");

  // Score the base profile and every lever through the engine, in parallel. This is the standout:
  // the numbers on these cards are the engine's, computed on real mutated profiles.
  const compute = useCallback(async (p: Profile) => {
    setScenState("loading");
    const levers = buildLevers(p);
    try {
      const base = await fetchPosition(toRequestProfile(p));
      const leverTotals = await Promise.all(
        levers.map((l) => fetchPosition(toRequestProfile(l.mutate(p))).then((r) => r.total)),
      );
      const rows: Scenario[] = [
        {
          key: "me", title: "Me — today", sub: "your current profile",
          total: base.total, delta: null, clears: benchmarkCutoff != null && base.total >= benchmarkCutoff,
          active: true,
        },
        ...levers.map((l, i) => ({
          key: l.key, title: l.title, sub: l.sub,
          total: leverTotals[i], delta: leverTotals[i] - base.total,
          clears: benchmarkCutoff != null && base.total < benchmarkCutoff && leverTotals[i] >= benchmarkCutoff,
        })),
      ];
      setScenarios(rows);
      setScenState("idle");
    } catch {
      setScenState("error");
    }
  }, [benchmarkCutoff]);

  // Compute once on mount for the profile we opened with. Deliberately not on every keystroke —
  // scenarios recompute on RECOMPUTE, so a half-typed field does not fire a burst of requests.
  const didInit = useRef(false);
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    void compute(initialProfile);
  }, [compute, initialProfile]);

  const recompute = () => {
    onSubmit(profile);
    void compute(profile);
  };

  const saveScenario = () => {
    const me = scenarios.find((s) => s.key === "me");
    setSaved((prev) => [
      ...prev,
      {
        key: `saved-${Date.now()}`,
        title: `Saved · ${PROVINCE_OPTIONS.find((o) => o.value === profile.province)?.label ?? ""} ${age ?? ""}`,
        sub: "a snapshot you saved",
        total: me?.total ?? null, delta: null,
        clears: me?.clears ?? false,
      },
    ]);
  };

  return (
    <div className="sheet">
      <div className="sheet-inner">
        <h1 className="prof-title">Your profile</h1>
        <p className="prof-lede">
          Everything here is an input to IRCC&rsquo;s published grids. Edit any field and recompute,
          and MapleGuard rescores on the server. Nothing is scored in your browser.
        </p>

        <div className="prof-grid">
          <div>
            <div className="prof-kick">LOCATION &amp; STATUS</div>
            <Row label="Province you are settling in">
              <Sel<Province> value={profile.province} options={PROVINCE_OPTIONS} onChange={(v) => set("province", v)} />
            </Row>
            <Row label="Marital status">
              <Sel<MaritalStatus> value={profile.marital_status} options={MARITAL_OPTIONS} onChange={(v) => set("marital_status", v)} />
            </Row>

            <div className="prof-kick prof-kick-mt">AGE &amp; EDUCATION</div>
            <Row label="Date of birth" hint={age !== null ? `age ${age}` : undefined}>
              <input className="prof-ctl" type="date" value={profile.date_of_birth}
                onChange={(e) => set("date_of_birth", e.target.value)} />
            </Row>
            <Row label="Highest credential">
              <Sel<EducationLevel> value={profile.education} options={EDUCATION_OPTIONS} onChange={(v) => set("education", v)} />
            </Row>

            <div className="prof-kick prof-kick-mt">WORK &amp; OCCUPATION</div>
            <Row label="Canadian work">
              <Sel<number> value={profile.canadian_work_years} options={YEARS.map((n) => ({ value: n, label: n === 5 ? "5+ years" : `${n} year${n === 1 ? "" : "s"}` }))} onChange={(v) => set("canadian_work_years", v)} />
            </Row>
            <Row label="Foreign work">
              <Sel<number> value={profile.foreign_work_years} options={YEARS.map((n) => ({ value: n, label: n === 5 ? "5+ years" : `${n} year${n === 1 ? "" : "s"}` }))} onChange={(v) => set("foreign_work_years", v)} />
            </Row>
            <Row label="NOC 2021 code" hint="unlocks category checks">
              <input className="prof-ctl" type="text" placeholder="21231" value={profile.noc_code ?? ""}
                onChange={(e) => set("noc_code", e.target.value || null)} />
            </Row>
          </div>

          <div>
            <div className="prof-kick">LANGUAGE</div>
            <Row label="First official language">
              <Sel<number> value={minClb} options={CLB_ALL.map((n) => ({ value: n, label: `CLB ${n} (all)` }))} onChange={(v) => set("first_language", evenLanguage(v))} />
            </Row>
            <Row label="Test taken" hint={expiry ? `lapses ${expiry}` : undefined}>
              <input className="prof-ctl" type="date" value={profile.first_language_test_date ?? ""}
                onChange={(e) => set("first_language_test_date", e.target.value || null)} />
            </Row>
            <Row label="Second language (French)">
              <Sel<number>
                value={frenchClb}
                options={[{ value: 0, label: "none" }, ...[7, 8, 9, 10].map((n) => ({ value: n, label: `NCLC ${n} (all)` }))]}
                onChange={(v) => {
                  if (v === 0) { set("second_language", null); set("second_language_is_french", false); }
                  else { set("second_language", evenLanguage(v)); set("second_language_is_french", true); }
                }}
              />
            </Row>

            <div className="prof-kick prof-kick-mt">ADDITIONAL</div>
            <Row label="Provincial nomination">
              <Sel<string> value={profile.has_provincial_nomination ? "yes" : "no"} options={YESNO} onChange={(v) => set("has_provincial_nomination", v === "yes")} />
            </Row>
            <Row label="Sibling in Canada">
              <Sel<string> value={profile.has_sibling_in_canada ? "yes" : "no"} options={YESNO} onChange={(v) => set("has_sibling_in_canada", v === "yes")} />
            </Row>
            <Row label="Studied in Canada">
              <Sel<number>
                value={profile.canadian_post_secondary_years}
                options={[{ value: 0, label: "none" }, { value: 2, label: "1-2 years" }, { value: 3, label: "3+ years" }]}
                onChange={(v) => set("canadian_post_secondary_years", v)}
              />
            </Row>

            {serverError && <div className="mg-server-error" role="alert" style={{ marginTop: 18 }}>{serverError}</div>}

            <div className="prof-actions">
              <button className="dash-btn" onClick={recompute} disabled={loading}>
                {loading ? "COMPUTING…" : watched ? "RECOMPUTE & KEEP WATCHING" : "COMPUTE & WATCH"}
              </button>
              <button className="prof-btn-ghost" onClick={saveScenario} disabled={scenState !== "idle"}>
                SAVE AS SCENARIO
              </button>
            </div>
          </div>
        </div>

        <div className="prof-scen">
          <div className="dash-feed-head">
            <span className="dash-kick">SAVED SCENARIOS</span>
            <span className="dash-feed-note">what-ifs, each scored by the engine · load onto the dashboard</span>
          </div>

          {scenState === "error" ? (
            <p className="mg-watch-empty" style={{ marginTop: 14 }}>
              Scenarios need the scoring server. It is not reachable right now, so no what-if totals
              are shown (never a guessed number).
            </p>
          ) : (
            <div className="prof-scen-grid">
              {scenState === "loading" && scenarios.length === 0 ? (
                <div className="prof-scen-card"><div className="prof-scen-title">Scoring…</div></div>
              ) : (
                [...scenarios, ...saved].map((s) => (
                  <div className="prof-scen-card" data-active={s.active} key={s.key}>
                    <div>
                      <div className="prof-scen-title">{s.title}</div>
                      <div className="prof-scen-sub">{s.sub}</div>
                    </div>
                    <div className="prof-scen-num">
                      <div className="prof-scen-total tabnum" data-up={s.delta != null && s.delta > 0}>
                        {s.total ?? "—"}
                      </div>
                      <div className="prof-scen-tag">
                        {s.active && benchmarkCutoff != null && s.total != null
                          ? `${shortName} ${s.total - benchmarkCutoff >= 0 ? "+" : ""}${s.total - benchmarkCutoff}`
                          : s.clears
                            ? `clears ${shortName}`
                            : s.delta != null
                              ? `+${s.delta}`
                              : ""}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
