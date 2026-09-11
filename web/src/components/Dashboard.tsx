"use client";

/**
 * The DASHBOARD: the whole product on one page, in the agent's voice. It is built so the autonomous
 * monitor and the agentic read of the case are the first things on screen, before any scroll:
 *
 *   1. a black WATCHING strip — the monitor, stated as a live status line
 *   2. WHAT MAPLEGUARD FOUND — the finding, in one plain sentence beside the computed CRS
 *   3. WHAT YOU QUALIFY FOR — verdict-first cards, provincial one filtered to the user's province
 *   4. THE OFFICER'S TEST — the reference-letter audit (or a CTA to run it)
 *   5. MAPLEGUARD IS WATCHING — the cited live feed
 *
 * Every number is the engine's (passed in via DashboardData / PathwaysData / the alerts feed). This
 * component computes nothing and asserts no eligibility. Where a value is not available (no live
 * draw, no letter yet) it says so rather than inventing one.
 */
import React from "react";

import type { Alert, BriefLetterAudit, DashboardData, PathwaysData, PathwayStanding, Profile } from "@/data/types";
import { PROVINCE_OPTIONS, PROVINCE_TO_PNP_SLUG } from "@/lib/profile";
import { Cite } from "./atoms";

const HEXAGON = "M20 7 12 3 4 7v10l8 4 8-4Z";

function provinceLabel(province: Profile["province"]): string {
  return PROVINCE_OPTIONS.find((p) => p.value === province)?.label ?? "your province";
}

/** The monitor, stated as a status line. Honest: it reports the real 6-hour cadence and the most
 *  recent thing found, and never fabricates a "checked 2 minutes ago" timestamp we do not have. */
function WatchingStrip({ watched, latestAlert }: { watched: boolean; latestAlert: Alert | null }) {
  return (
    <div className="dash-watching" data-watched={watched}>
      <span className="dash-watching-dot" aria-hidden />
      {watched ? (
        <span>
          WATCHING YOUR CASE · checks the IRCC rounds feed every 6 hours
          {latestAlert ? ` · last found ${latestAlert.as_of}` : " · nothing needs you right now"}
        </span>
      ) : (
        <span>PREVIEWING A DEMO CASE · start a watch from the PROFILE tab to track your own</span>
      )}
    </div>
  );
}

/** WHAT MAPLEGUARD FOUND: the computed CRS beside a plain-English finding assembled from the live
 *  draw standing and (when present) the letter audit. No verdict on eligibility, only cited facts. */
function FoundHero({ data, letterAudit }: { data: DashboardData; letterAudit: BriefLetterAudit | null }) {
  const draw = data.lastDraw;
  const gap = draw.available && draw.delta != null && draw.delta < 0 ? Math.abs(draw.delta) : null;
  const clears = draw.available && draw.delta != null && draw.delta >= 0;
  const letterGaps = letterAudit ? letterAudit.duties.required - letterAudit.duties.covered : 0;

  return (
    <div className="dash-hero">
      <div className="dash-kick" style={{ color: "var(--maple)" }}>WHAT MAPLEGUARD FOUND</div>
      <div className="dash-hero-grid">
        <div>
          <div className="dash-hero-num tabnum">{data.position.total}</div>
          <div className="dash-hero-unit">CRS · /1200</div>
        </div>
        <div>
          <p className="dash-hero-say">
            {gap != null ? (
              <>You are <strong>{gap} points</strong> below the {draw.name ?? "latest"} cutoff</>
            ) : clears ? (
              <>You <strong>clear</strong> the latest {draw.name ?? "draw"} by {draw.delta}</>
            ) : (
              <>Your CRS is <strong>{data.position.total}</strong>, with no live draw to benchmark against right now</>
            )}
            {letterAudit && letterGaps > 0 ? (
              <>, and your reference letter has <strong>{letterGaps} {letterGaps === 1 ? "duty" : "duties"} an officer will flag</strong>. Both are fixable.</>
            ) : letterAudit ? (
              <>, and your reference letter covers every required duty. </>
            ) : (
              <>. Add your reference letter below and MapleGuard reads it the way an officer will.</>
            )}
          </p>
          <Cite>every number computed from IRCC&rsquo;s grids and cited · not adjudicated</Cite>
        </div>
      </div>
    </div>
  );
}

function QualifyCard({ icon, title, tag, children }: {
  icon: string; title: string; tag: string; children: React.ReactNode;
}) {
  return (
    <div className="dash-card">
      <div className="dash-card-head">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="var(--ink)" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          <path d={icon} />
        </svg>
        <span className="dash-card-title">{title}</span>
      </div>
      <span className="dash-tag">{tag}</span>
      <p className="dash-card-body">{children}</p>
    </div>
  );
}

/** WHAT YOU QUALIFY FOR: the federal pool and French cards (everyone), plus the ONE provincial
 *  program that matches the user's settlement province. An Ontario user sees Ontario, never all
 *  eleven — a PNP is a commitment to settle in that province, so we show only theirs. */
