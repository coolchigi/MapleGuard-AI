import React from "react";
import type { Category, DashboardData, Lever, LineItem } from "@/data/types";
import { Cite, Guilloche, Masthead, MrzStrip, Stamp } from "./atoms";

function CategoryHeader({ cat }: { cat: Category }) {
  const zero = cat.subtotal === 0;
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "baseline",
      borderBottom: "2px solid var(--ink)", paddingBottom: 6,
    }}>
      <span style={{ fontSize: 12, fontWeight: 800, letterSpacing: "0.12em", color: "var(--maple)" }}>
        {cat.code} · {cat.label}{" "}
        <span style={{ color: "var(--muted-3)", fontWeight: 600 }}>
          / IRCC caps this category at {cat.cap}
        </span>
      </span>
      <span className="tabnum" style={{ fontSize: 24, fontWeight: 800, color: zero ? "var(--muted-3)" : "var(--ink)" }}>
        {cat.subtotal}
      </span>
    </div>
  );
}

function Row({ item }: { item: LineItem }) {
  return (
    <div className="gc" style={{
      display: "flex", justifyContent: "space-between", alignItems: "baseline",
      padding: "10px 0", fontFamily: "var(--serif)", fontSize: 16,
      color: item.muted ? "var(--muted-2)" : "var(--ink)",
    }}>
      <span>
        {item.label}{" "}
        {item.meta && (
          <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--muted-2)" }}>{item.meta}</span>
        )}
      </span>
      <span className="tabnum" style={{ fontFamily: "var(--sans)", fontWeight: 700 }}>{item.points}</span>
    </div>
  );
}

function LeverGrid({ levers }: { levers: Lever[] }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "0 40px", color: "var(--muted-2)" }}>
      {levers.map((lv, i) => (
        <div key={i} className="gc" style={{ display: "flex", justifyContent: "space-between", padding: "9px 0", fontFamily: "var(--serif)", fontSize: 15 }}>
          <span>{lv.label}</span>
          <span style={{ fontFamily: "var(--mono)" }}>{lv.points}</span>
        </div>
      ))}
    </div>
  );
}

function CategoryNote({ cat }: { cat: Category }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8, gap: 16 }}>
      <span style={{ fontFamily: "var(--serif)", fontStyle: "italic", fontSize: 14, color: "var(--muted)" }}>
        {cat.note}
      </span>
      <Cite>{cat.cite}</Cite>
    </div>
  );
}

/** One category block. The server decides which categories exist (a spouse block appears only
 *  when the partner is actually scored) and whether each carries scored line items, the levers
 *  still available, or — for a partly-claimed Additional category — both. */
function CategoryBlock({ cat, last }: { cat: Category; last?: boolean }) {
  return (
    <div style={{ marginBottom: last ? 6 : 24 }}>
      <CategoryHeader cat={cat} />
      {cat.items && <div>{cat.items.map((it, i) => <Row key={i} item={it} />)}</div>}
      {cat.levers && <LeverGrid levers={cat.levers} />}
      <CategoryNote cat={cat} />
    </div>
  );
}

export function PositionPanel({ data }: { data: DashboardData }) {
  const { position, lastDraw } = data;

  const spouseMrz = position.spouse ? `SPOUSE<${position.spouse}<` : "";
  const mrz1 = `P<CAN<CRS<${position.total}<<CORE<${position.core}<${spouseMrz}TRANSFER<${position.skillTransfer}<ADD<${String(position.additional).padStart(3, "0")}<<<<`;
  const expiry = data.trajectory.testExpiry;
  const expiryMrz = expiry ? `TEST<EXP<${expiry.slice(2).replace(/-/g, "")}<<` : "TEST<EXP<NONE<<";
  const mrz2 = `GEN<${lastDraw.score}<DELTA<${Math.abs(lastDraw.delta)}<<${expiryMrz}NOT<ADJUDICATED<<`;

  return (
    <div className="sheet">
      <div className="sheet-inner">
        <Masthead label={`Assessment · ${data.asOfHuman}`} />

        {/* hero */}
        <div className="hero">
          <Guilloche />
          <div className="hero-num tabnum">{position.total}</div>
          <div className="hero-copy" style={{ paddingBottom: 18 }}>
            <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.16em", color: "var(--muted)" }}>
              COMPREHENSIVE RANKING SYSTEM · /1200
            </div>
            <p style={{ fontFamily: "var(--serif)", fontSize: 25, lineHeight: 1.26, margin: "12px 0 10px", maxWidth: 360 }}>
              {lastDraw.delta === 0 ? (
                <>Exactly level with the last general draw of{" "}</>
              ) : (
                <>
                  {Math.abs(lastDraw.delta)} points{" "}
                  {lastDraw.delta > 0 ? "above" : "below"} the last general draw of{" "}
                </>
              )}
              <span style={{ color: "var(--maple)", fontWeight: 500 }}>{lastDraw.score}</span>.
            </p>
            <Cite>canada.ca/rounds-of-invitations · {lastDraw.date}</Cite>
          </div>
          <Stamp />
        </div>

        <div style={{ height: 1, background: "var(--ink)", margin: "26px 0 0" }} />
        <p style={{ fontFamily: "var(--serif)", fontStyle: "italic", fontSize: 18, lineHeight: 1.4, color: "var(--ink-body)", margin: "22px 0", maxWidth: 640 }}>
          “Every figure below is computed from the published grids and cited to source. We do not assert
          eligibility — that determination is{" "}
          <span style={{ fontStyle: "normal", fontWeight: 700, color: "var(--ink)" }}>IRCC’s</span>.”
        </p>

        <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.14em", color: "var(--muted)", margin: "30px 0 16px" }}>
          HOW THIS NUMBER IS BUILT
        </div>

        {position.categories.map((cat, i) => (
          <CategoryBlock key={cat.code} cat={cat} last={i === position.categories.length - 1} />
        ))}

        <MrzStrip
          line1={mrz1}
          line2={mrz2}
          caption="Computed from the published IRCC grids and cited to source. Not a determination of eligibility."
        />
      </div>
    </div>
  );
}
