"use client";

import type { Alert } from "@/data/types";
import { Masthead } from "./atoms";

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

export function AlertsPanel({
  profileId,
  watched,
  saving,
  saveError,
  alerts,
  alertsLoading,
  alertsError,
  onWatch,
  onRefresh,
  canWatch,
}: {
  profileId: string | null;
  watched: boolean;
  saving: boolean;
  saveError: string | null;
  alerts: Alert[];
  alertsLoading: boolean;
  alertsError: string | null;
  onWatch: () => void;
  onRefresh: () => void;
  canWatch: boolean;
}) {
  return (
    <div className="sheet">
      <div className="sheet-inner">
        <Masthead label="Autonomous monitor" />

        <div className="mg-form-head">
          <h1 className="mg-form-title">Watch my case.</h1>
          <p className="mg-form-lede">
            The monitor checks IRCC draws every 6 hours. When a new draw moves your position,
            you get a cited alert. No email leaves until you configure a destination.
          </p>
        </div>

        {!watched ? (
          <div className="mg-watch-cta">
            {!canWatch && (
              <p className="mg-watch-hint">
                Compute your position first, then save your profile to the monitor.
              </p>
            )}
            {saveError && (
              <div className="mg-server-error" role="alert">
                <strong>Could not save profile.</strong> {saveError}
              </div>
            )}
            <div className="mg-actions">
              <button
                className="mg-submit"
                onClick={onWatch}
                disabled={saving || !canWatch}
              >
                {saving ? "SAVING…" : "WATCH MY CASE"}
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="mg-watch-active">
              <span className="mg-watch-badge">MONITORING ACTIVE</span>
              <span className="mg-watch-id">profile {profileId}</span>
              <button className="mg-secondary" onClick={onRefresh} disabled={alertsLoading}>
                {alertsLoading ? "CHECKING…" : "REFRESH"}
              </button>
            </div>

            {alertsError && (
              <div className="mg-server-error" role="alert">{alertsError}</div>
            )}

            {!alertsLoading && alerts.length === 0 ? (
              <p className="mg-watch-empty">
                No alerts yet. The monitor runs every 6 hours — check back after the next IRCC
                draw round.
              </p>
            ) : (
              <div className="mg-alerts-feed">
                {alerts.map((a, i) => (
                  <AlertCard key={a.event_id || i} alert={a} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
