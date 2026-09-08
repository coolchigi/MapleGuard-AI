import React from "react";
import type { PathwayStanding, PathwaysData } from "@/data/types";
import { Cite, Guilloche, Masthead, MrzStrip, Stamp } from "./atoms";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function human(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

/** One pathway's cited standing. `eligible` drives the accent: matched (maple), not (muted),
 *  unknown (muted, "needs your NOC"). Every claim carries its source. */
function PathwayRow({ p }: { p: PathwayStanding }) {
  const accent = p.eligible === true ? "var(--maple)" : "var(--muted-3)";
  const move = p.closing_moves.find((m) => m.closes_gap) ?? p.closing_moves[0];
  return (
    <div className="gc" style={{ padding: "13px 0" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: "0 16px", alignItems: "baseline" }}>
        <span style={{ fontFamily: "var(--serif)", fontSize: 17, color: p.eligible === true ? "var(--ink)" : "var(--muted)" }}>
          {p.title}
        </span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.08em", color: accent, whiteSpace: "nowrap" }}>
          {p.score_kind === "SIRS" ? "SIRS" : "CRS"}
        </span>
      </div>

      <div style={{ fontFamily: "var(--serif)", fontStyle: "italic", fontSize: 14, color: "var(--muted)", margin: "4px 0 0", maxWidth: 620 }}>
        {p.eligibility_reason}
        {p.additional_requirements ? (
          <span style={{ color: "var(--muted-3)" }}> IRCC {p.additional_requirements} (not checked here).</span>
        ) : null}
      </div>

      {/* standing against this pathway's latest cited draw */}
      {p.latest_cutoff !== null ? (
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: "4px 14px", margin: "7px 0 0", fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink)" }}>
          <span className="tabnum">your {p.score_kind} {p.your_score ?? "—"}</span>
          <span style={{ color: "var(--muted-3)" }}>vs</span>
          <span className="tabnum">last cutoff {p.latest_cutoff}</span>
          {p.latest_draw_date ? <span style={{ color: "var(--muted-2)" }}>({human(p.latest_draw_date)})</span> : null}
          {p.eligible === true ? (
            p.clears ? (
              <span style={{ color: "var(--maple)", fontWeight: 600 }}>· clears now</span>
            ) : (
              <span style={{ color: "var(--maple)" }}>· {p.gap} short</span>
            )
          ) : null}
        </div>
      ) : null}

      {/* cheapest single move that closes the gap, only ever shown for a pathway you are in */}
      {p.eligible === true && !p.clears && move ? (
        <div style={{ fontFamily: "var(--serif)", fontSize: 14, color: "var(--ink-body)", margin: "5px 0 0" }}>
          Closest move: <span style={{ fontWeight: 600 }}>{move.move}</span>{" "}
          <span style={{ color: "var(--muted-2)" }}>({move.effort}) → {move.new_score}{move.closes_gap ? ", clears" : ""}</span>
        </div>
      ) : null}

      {p.source_url ? (
        <div style={{ marginTop: 6 }}>
          <Cite>
            <a href={p.source_url} target="_blank" rel="noopener noreferrer" style={{ color: "inherit" }}>
              {p.source_url.replace(/^https?:\/\/(www\.)?/, "").slice(0, 46)} · {p.source_date}
            </a>
          </Cite>
        </div>
      ) : null}
    </div>
  );
}