function QualifySection({ data, pathways, province }: {
  data: DashboardData; pathways: PathwaysData; province: Profile["province"];
}) {
  const byslug = (s: string): PathwayStanding | undefined => pathways.pathways.find((p) => p.slug === s);
  const draw = data.lastDraw;
  const french = byslug("french");
  const pnpSlug = PROVINCE_TO_PNP_SLUG[province];
  const pnp = pnpSlug ? byslug(pnpSlug) : undefined;

  const drawTag = draw.available && draw.delta != null
    ? draw.delta >= 0 ? "clears the last draw" : `${Math.abs(draw.delta)} below last draw`
    : "no live draw";

  return (
    <div className="dash-section">
      <div className="dash-kick">WHAT YOU QUALIFY FOR</div>
      <div className="dash-cards">
        <QualifyCard icon={HEXAGON} title={draw.name ?? "Express Entry pool"} tag={drawTag}>
          Last {draw.name ?? "draw"} cutoff {draw.score ?? "—"}
          {draw.round ? `, round ${draw.round}` : ""}. Raising your language to CLB 10 is the
          shortest move on your file.
        </QualifyCard>

        <QualifyCard
          icon="M4 5h7M9 3v2c0 5-3 8-6 9M5 9c0 3 3 6 7 7M14 21l4-9 4 9M15.5 18h5"
          title="French-language"
          tag={french?.clears ? "you clear it" : "door opens at NCLC 7"}
        >
          {french?.eligibility_reason
            ? french.eligibility_reason
            : "French draws cut far lower than the general pool. Reaching NCLC 7 across all four abilities opens them."}
        </QualifyCard>

        {pnp ? (
          <QualifyCard
            icon="M12 2a8 8 0 0 0-8 8c0 5.4 8 12 8 12s8-6.6 8-12a8 8 0 0 0-8-8Z M12 10 m-3 0 a3 3 0 1 0 6 0 a3 3 0 1 0 -6 0"
            title={pnp.title}
            tag={`you set province to ${provinceLabel(province)}`}
          >
            {pnp.eligibility_reason || `See which ${provinceLabel(province)} streams your profile matches and what each one needs.`}
          </QualifyCard>
        ) : (
          <QualifyCard
            icon="M12 2a8 8 0 0 0-8 8c0 5.4 8 12 8 12s8-6.6 8-12a8 8 0 0 0-8-8Z"
            title="Provincial programs"
            tag={province === "quebec" ? "Quebec is separate" : "set your province"}
          >
            {province === "quebec"
              ? "Quebec runs its own selection (a CSQ), outside Express Entry, so no PNP is shown here."
              : "Pick your settlement province on the Profile tab and MapleGuard shows the one provincial program that is yours to pursue."}
          </QualifyCard>
        )}
      </div>
    </div>
  );
}

/** THE OFFICER'S TEST: the reference-letter audit promoted to the hero. Populated only from a real
 *  audit result; with no letter yet it is an honest CTA, never a fabricated coverage number. */
