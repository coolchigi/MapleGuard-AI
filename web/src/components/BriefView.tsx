"use client";

/**
 * The consultant brief: the tangible thing a candidate (or a settlement worker helping one) hands
 * to an immigration consultant. It is assembled by `POST /brief` from the deterministic core, so
 * every number and citation on the page is the engine's; only the short cover note is model-written
 * and the server screens it for an eligibility verdict before returning it.
 *
 * Optionally it audits an employer reference letter against the claimed NOC occupation and includes
 * a corrected draft — the one artifact here that changes what an employer signs. The letter is
 * sent only when the user pastes one and gives its NOC code.
 *
 * "Save as PDF" is the browser's own print-to-PDF: the print stylesheet (globals.css @media print)
 * hides the app chrome and the controls, leaving just the document. No PDF library, no new backend,
 * determinism intact.
 */
import React, { useCallback, useState } from "react";

import type { BriefData, BriefLetterAudit, DrawRecord, Profile } from "@/data/types";
import { ApiError, fetchBrief, fetchDraws } from "@/lib/api";
import { toRequestProfile } from "@/lib/profile";
import { Cite } from "./atoms";

/** The current draw landscape: the latest cutoff per category (or program), newest first. The
 *  rounds feed carries the full history back to 2015; a consultant brief wants where the candidate
 *  stands against the draws that run NOW, not every historical round. This is pure deterministic
 *  input selection — the engine still computes each verdict on what it is handed. */
function currentLandscape(draws: DrawRecord[]): DrawRecord[] {
  const latest = new Map<string, DrawRecord>();
  for (const d of draws) {
    const key = (d.category && d.category.trim()) || d.name || d.kind;
    const cur = latest.get(key);
    if (!cur || (d.date ?? "") > (cur.date ?? "")) latest.set(key, d);
  }
  return [...latest.values()].sort((a, b) => (b.date ?? "").localeCompare(a.date ?? ""));
}

const SUMMARY_LABELS: Record<string, string> = {
  education: "Education",
  date_of_birth: "Date of birth",
  age: "Age",
  marital_status: "Marital status",
  canadian_work_years: "Canadian work (years)",
  foreign_work_years: "Foreign work (years)",
  has_provincial_nomination: "Provincial nomination",
  has_certificate_of_qualification: "Trade certificate",
  second_language_is_french: "French second language",
};

function fmt(value: unknown): string {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value === null || value === undefined) return "—";
  return String(value);
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="brief-section">
      <h2 className="brief-h2">{title}</h2>
      {children}
    </section>
  );
}