function Group({ title, subtitle, rows }: { title: string; subtitle: string; rows: PathwayStanding[] }) {
  if (rows.length === 0) return null;
  return (
    <div style={{ marginBottom: 26 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", borderBottom: "2px solid var(--ink)", paddingBottom: 6 }}>
        <span style={{ fontSize: 12, fontWeight: 800, letterSpacing: "0.12em", color: "var(--maple)" }}>{title}</span>
        <span style={{ fontFamily: "var(--serif)", fontStyle: "italic", fontSize: 13, color: "var(--muted)" }}>{subtitle}</span>
      </div>
      {rows.map((p) => <PathwayRow key={p.slug} p={p} />)}
    </div>
  );
}

export function PathwaysPanel({ data }: { data: PathwaysData }) {
  const qualify = data.pathways.filter((p) => p.eligible === true);
  const check = data.pathways.filter((p) => p.eligible === null);
  const notEligible = data.pathways.filter((p) => p.eligible === false);
  const qualTitles = qualify.map((p) => p.title);

  const mrz1 = `P<CAN<PATHWAYS<QUAL<${qualify.length}<OF<${data.pathways.length}<<CRS<${data.crs_total}<<`;
  const mrz2 = `COVERAGE<FEDERAL<+<BC<PNP<<OTHER<PROVINCES<NOT<MODELLED<<NOT<ADJUDICATED<<`;

  return (
    <div className="sheet">
      <div className="sheet-inner">
        <Masthead label={`Pathways · ${human(data.as_of)}`} />

        {/* hero */}
        <div className="hero">
          <Guilloche />
          <div className="hero-num tabnum">{qualify.length}</div>
          <div className="hero-copy" style={{ paddingBottom: 18 }}>
            <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.16em", color: "var(--muted)" }}>
              PATHWAYS YOU QUALIFY FOR · OF {data.pathways.length}
            </div>
            <p style={{ fontFamily: "var(--serif)", fontSize: 23, lineHeight: 1.28, margin: "12px 0 10px", maxWidth: 400 }}>
              {qualTitles.length > 0 ? (
                <>You currently meet the entry test for{" "}
                  <span style={{ color: "var(--maple)", fontWeight: 500 }}>{qualTitles.join(", ")}</span>.{" "}
                  {check.length > 0 ? `${check.length} more turn on once you add your NOC.` : ""}</>
              ) : (
                <>No pathway’s entry test is met on this profile yet. Each one below shows the cited reason and the nearest move.</>
              )}
            </p>
            <Cite>canada.ca/express-entry · narrow category test, not a PR-eligibility ruling</Cite>
          </div>
          <Stamp />
        </div>

        <div style={{ height: 1, background: "var(--ink)", margin: "26px 0 0" }} />
        <p style={{ fontFamily: "var(--serif)", fontStyle: "italic", fontSize: 18, lineHeight: 1.4, color: "var(--ink-body)", margin: "22px 0", maxWidth: 660 }}>
          “Each verdict is the narrow official entry test, computed from the published lists and cited
          to source. It is not a determination of eligibility for permanent residence — that stays{" "}
          <span style={{ fontStyle: "normal", fontWeight: 700, color: "var(--ink)" }}>IRCC’s</span>.”
        </p>

        {/* coverage honesty */}
        <div style={{ display: "flex", gap: 12, alignItems: "flex-start", margin: "0 0 26px", padding: "12px 16px", border: "1px solid var(--hair)", borderRadius: 6, background: "var(--paper)" }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: 1 }}>
            <circle cx="12" cy="12" r="9" /><path d="M12 8h.01M11 12h1v4h1" />
          </svg>
          <span style={{ fontFamily: "var(--serif)", fontSize: 14, color: "var(--muted)", lineHeight: 1.45 }}>
            Coverage is the <strong style={{ color: "var(--ink)" }}>federal general pool</strong>, the{" "}
            <strong style={{ color: "var(--ink)" }}>2026 category-based selections</strong>, and{" "}
            <strong style={{ color: "var(--ink)" }}>BC PNP</strong>. Ontario OINP and other provincial programs
            are <strong style={{ color: "var(--ink)" }}>not yet modelled</strong> — their absence here is not a “no”.
          </span>
        </div>

        <Group
          title="YOU QUALIFY NOW"
          subtitle="entry test met · where you stand against the latest draw"
          rows={qualify}
        />
        <Group
          title="ADD YOUR NOC TO CHECK"
          subtitle="occupation categories decided by your 2021 NOC code"
          rows={check}
        />
        <Group
          title="NOT A MATCH YET"
          subtitle="the entry test is not met on this profile"
          rows={notEligible}
        />

        <MrzStrip
          line1={mrz1}
          line2={mrz2}
          caption="Each pathway's entry test computed from the published lists and cited to source. Coverage is federal + BC PNP. Not a determination of eligibility."
        />
      </div>
    </div>
  );
}