function OfficerTest({ letterAudit, onDraftFix }: { letterAudit: BriefLetterAudit | null; onDraftFix: () => void }) {
  const d = letterAudit?.duties;
  const pct = d ? Math.round(d.coverage * 100) : null;
  return (
    <div className="dash-section">
      <div className="dash-officer">
        <div className="dash-officer-head">
          <span>THE OFFICER&rsquo;S TEST · YOUR REFERENCE LETTER</span>
          <span className="dash-officer-tag">WHAT NO CALCULATOR DOES</span>
        </div>
        <div className="dash-officer-body">
          <div className="dash-officer-score">
            {pct != null ? (
              <>
                <div className="dash-officer-pct tabnum">{pct}<span>%</span></div>
                <div className="dash-officer-cap">DUTY COVERAGE · NOC {letterAudit!.noc_code}</div>
                <div className="dash-officer-bar"><div style={{ width: `${pct}%` }} /></div>
              </>
            ) : (
              <>
                <div className="dash-officer-pct" style={{ color: "var(--muted-3)" }}>—</div>
                <div className="dash-officer-cap">NO LETTER READ YET</div>
              </>
            )}
          </div>
          <div>
            {letterAudit && d ? (
              <>
                <p className="dash-officer-say">
                  We read your letter the way an officer will. {d.lead_statement_covered ? "The lead statement checks out, but" : "The lead statement is not evidenced, and"}{" "}
                  <strong>{d.required - d.covered} required {d.required - d.covered === 1 ? "duty is" : "duties are"} not evidenced</strong> — each cited to the 2021 NOC text.
                </p>
                {d.gaps.slice(0, 3).map((g, i) => (
                  <div className="dash-officer-gap" key={i}>&ldquo;{g.text}&rdquo;</div>
                ))}
              </>
            ) : (
              <p className="dash-officer-say">
                Paste your employer reference letter and MapleGuard audits it against the cited NOC
                2021 duties the way an officer will, then drafts a corrected version that describes
                only supported work and leaves every gap as an explicit <span className="dash-mono">[employer to confirm]</span>.
              </p>
            )}
            <div className="dash-officer-actions">
              <button className="dash-btn" onClick={onDraftFix}>
                {letterAudit ? "DRAFT THE FIX →" : "RUN THE OFFICER'S TEST →"}
              </button>
              <Cite>gaps left as <span className="dash-mono">[employer to confirm]</span> · never invented</Cite>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** MAPLEGUARD IS WATCHING: the cited live feed. When the monitor has recorded alerts they lead;
 *  otherwise the current cited standing (the benchmarked draw and the next dated cliff) is shown as
 *  the latest read, so the feed is a real cited row rather than an empty box. */
function WatchingFeed({ data, alerts }: { data: DashboardData; alerts: Alert[] }) {
  const draw = data.lastDraw;
  const cliff = data.trajectory.cliffs.find((c) => c.kind === "test_expiry") ?? data.trajectory.cliffs[0];
  return (
    <div className="dash-section">
      <div className="dash-feed-head">
        <span className="dash-kick">MAPLEGUARD IS WATCHING</span>
        <span className="dash-feed-note">live IRCC feed · cited</span>
      </div>

      {alerts.length > 0 ? (
        alerts.slice(0, 4).map((a, i) => (
          <div className="dash-feed-row" key={a.event_id || i}>
            <span className="dash-tag dash-tag-sm">{a.kind.toUpperCase()}</span>
            <span className="dash-feed-say">{a.summary}</span>
            <span className="dash-feed-when">{a.as_of}</span>
          </div>
        ))
      ) : (
        <div className="dash-feed-row">
          <span className="dash-tag dash-tag-sm">DRAW</span>
          <span className="dash-feed-say">
            {draw.available && draw.name
              ? <>{draw.name} round {draw.round}, cutoff {draw.score} — you are {draw.delta != null && draw.delta < 0 ? `${Math.abs(draw.delta)} below` : "clear"}.</>
              : <>No live draw to benchmark against right now.</>}
            {cliff ? <> A <strong>{cliff.delta} cliff on {cliff.dateHuman}</strong> ({cliff.label}).</> : null}
          </span>
          {draw.sourceUrl ? (
            <a className="dash-feed-when" href={draw.sourceUrl} target="_blank" rel="noopener noreferrer">
              {draw.date ?? "source"}
            </a>
          ) : <span className="dash-feed-when">{draw.date ?? ""}</span>}
        </div>
      )}
    </div>
  );
}

/** The passport machine-readable-zone footer: a compact cited summary line in the visa-document
 *  motif, then the determinism disclaimer. */
function MrzFooter({ data, province }: { data: DashboardData; province: Profile["province"] }) {
  const draw = data.lastDraw;
  const gap = draw.delta != null ? Math.abs(draw.delta) : 0;
  const cliff = data.trajectory.cliffs.find((c) => c.kind === "test_expiry");
  const cliffCode = cliff ? cliff.date.replace(/-/g, "").slice(2) : "NONE";
  const prov = (province === "undecided" ? "XX" : province.slice(0, 2)).toUpperCase();
  return (
    <>
      <div className="dash-mrz">
        <span>{`P<CAN<CRS<${data.position.total}<<${(draw.category ?? "GENERAL").toUpperCase().replace(/[^A-Z]/g, "").slice(0, 3)}<${draw.score ?? 0}<GAP<${gap}<<`}</span>
        <span>{`WATCHING<${prov}<<NEXT<CLIFF<${cliffCode}<<NOT<ADJUDICATED<<`}</span>
      </div>
      <p className="dash-disclaimer">
        The model orchestrates and explains. It computes nothing and asserts no eligibility — every
        figure is from the published IRCC grids, cited to source.
      </p>
    </>
  );
}

export function Dashboard({ data, pathways, profile, watched, alerts, letterAudit, onDraftFix }: {
  data: DashboardData;
  pathways: PathwaysData;
  profile: Profile;
  watched: boolean;
  alerts: Alert[];
  letterAudit: BriefLetterAudit | null;
  onDraftFix: () => void;
}) {
  return (
    <div className="sheet">
      <WatchingStrip watched={watched} latestAlert={alerts[0] ?? null} />
      <div className="sheet-inner dash-inner">
        <FoundHero data={data} letterAudit={letterAudit} />
        <QualifySection data={data} pathways={pathways} province={profile.province} />
        <OfficerTest letterAudit={letterAudit} onDraftFix={onDraftFix} />
        <WatchingFeed data={data} alerts={alerts} />
      </div>
      <MrzFooter data={data} province={profile.province} />
    </div>
  );
}