function LetterAuditBlock({ audit }: { audit: BriefLetterAudit }) {
  const d = audit.duties;
  return (
    <>
      <p className="brief-p">
        The letter covers <strong>{d.covered} of {d.required}</strong> required duties for NOC{" "}
        {audit.noc_code} ({Math.round(d.coverage * 100)}% against a {Math.round(d.threshold * 100)}%
        threshold). Lead statement {d.lead_statement_covered ? "covered" : "not covered"}.
      </p>
      {audit.needs_verification && (
        <p className="brief-flag">
          Reference text not line-verified against the official source. {audit.verification_note}
        </p>
      )}
      {d.gaps.length > 0 && (
        <>
          <h3 className="brief-h3">Duty gaps, each cited to the NOC</h3>
          <ul className="brief-list">
            {d.gaps.map((g, i) => (
              <li key={i}>
                {g.text}
                <span className="brief-src">
                  {" "}
                  <a href={g.source} target="_blank" rel="noopener noreferrer">
                    NOC {g.noc_code} · {g.version}
                  </a>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

function BriefDocument({ data }: { data: BriefData }) {
  const summary = data.profile_summary ?? {};
  const summaryRows = Object.keys(SUMMARY_LABELS).filter((k) => k in summary);
  const crs = data.crs;
  const cliffs = [
    ...(data.deadlines?.age_cliffs ?? []),
    ...(data.deadlines?.test_expiry_cliff ? [data.deadlines.test_expiry_cliff] : []),
  ];

  return (
    <article className="brief-doc">
      <header className="brief-head">
        <div className="brief-brand">MAPLEGUARD</div>
        <h1 className="brief-title">Consultant brief</h1>
        <p className="brief-dateline">
          Computed{data.as_of ? ` as of ${data.as_of}` : ""}. Every figure below is computed from
          the published government grids and cited to source.
        </p>
      </header>

      <Section title="Candidate summary">
        <dl className="brief-dl">
          {summaryRows.map((k) => (
            <div className="brief-dl-row" key={k}>
              <dt>{SUMMARY_LABELS[k]}</dt>
              <dd>{fmt((summary as Record<string, unknown>)[k])}</dd>
            </div>
          ))}
          <div className="brief-dl-row brief-dl-total">
            <dt>CRS total</dt>
            <dd>{crs.total}</dd>
          </div>
        </dl>
      </Section>

      <Section title="CRS position">
        <table className="brief-table">
          <tbody>
            <tr><th>Core / human capital</th><td>{crs.core}</td></tr>
            {crs.spouse > 0 && <tr><th>Spouse factors</th><td>{crs.spouse}</td></tr>}
            <tr><th>Skill transferability</th><td>{crs.skill_transfer}</td></tr>
            <tr><th>Additional</th><td>{crs.additional}</td></tr>
            <tr className="brief-table-total"><th>Total</th><td>{crs.total}</td></tr>
          </tbody>
        </table>
        <Cite>canada.ca/crs-criteria</Cite>
      </Section>

      {cliffs.length > 0 && (
        <Section title="Dated cliffs ahead">
          <ul className="brief-list">
            {cliffs.map((c, i) => (
              <li key={i}>
                <strong>{c.date}</strong> — {c.label} ({c.delta > 0 ? "+" : ""}{c.delta} CRS)
              </li>
            ))}
          </ul>
        </Section>
      )}

      {data.next_moves.length > 0 && (
        <Section title="Ranked next moves">
          <ul className="brief-list">
            {data.next_moves.map((m, i) => (
              <li key={i}>
                <strong>{m.draw}</strong>
                {m.date ? ` (${m.date})` : ""}
                {m.cutoff != null ? ` — cutoff ${m.cutoff}` : ""}
                {m.your_score != null ? `, you ${m.your_score}` : ""}
                {m.clears ? " · clears" : m.gap != null ? ` · ${m.gap} short` : ""}
                {!m.clears && m.closing_moves[0] && (
                  <span className="brief-move">
                    {" "}→ closest move: {m.closing_moves[0].move} ({m.closing_moves[0].effort})
                  </span>
                )}
                {m.source && (
                  <span className="brief-src">
                    {" "}
                    <a href={m.source} target="_blank" rel="noopener noreferrer">source</a>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {data.letter_audit && (
        <Section title="Reference letter audit">
          <LetterAuditBlock audit={data.letter_audit} />
        </Section>
      )}

      {data.correction_draft && (
        <Section title="Corrected reference letter, for the employer to review and sign">
          {data.correction_draft.has_open_gaps && (
            <p className="brief-flag">
              This draft leaves {data.correction_draft.placeholders.length} explicit gap
              {data.correction_draft.placeholders.length === 1 ? "" : "s"} for the employer to
              confirm. It describes only supported work and invents nothing.
            </p>
          )}
          <pre className="brief-letter">{data.correction_draft.letter_text}</pre>
        </Section>
      )}

      {data.prose && (
        <Section title="Cover note">
          <p className="brief-p">{data.prose}</p>
        </Section>
      )}

      <footer className="brief-foot">{data.disclaimer}</footer>
    </article>
  );
}

export function BriefView({ profile, onClose, onAudit }: {
  profile: Profile;
  onClose: () => void;
  /** Fired with the letter audit whenever a brief that read a letter lands, so the caller can
   *  surface the officer's-test result outside this view. */
  onAudit?: (audit: BriefData["letter_audit"]) => void;
}) {
  const [nocCode, setNocCode] = useState("");
  const [letterText, setLetterText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<BriefData | null>(null);

  const generate = useCallback(async () => {
    setLoading(true);
    setError(null);
    // The rounds feed ranks the next moves. It is best-effort: if it is unreachable the brief still
    // assembles (CRS, cliffs, letter), it just omits the ranked-moves block rather than failing.
    let draws: unknown[] | undefined;
    try {
      draws = currentLandscape((await fetchDraws()).draws);
    } catch {
      draws = undefined;
    }
    const hasLetter = letterText.trim().length > 0 && nocCode.trim().length > 0;
    try {
      const brief = await fetchBrief({
        profile: toRequestProfile(profile),
        draws,
        ...(hasLetter ? { noc_code: nocCode.trim(), letter_text: letterText } : {}),
      });
      setData(brief);
      if (brief.letter_audit && onAudit) onAudit(brief.letter_audit);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [profile, nocCode, letterText, onAudit]);

  return (
    <div className="sheet brief-sheet">
      <div className="sheet-inner">
        <div className="brief-controls">
          <div className="mg-actions">
            <button className="mg-secondary" onClick={onClose}>← BACK TO MONITOR</button>
            {data && (
              <button className="mg-submit" onClick={() => window.print()}>
                SAVE AS PDF
              </button>
            )}
          </div>

          <div className="mg-form-head">
            <h1 className="mg-form-title">Prepare a consultant brief.</h1>
            <p className="mg-form-lede">
              One cited document a candidate hands their immigration consultant: the CRS position,
              the dated cliffs, the ranked next moves. Paste an employer reference letter and its
              NOC code and it also audits the letter and drafts a corrected version to sign.
            </p>
          </div>

          <label className="brief-input-label" htmlFor="brief-noc">
            Claimed NOC 2021 code (optional, for the letter audit)
          </label>
          <input
            id="brief-noc"
            className="mg-input brief-noc"
            placeholder="e.g. 21234"
            value={nocCode}
            onChange={(e) => setNocCode(e.target.value)}
          />
          <label className="brief-input-label" htmlFor="brief-letter">
            Employer reference letter (optional)
          </label>
          <textarea
            id="brief-letter"
            className="mg-input brief-letter-input"
            placeholder="Paste the reference letter text to audit it against the cited NOC duties and draft a corrected version."
            value={letterText}
            onChange={(e) => setLetterText(e.target.value)}
            rows={5}
          />

          {error && <div className="mg-server-error" role="alert">{error}</div>}

          <div className="mg-actions">
            <button className="mg-submit" onClick={() => void generate()} disabled={loading}>
              {loading ? "ASSEMBLING…" : data ? "REGENERATE" : "GENERATE BRIEF"}
            </button>
          </div>
        </div>

        {data && <BriefDocument data={data} />}
      </div>
    </div>
  );
}
