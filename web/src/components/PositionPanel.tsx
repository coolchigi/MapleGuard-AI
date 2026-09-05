import React from "react";
import type { Category, DashboardData, Lever, LineItem, RecentDraw } from "@/data/types";
import { Cite, Guilloche, Masthead, MrzStrip, Stamp } from "./atoms";

/** The other recent draws, so a specialty round the applicant is not in reads as secondary
 *  rather than as the headline. `relevant` is true / false / null (null = not derivable from the
 *  profile, e.g. an occupation category with no NOC on file). */
function OtherDraws({ draws }: { draws: RecentDraw[] }) {
  const tag = (r: boolean | null) =>
    r === true
      ? { label: "RELEVANT TO YOU", color: "var(--maple)" }
      : r === false
        ? { label: "NOT YOUR CATEGORY", color: "var(--muted-3)" }
        : { label: "NEEDS YOUR NOC", color: "var(--muted-3)" };
  return (
    <div style={{ margin: "30px 0 0" }}>
      <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.14em", color: "var(--muted)", marginBottom: 10 }}>
        OTHER RECENT DRAWS · WHAT’S RELEVANT TO YOU
      </div>
      {draws.map((d) => {
        const t = tag(d.relevant);
        const muted = d.relevant !== true;
        return (
          <div
            key={`${d.round}-${d.date}`}
            className="gc"
            style={{
              display: "grid", gridTemplateColumns: "1fr auto", gap: "2px 16px",
              alignItems: "baseline", padding: "9px 0",
              color: muted ? "var(--muted-2)" : "var(--ink)",
            }}
          >
            <span style={{ fontFamily: "var(--serif)", fontSize: 15 }}>
              {d.sourceUrl ? (
                <a href={d.sourceUrl} target="_blank" rel="noopener noreferrer"
                   style={{ color: "inherit", textDecoration: "none" }}>
                  {d.name}
                </a>
              ) : d.name}
              {d.round ? <span style={{ color: "var(--muted-2)" }}> · round {d.round}</span> : null}
            </span>
            <span className="tabnum" style={{ fontFamily: "var(--sans)", fontWeight: 700, textAlign: "right" }}>
              {d.score}
            </span>
            <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.08em", color: t.color }}>
              {t.label}
            </span>
            <span style={{ fontFamily: "var(--serif)", fontStyle: "italic", fontSize: 12, color: "var(--muted-2)", textAlign: "right" }}>
              {d.reason}
            </span>
          </div>
        );
      })}
    </div>
  );
}

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
  const drawMrz = lastDraw.available && lastDraw.score !== null
    ? `DRAW<${lastDraw.score}<DELTA<${Math.abs(lastDraw.delta ?? 0)}`
    : `DRAW<NONE<DELTA<NA`;
  const mrz2 = `${drawMrz}<<${expiryMrz}NOT<ADJUDICATED<<`;

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
            {lastDraw.available && lastDraw.score !== null ? (
              <>
                <p style={{ fontFamily: "var(--serif)", fontSize: 25, lineHeight: 1.26, margin: "12px 0 10px", maxWidth: 360 }}>
                  {lastDraw.delta === 0 ? (
                    <>Exactly level with the last draw of{" "}</>
                  ) : (
                    <>
                      {Math.abs(lastDraw.delta ?? 0)} points{" "}
                      {(lastDraw.delta ?? 0) > 0 ? "above" : "below"} the last draw of{" "}
                    </>
                  )}
                  <span style={{ color: "var(--maple)", fontWeight: 500 }}>{lastDraw.score}</span>
                  {lastDraw.name ? (
                    <span style={{ color: "var(--muted)" }}>
                      {" "}({lastDraw.name}{lastDraw.round ? `, round ${lastDraw.round}` : ""})
                    </span>
                  ) : null}
                  .
                </p>
                <Cite>
                  {lastDraw.sourceUrl ? (
                    <a href={lastDraw.sourceUrl} target="_blank" rel="noopener noreferrer" style={{ color: "inherit" }}>
                      canada.ca/rounds-of-invitations · {lastDraw.date}
                    </a>
                  ) : (
                    <>canada.ca/rounds-of-invitations · {lastDraw.date}</>
                  )}
                </Cite>
                {lastDraw.relevance === "matched" && lastDraw.matchReason ? (
                  <p style={{ fontSize: 11, color: "var(--muted)", margin: "8px 0 0", maxWidth: 360, lineHeight: 1.5 }}>
                    The draw relevant to your profile: {lastDraw.matchReason}.
                  </p>
                ) : lastDraw.relevance === "reference" ? (
                  <p style={{ fontSize: 11, color: "var(--muted)", margin: "8px 0 0", maxWidth: 360, lineHeight: 1.5 }}>
                    No recent draw matches your profile; shown for comparison.
                  </p>
                ) : null}
                {lastDraw.general ? (
                  <p style={{ fontSize: 11, color: "var(--muted)", margin: "8px 0 0", maxWidth: 360, lineHeight: 1.5 }}>
                    No all-program (general) draw since round {lastDraw.general.round} on{" "}
                    {lastDraw.general.date} (cutoff {lastDraw.general.score}); draws are now category-based.{" "}
                    {lastDraw.general.sourceUrl ? (
                      <a href={lastDraw.general.sourceUrl} target="_blank" rel="noopener noreferrer" style={{ color: "var(--maple)" }}>
                        source
                      </a>
                    ) : null}
                  </p>
                ) : null}
              </>
            ) : (
              <>
                <p style={{ fontFamily: "var(--serif)", fontSize: 20, lineHeight: 1.3, margin: "12px 0 10px", maxWidth: 360, color: "var(--muted)" }}>
                  No current draw benchmark available (live rounds feed unreachable).
                </p>
                <Cite>canada.ca/rounds-of-invitations</Cite>
              </>
            )}
          </div>
          <Stamp />
        </div>

        <div style={{ height: 1, background: "var(--ink)", margin: "26px 0 0" }} />
        <p style={{ fontFamily: "var(--serif)", fontStyle: "italic", fontSize: 18, lineHeight: 1.4, color: "var(--ink-body)", margin: "22px 0", maxWidth: 640 }}>
          “Every figure below is computed from the published grids and cited to source. We do not assert
          eligibility — that determination is{" "}
          <span style={{ fontStyle: "normal", fontWeight: 700, color: "var(--ink)" }}>IRCC’s</span>.”
        </p>

        {lastDraw.others && lastDraw.others.length > 0 ? (
          <OtherDraws draws={lastDraw.others} />
        ) : null}

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
