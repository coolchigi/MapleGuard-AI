"use client";

import type { Alert, DashboardData } from "@/data/types";
import { Cite, Masthead } from "./atoms";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Format a YYYY-MM-DD string without going through `new Date()`, which parses it as UTC midnight
 *  and then renders a day earlier in any timezone behind UTC (the "Aug 22 -> Aug 21" bug). */
function humanDate(iso: string): string {
  const [y, m, d] = (iso ?? "").split("-").map(Number);
  if (!y || !m || !d) return iso ?? "";
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

function AlertCard({ alert }: { alert: Alert }) {
  const date = humanDate(alert.as_of);

  return (
    <div className="mg-alert-card">
      <div className="mg-alert-header">
        <span className="mg-alert-kind">{alert.kind.toUpperCase()}</span>
        <span className="mg-alert-date">{date}</span>
      </div>
      {alert.summary && <p className="mg-alert-summary">{alert.summary}</p>}
      {alert.impact.length > 0 && (
        <ul className="mg-alert-draws">
          {alert.impact.map((im, i) => (
            <li key={i}>
              <strong>{im.draw}</strong>
              {im.round_number ? ` · round ${im.round_number}` : ""}
              {im.cutoff != null ? ` — cutoff ${im.cutoff}` : ""}
              {im.your_score != null ? `, you ${im.your_score}` : ""}
              {im.clears ? " · clears" : im.gap != null ? ` · ${im.gap} short` : ""}
              {!im.clears && im.closing_moves && im.closing_moves[0] ? (
                <span className="mg-alert-move"> → closest move: {im.closing_moves[0].move} ({im.closing_moves[0].effort})</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {alert.impact.length === 0 && alert.new_draws.length > 0 && (
        <ul className="mg-alert-draws">
          {alert.new_draws.map((d, i) => (
            <li key={i}>
              <strong>{d.name}</strong>{d.cutoff != null ? ` — cutoff ${d.cutoff}` : ""}
              {d.date ? ` (${d.date})` : ""}
              {(d.provenance?.source_url ?? d.source) && (
                <>
                  {" · "}
                  <a href={d.provenance?.source_url ?? d.source ?? "#"} target="_blank" rel="noopener noreferrer" className="mg-cite-link">
                    source
                  </a>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {alert.citations.length > 0 && (
        <div className="mg-alert-citations">
          {alert.citations.map((c, i) => (
            <a key={i} href={c} target="_blank" rel="noopener noreferrer" className="mg-cite-link">
              {c}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

/** The one-line cited standing MapleGuard is watching: the CRS it computed, and where that sits
 *  against the latest benchmarked draw. Every number here is the engine's; nothing is derived in
 *  the browser. Rendered null-safe — an unavailable benchmark shows the score alone, never a
 *  guessed gap. */
function StandingStrip({ position }: { position: DashboardData }) {
  const total = position.position.total;
  const draw = position.lastDraw;
  const standing = draw.available && draw.delta != null
    ? draw.delta >= 0
      ? `clears the latest ${draw.name ?? "draw"} by ${draw.delta}`
      : `${Math.abs(draw.delta)} short of the latest ${draw.name ?? "draw"}`
    : null;
  return (
    <div className="mg-monitor-standing">
      <div className="mg-monitor-standing-num">
        <span className="mg-monitor-standing-crs tabnum">{total}</span>
        <span className="mg-monitor-standing-unit">CRS</span>
      </div>
      <div className="mg-monitor-standing-body">
        {standing ? (
          <p className="mg-monitor-standing-line">You {standing}.</p>
        ) : (
          <p className="mg-monitor-standing-line">
            No live draw to benchmark against right now.
          </p>
        )}
        <Cite>{draw.cite || `computed as of ${position.asOfHuman}`}</Cite>
      </div>
    </div>
  );
}

export function AlertsPanel({
  profileId,
  position,
  alerts,
  alertsLoading,
  alertsError,
  onRefresh,
  onEdit,
  onPrepareBrief,
}: {
  profileId: string | null;
  /** The candidate's computed position, so the monitor home leads with the standing it watches. */
  position: DashboardData;
  alerts: Alert[];
  alertsLoading: boolean;
  alertsError: string | null;
  onRefresh: () => void;
  onEdit: () => void;
  onPrepareBrief: () => void;
}) {
  return (
    <div className="sheet">
      <div className="sheet-inner">
        <Masthead label="Autonomous monitor" />

        <div className="mg-watch-active">
          <span className="mg-watch-badge">● MONITORING ACTIVE</span>
          <span className="mg-watch-id">profile {profileId}</span>
          <button className="mg-secondary" onClick={onEdit}>
            UPDATE PROFILE
          </button>
          <button className="mg-secondary" onClick={onRefresh} disabled={alertsLoading}>
            {alertsLoading ? "CHECKING…" : "REFRESH"}
          </button>
        </div>

        <StandingStrip position={position} />

        <div className="mg-actions mg-monitor-brief-cta">
          <button className="mg-submit" onClick={onPrepareBrief}>
            PREPARE CONSULTANT BRIEF
          </button>
          <span className="mg-actions-note">
            <Cite>a cited PDF for your consultant · corrected letter included</Cite>
          </span>
        </div>

        <p className="mg-form-lede mg-monitor-explainer">
          MapleGuard checks the IRCC rounds feed every 6 hours. It surfaces here only when a new
          draw or a rule change actually moves this position. No email leaves until you configure a
          destination.
        </p>

        {alertsError && <div className="mg-server-error" role="alert">{alertsError}</div>}

        {!alertsLoading && alerts.length === 0 ? (
          <p className="mg-watch-empty">
            Nothing needs your attention yet. The monitor runs every 6 hours — the next cited alert
            lands here after a draw round moves your standing.
          </p>
        ) : (
          <div className="mg-alerts-feed">
            {alerts.map((a, i) => (
              <AlertCard key={a.event_id || i} alert={a} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
