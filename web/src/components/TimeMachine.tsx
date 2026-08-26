"use client";

import React, { useCallback, useMemo, useRef, useState } from "react";
import type { Cliff, DemoData } from "@/data/types";
import { Cite, Guilloche, Masthead, MrzStrip, Stamp } from "./atoms";

// --- chart geometry (viewBox units) ---------------------------------------
const VB_W = 816;
const VB_H = 300;
const X0 = 56;      // left plot edge
const X1 = 800;     // right plot edge
const Y_TOP = 50;   // y for CRS 500
const Y_BOT = 250;  // y for CRS 300 / baseline
const SPAN = X1 - X0;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parse(d: string): number {
  const [y, m, day] = d.split("-").map(Number);
  return Date.UTC(y, m - 1, day);
}
const DAY = 86400000;
function fmt(ms: number): string {
  const dt = new Date(ms);
  return `${MONTHS[dt.getUTCMonth()]} ${dt.getUTCDate()}, ${dt.getUTCFullYear()}`;
}
function yFor(crs: number): number {
  return Math.max(Y_TOP, Math.min(Y_BOT, 550 - crs));
}

export function TimeMachine({ data }: { data: DemoData }) {
  const traj = data.trajectory;
  const svgRef = useRef<SVGSVGElement>(null);
  const [dragging, setDragging] = useState(false);

  const geom = useMemo(() => {
    const t0 = parse(traj.points[0].date);
    const tEnd = parse(traj.points[traj.points.length - 1].date);
    const totalDays = Math.max(1, Math.round((tEnd - t0) / DAY));
    const xForDay = (day: number) => X0 + (day / totalDays) * SPAN;
    const pts = traj.points.map((p) => {
      const day = Math.round((parse(p.date) - t0) / DAY);
      return { ...p, day, x: xForDay(day), y: yFor(p.total) };
    });
    return { t0, totalDays, xForDay, pts };
  }, [traj]);

  // scrub position, in day-offset from today
  const [day, setDay] = useState(0);

  const todayCRS = traj.points[0].total;
  // step value: total of the last point whose day <= scrub day
  const currentCRS = useMemo(() => {
    let v = geom.pts[0].total;
    for (const p of geom.pts) if (p.day <= day) v = p.total;
    return v;
  }, [geom, day]);
  const currentMs = geom.t0 + day * DAY;
  const scrubX = geom.xForDay(day);
  const scrubY = yFor(currentCRS);
  const deltaFromToday = currentCRS - todayCRS;

  const setFromClientX = useCallback((clientX: number) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const vbx = ((clientX - rect.left) / rect.width) * VB_W;
    const frac = Math.max(0, Math.min(1, (vbx - X0) / SPAN));
    setDay(Math.round(frac * geom.totalDays));
  }, [geom.totalDays]);

  const onDown = (e: React.PointerEvent) => {
    (e.target as Element).setPointerCapture?.(e.pointerId);
    setDragging(true);
    setFromClientX(e.clientX);
  };
  const onMove = (e: React.PointerEvent) => { if (dragging) setFromClientX(e.clientX); };
  const onUp = () => setDragging(false);

  const onKey = (e: React.KeyboardEvent) => {
    const step = e.shiftKey ? 30 : 7;
    if (e.key === "ArrowLeft") { setDay((d) => Math.max(0, d - step)); e.preventDefault(); }
    if (e.key === "ArrowRight") { setDay((d) => Math.min(geom.totalDays, d + step)); e.preventDefault(); }
    if (e.key === "Home") { setDay(0); e.preventDefault(); }
    if (e.key === "End") { setDay(geom.totalDays); e.preventDefault(); }
  };

  // step path across all points
  const stepPath = useMemo(() => {
    let d = `M ${geom.pts[0].x} ${geom.pts[0].y}`;
    for (let i = 1; i < geom.pts.length; i++) {
      d += ` H ${geom.pts[i].x} V ${geom.pts[i].y}`;
    }
    return d;
  }, [geom]);

  const areaPath = `${stepPath} V ${Y_BOT} H ${geom.pts[0].x} Z`;

  const expiryCliff = traj.cliffs.find((c) => c.kind === "test_expiry");
  const expiryPt = geom.pts.find((p) => p.date === traj.testExpiry);
  const prevExpiryPt = expiryPt ? geom.pts[geom.pts.indexOf(expiryPt) - 1] : undefined;

  const activeCliffDate = useMemo(() => {
    // which cliff row is "reached" at the current scrub day
    let reached: string | null = null;
    for (const c of traj.cliffs) {
      const cday = Math.round((parse(c.date) - geom.t0) / DAY);
      if (cday <= day) reached = c.date;
    }
    return reached;
  }, [traj.cliffs, geom.t0, day]);

  const mrz1 = `P<CAN<CRS<${todayCRS}<<CLIFF<270301<LANG<EXP<DROP<${Math.abs(traj.testExpiryDelta ?? 0)}<<`;
  const mrz2 = `TRAJ<${traj.points.map((p) => p.total).join("<")}<<RETAKE<BY<270301<NOT<ADJUDICATED<<`;

  return (
    <div className="sheet">
      <div className="sheet-inner">
        <Masthead label={`Time machine · ${data.asOfHuman}`} />

        {/* hero — the number updates as you scrub */}
        <div className="hero">
          <Guilloche />
          <div>
            <div
              className="hero-num tabnum"
              style={{ color: day === 0 ? "var(--ink)" : "var(--maple)", transition: "color 0.12s" }}
            >
              {currentCRS}
            </div>
            <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--muted-2)", marginTop: 8, letterSpacing: "0.06em" }}>
              {fmt(currentMs)}
              {deltaFromToday !== 0 && (
                <span style={{ color: "var(--maple)", fontWeight: 600 }}>{"  "}{deltaFromToday} from today</span>
              )}
            </div>
          </div>
          <div className="hero-copy" style={{ paddingBottom: 18 }}>
            <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.16em", color: "var(--muted)" }}>
              CRS TRAJECTORY · TODAY → NEXT 3 YEARS
            </div>
            <p style={{ fontFamily: "var(--serif)", fontSize: 25, lineHeight: 1.26, margin: "12px 0 10px", maxWidth: 380 }}>
              Today’s number, then dated cliffs. The steepest is a{" "}
              <span style={{ color: "var(--maple)", fontWeight: 500 }}>{traj.testExpiryDelta}</span>{" "}
              the day your language test expires.
            </p>
            <Cite>canada.ca/crs-criteria · grids run forward over dates</Cite>
          </div>
          <Stamp />
        </div>

        <div style={{ height: 1, background: "var(--ink)", margin: "26px 0 0" }} />
        <p style={{ fontFamily: "var(--serif)", fontStyle: "italic", fontSize: 18, lineHeight: 1.4, color: "var(--ink-body)", margin: "22px 0", maxWidth: 660 }}>
          “Every cliff below is computed by running the published grids forward over future dates. We compute
          the fall — we do not assert eligibility, that determination is{" "}
          <span style={{ fontStyle: "normal", fontWeight: 700, color: "var(--ink)" }}>IRCC’s</span>.”
        </p>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", margin: "30px 0 6px" }}>
          <span className="kicker">THE CLIFFS AHEAD</span>
          <span style={{ fontFamily: "var(--serif)", fontStyle: "italic", fontSize: 14, color: "var(--muted)" }}>
            Drag the scrubber — the number falls at each cliff.
          </span>
        </div>

        {/* CHART */}
        <div style={{ borderTop: "2px solid var(--ink)", borderBottom: "1px solid var(--hair)", padding: "12px 0 4px" }}>
          <svg
            ref={svgRef}
            viewBox={`0 0 ${VB_W} ${VB_H}`}
            style={{ display: "block", width: "100%", height: "auto", fontFamily: "var(--mono)", touchAction: "none", cursor: dragging ? "grabbing" : "pointer" }}
            onPointerDown={onDown}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerLeave={onUp}
          >
            {/* y grid + labels */}
            <g stroke="var(--hair)" strokeWidth="1">
              <line x1={X0} y1="50" x2={X1} y2="50" />
              <line x1={X0} y1="100" x2={X1} y2="100" />
              <line x1={X0} y1="150" x2={X1} y2="150" />
              <line x1={X0} y1="200" x2={X1} y2="200" />
            </g>
            <line x1={X0} y1="250" x2={X1} y2="250" stroke="var(--ink)" strokeWidth="1.5" />
            <g fill="var(--muted-2)" fontSize="10" textAnchor="end">
              <text x="46" y="53">500</text>
              <text x="46" y="103">450</text>
              <text x="46" y="153">400</text>
              <text x="46" y="203">350</text>
              <text x="46" y="253">300</text>
            </g>
            <text x="20" y="150" fill="var(--muted-2)" fontSize="9" letterSpacing="0.14em" textAnchor="middle" transform="rotate(-90 20 150)">CRS · /1200</text>

            {/* area + step line */}
            <path d={areaPath} fill="#14110D" opacity="0.045" />
            <path d={stepPath} fill="none" stroke="var(--ink)" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />

            {/* red test-expiry drop */}
            {expiryPt && prevExpiryPt && (
              <>
                <path d={`M ${expiryPt.x} ${prevExpiryPt.y} V ${expiryPt.y - 2}`} fill="none" stroke="var(--maple)" strokeWidth="4.5" strokeLinecap="round" />
                <path d={`M ${expiryPt.x - 7} ${expiryPt.y - 12} L ${expiryPt.x} ${expiryPt.y} L ${expiryPt.x + 7} ${expiryPt.y - 12}`} fill="none" stroke="var(--maple)" strokeWidth="4.5" strokeLinecap="round" strokeLinejoin="round" />
                <text x={expiryPt.x + 22} y="150" fill="var(--maple)" fontFamily="Archivo, sans-serif" fontWeight="900" fontSize="30" letterSpacing="-0.02em">{traj.testExpiryDelta}</text>
                <text x={expiryPt.x + 22} y="166" fill="var(--maple)" fontSize="9" letterSpacing="0.1em">TEST EXPIRY</text>
              </>
            )}

            {/* cliff landing markers */}
            {geom.pts.map((p, i) => {
              if (i === 0) return null;
              const isExpiry = p.date === traj.testExpiry;
              if (isExpiry) return <circle key={i} cx={p.x} cy={p.y} r="6" fill="var(--maple)" stroke="var(--paper)" strokeWidth="2" />;
              return <circle key={i} cx={p.x} cy={p.y} r="3.5" fill="var(--ink)" />;
            })}

            {/* endpoint value tags */}
            <text x={geom.pts[0].x} y={geom.pts[0].y - 12} fill="var(--ink)" fontFamily="Archivo, sans-serif" fontWeight="800" fontSize="13" textAnchor="start">{todayCRS}</text>
            {expiryPt && (
              <text x={expiryPt.x + 10} y={expiryPt.y + 16} fill="var(--maple)" fontFamily="Archivo, sans-serif" fontWeight="800" fontSize="13" textAnchor="start">{expiryPt.total}</text>
            )}
            <text x={X1} y={geom.pts[geom.pts.length - 1].y + 15} fill="var(--ink)" fontFamily="Archivo, sans-serif" fontWeight="800" fontSize="13" textAnchor="end">{traj.endTotal}</text>

            {/* x date labels at each cliff */}
            <g fill="var(--muted-2)" fontSize="9.5" letterSpacing="0.04em" textAnchor="middle">
              <text x={geom.pts[0].x} y="270" textAnchor="start">{fmt(geom.t0).toUpperCase()}</text>
              {traj.cliffs.map((c, i) => {
                const p = geom.pts.find((pp) => pp.date === c.date);
                if (!p) return null;
                if (p.x - geom.pts[0].x < 46) return null; // avoid colliding with the start label
                const isExpiry = c.kind === "test_expiry";
                return (
                  <text key={i} x={p.x} y="270" fill={isExpiry ? "var(--maple)" : "var(--muted-2)"} fontWeight={isExpiry ? 600 : 400}>
                    {MONTHS[new Date(parse(c.date)).getUTCMonth()]} ’{String(new Date(parse(c.date)).getUTCFullYear()).slice(2)}
                  </text>
                );
              })}
            </g>

            {/* the live dot riding the step line */}
            <circle cx={scrubX} cy={scrubY} r="5" fill="var(--paper)" stroke="var(--maple)" strokeWidth="2.5" />

            {/* scrubber */}
            <line x1={scrubX} y1="28" x2={scrubX} y2="250" stroke="var(--maple)" strokeWidth="1.5" strokeDasharray="3 3" />
            <g
              tabIndex={0}
              role="slider"
              aria-label="Scrub across dates"
              aria-valuemin={0}
              aria-valuemax={geom.totalDays}
              aria-valuenow={day}
              aria-valuetext={`${fmt(currentMs)}, CRS ${currentCRS}`}
              onKeyDown={onKey}
              style={{ cursor: "grab", outline: "none" }}
            >
              <rect x={scrubX - 16} y="20" width="32" height="16" rx="8" fill="var(--maple)" />
              <path d={`M ${scrubX - 6} 24 L ${scrubX - 9} 28 L ${scrubX - 6} 32 M ${scrubX + 6} 24 L ${scrubX + 9} 28 L ${scrubX + 6} 32`} fill="none" stroke="var(--paper)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
            </g>
            {day === 0 && (
              <text x={scrubX + 24} y="32" fill="var(--maple)" fontSize="9" fontWeight="600" letterSpacing="0.12em">TODAY · DRAG TO SCRUB</text>
            )}
          </svg>
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
          <Cite>canada.ca/crs-criteria · canada.ca/rounds-of-invitations</Cite>
        </div>

        {/* CLIFFS LIST */}
        <div style={{ margin: "26px 0 6px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "128px 1fr auto auto", alignItems: "center", gap: "0 20px", borderBottom: "2px solid var(--ink)", paddingBottom: 6, fontSize: 11, fontWeight: 800, letterSpacing: "0.12em", color: "var(--muted)" }}>
            <span>DATE</span><span>EVENT</span>
            <span style={{ textAlign: "right" }}>Δ</span>
            <span style={{ textAlign: "right", paddingLeft: 14 }}>CRS</span>
          </div>
          {traj.cliffs.map((c) => (
            <CliffRow key={c.date} cliff={c} active={c.date === activeCliffDate} />
          ))}
        </div>

        {/* ACTION CALLOUT */}
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 22, padding: "16px 18px", border: "2px solid var(--maple)", borderRadius: 8 }}>
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="var(--maple)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
          </svg>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: "0.1em", color: "var(--maple)" }}>
              RETAKE BEFORE {(traj.testExpiryHuman ?? "").toUpperCase()}
            </div>
            <div style={{ fontFamily: "var(--serif)", fontSize: 15, color: "var(--ink-body)", marginTop: 2 }}>
              A fresh language result before the expiry date holds the {traj.testExpiryDelta} cliff off entirely — the single highest-leverage move on this timeline.
            </div>
          </div>
          <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--muted-2)", textAlign: "right", whiteSpace: "nowrap" }}>
            {traj.daysToExpiry} days<br />from today
          </div>
        </div>

        <MrzStrip
          line1={mrz1}
          line2={mrz2}
          caption="Simulated by running the published IRCC grids forward over dates and cited to source. Not a determination of eligibility."
        />
      </div>
    </div>
  );
}

