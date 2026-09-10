"use client";

import type { Alert } from "@/data/types";
import { Masthead } from "./atoms";

function AlertCard({ alert }: { alert: Alert }) {
  const date = alert.as_of
    ? new Date(alert.as_of).toLocaleDateString("en-CA", {
        year: "numeric",
        month: "short",
        day: "numeric",
      })
    : alert.as_of;

  return (
    <div className="mg-alert-card">
      <div className="mg-alert-header">
        <span className="mg-alert-kind">{alert.kind.toUpperCase()}</span>
        <span className="mg-alert-date">{date}</span>
      </div>
      {alert.summary && <p className="mg-alert-summary">{alert.summary}</p>}
      {alert.new_draws.length > 0 && (
        <ul className="mg-alert-draws">
          {alert.new_draws.map((d, i) => (
            <li key={i}>
              {d.name ?? "draw"}{d.score != null ? ` — cutoff ${d.score}` : ""}
              {d.date ? ` (${d.date})` : ""}
              {d.source_url && (
                <>
                  {" · "}
                  <a href={d.source_url} target="_blank" rel="noopener noreferrer" className="mg-cite-link">
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