function CliffRow({ cliff, active }: { cliff: Cliff; active: boolean }) {
  const hero = cliff.kind === "test_expiry";
  const eventText = hero
    ? "Language test expires — profile rejected in-pool. Language points and their skill-transfer fall to 0."
    : `Turns ${cliff.label.replace("age ", "")} — age-factor bracket steps down`;

  if (hero) {
    return (
      <div style={{
        display: "grid", gridTemplateColumns: "128px 1fr auto auto", alignItems: "baseline",
        gap: "0 20px", padding: "14px 12px", margin: "2px -12px", background: "var(--wash)",
        borderLeft: "3px solid var(--maple)", borderRadius: 2,
        outline: active ? "2px solid var(--maple)" : "none",
      }}>
        <span style={{ fontFamily: "var(--mono)", fontSize: 13, fontWeight: 600, color: "var(--maple)" }}>{cliff.dateHuman}</span>
        <span style={{ fontFamily: "var(--serif)", fontSize: 16, color: "var(--ink)" }}>
          Language test expires — profile <span style={{ fontWeight: 600, color: "var(--maple)" }}>rejected in-pool</span>.
          Language points and their skill-transfer fall to <span style={{ fontFamily: "var(--mono)", fontSize: 12 }}>0</span>.
        </span>
        <span style={{ fontFamily: "var(--sans)", fontWeight: 900, color: "var(--maple)", textAlign: "right", fontSize: 17 }}>{cliff.delta}</span>
        <span className="tabnum" style={{ fontFamily: "var(--sans)", fontWeight: 900, color: "var(--maple)", textAlign: "right", paddingLeft: 14, fontSize: 17 }}>{cliff.total}</span>
      </div>
    );
  }

  return (
    <div className="gc" style={{
      display: "grid", gridTemplateColumns: "128px 1fr auto auto", alignItems: "baseline",
      gap: "0 20px", padding: "12px 0",
      background: active ? "var(--wash)" : "transparent",
      boxShadow: active ? "inset 3px 0 0 var(--maple)" : "none",
    }}>
      <span style={{ fontFamily: "var(--mono)", fontSize: 13, paddingLeft: active ? 8 : 0 }}>{cliff.dateHuman}</span>
      <span style={{ fontFamily: "var(--serif)", fontSize: 16 }}>{eventText}</span>
      <span style={{ fontFamily: "var(--mono)", fontWeight: 500, color: "var(--muted)", textAlign: "right" }}>{cliff.delta}</span>
      <span className="tabnum" style={{ fontFamily: "var(--sans)", fontWeight: 800, textAlign: "right", paddingLeft: 14 }}>{cliff.total}</span>
    </div>
  );
}
