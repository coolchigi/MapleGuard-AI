"use client";

/**
 * The shell, reframed around the monitor. MapleGuard is an agent that watches a case, so the
 * MONITOR view is the front door: it carries the intake when nobody is watching yet, and becomes
 * the cited alert feed once a case is under watch. POSITION / PATHWAYS / TIME MACHINE are the
 * breakdown behind the standing — one click away, never the first thing.
 *
 * Starting a watch is one action. Submitting the intake computes the position AND saves the
 * profile into the monitored set, so "see my numbers" and "watch my case" are the same gesture.
 * The compute has to land live for the watch to save (the monitor needs the real server), so a
 * failed or offline compute keeps the intake on screen with the reason.
 *
 * The POSITION/PATHWAYS consistency guard is unchanged and load-bearing: the two views come from
 * two independent requests, and we render live numbers only when BOTH went live, else both from
 * their own demo documents. Never live numbers beside demo numbers, two candidates on one screen.
 */
import React, { useCallback, useState } from "react";

import { AlertsPanel } from "@/components/AlertsPanel";
import { BriefView } from "@/components/BriefView";
import { PathwaysPanel } from "@/components/PathwaysPanel";
import { PositionPanel } from "@/components/PositionPanel";
import { ProfileForm } from "@/components/ProfileForm";
import { SourceBar } from "@/components/SourceBar";
import { TimeMachine } from "@/components/TimeMachine";
import type { Profile } from "@/data/types";
import { DEMO_DATA, useDashboard } from "@/hooks/useDashboard";
import { PATHWAYS_DEMO, usePathways } from "@/hooks/usePathways";
import { useWatchCase } from "@/hooks/useWatchCase";
import { DEFAULT_PROFILE } from "@/lib/profile";

type Tab = "monitor" | "position" | "pathways" | "time";

// The monitor leads; the other three are the breakdown behind the standing.
const BREAKDOWN_TABS: { id: Tab; label: string }[] = [
  { id: "position", label: "POSITION" },
  { id: "pathways", label: "PATHWAYS" },
  { id: "time", label: "TIME MACHINE" },
];

export default function Page() {
  const [tab, setTab] = useState<Tab>("monitor");
  const [profile, setProfile] = useState<Profile>(DEFAULT_PROFILE);
  // On the monitor tab, a watching user sees the feed; this flips them back to the intake to amend
  // the profile they are watching (a re-save under the same id).
  const [editing, setEditing] = useState(false);
  // The consultant-brief deliverable is a full-page view (its own print stylesheet), so it replaces
  // the shell when open rather than living inside a tab.
  const [briefOpen, setBriefOpen] = useState(false);
  const { data, source, loading, error, compute, reset, computedFor } = useDashboard();
  const pathways = usePathways();
  const watchCase = useWatchCase();

  // The intake is one action: compute the position and, when that lands live, save the profile to
  // the monitor. The watch can only persist off a live compute (it hits the API), so an offline or
  // rejected compute leaves the user on the intake with the reason, not silently unwatched.
  const startWatching = useCallback(
    async (submitted: Profile) => {
      setProfile(submitted);
      const [ok] = await Promise.all([compute(submitted), pathways.compute(submitted)]);
      if (ok) {
        await watchCase.watch(submitted);
        setEditing(false);
      }
    },
    [compute, pathways, watchCase],
  );

  // A rejected profile is the intake's problem to show; an unreachable server is the whole app's,
  // so it stays in the source bar on every tab.
  const rejection = error && !error.isFallbackAppropriate ? error.message : null;

  // Consistency guard (do not remove): POSITION and PATHWAYS come from two independent requests,
  // each of which falls back to its OWN demo document on failure. If only one went live we would
  // render live numbers beside demo numbers, two different candidates on screen. So show live ONLY
  // when BOTH are live; otherwise render both from their demo documents (same profile, so they
  // agree) and label the source bar honestly.
  const jointlyLive = source === "live" && pathways.source === "live";
  const jointSource = jointlyLive
    ? "live"
    : source === "demo" && pathways.source === "demo"
      ? "demo"
      : "fallback";
  const positionData = jointlyLive ? data : DEMO_DATA;
  const pathwaysData = jointlyLive ? pathways.data : PATHWAYS_DEMO;
  const retry = () => {
    void compute(profile);
    void pathways.compute(profile);
  };

  // The monitor home shows the feed once a case is watched; otherwise (or while amending) it shows
  // the intake. A live compute is what lets the watch save, so surface why one did not.
  const showFeed = watchCase.watched && !editing;
  const intakeNotice = watchCase.saveError
    ? `Could not start the watch: ${watchCase.saveError}`
    : rejection
      ? null // the form renders the rejection itself
      : !jointlyLive && computedFor === null && (source === "fallback" || pathways.source === "fallback")
        ? "The monitor needs the live server. Your numbers below are the bundled demo profile until it is reachable."
        : null;

  return (
    <main className="stage">
      <nav className="tabs">
        <span className="tab-brand">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--maple)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3c1.6 3 1 5 3 6.5C17.3 11.2 19 12 19 15a7 7 0 0 1-14 0c0-3 1.7-3.8 4-5.5C11 8 10.4 6 12 3Z" />
          </svg>
          MAPLEGUARD
        </span>
        <button
          className="tab"
          data-active={tab === "monitor"}
          onClick={() => setTab("monitor")}
          aria-current={tab === "monitor" ? "page" : undefined}
        >
          MONITOR
        </button>
        <span className="tab-sep" aria-hidden>breakdown</span>
        {BREAKDOWN_TABS.map((t) => (
          <button
            key={t.id}
            className="tab"
            data-active={tab === t.id}
            onClick={() => setTab(t.id)}
            aria-current={tab === t.id ? "page" : undefined}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className="mg-statusrow">
        <SourceBar
          source={jointSource}
          loading={loading}
          error={error}
          asOfHuman={positionData.asOfHuman}
          onRetry={retry}
        />
      </div>

      {briefOpen ? (
        <BriefView profile={profile} onClose={() => setBriefOpen(false)} />
      ) : (
        <>
          {tab === "monitor" &&
            (showFeed ? (
              <AlertsPanel
                profileId={watchCase.profileId}
                position={positionData}
                alerts={watchCase.alerts}
                alertsLoading={watchCase.alertsLoading}
                alertsError={watchCase.alertsError}
                onRefresh={() => void watchCase.refreshAlerts()}
                onEdit={() => setEditing(true)}
                onPrepareBrief={() => setBriefOpen(true)}
              />
            ) : (
              <ProfileForm
                initialProfile={profile}
                onSubmit={startWatching}
                onReset={watchCase.watched ? () => setEditing(false) : reset}
                loading={loading || watchCase.saving}
                submitLabel={watchCase.watched ? "UPDATE & KEEP WATCHING" : "START WATCHING MY CASE"}
                masthead="Autonomous monitor"
                title="Watch my case."
                lede="MapleGuard watches your Canadian immigration case and surfaces one cited alert when a real IRCC change moves your standing. Tell it who you are once. It computes your position and starts watching in the same step."
                serverError={rejection}
                status={intakeNotice ? <span className="mg-form-notice">{intakeNotice}</span> : undefined}
              />
            ))}
          {tab === "position" && <PositionPanel data={positionData} />}
          {tab === "pathways" && <PathwaysPanel data={pathwaysData} />}
          {tab === "time" && <TimeMachine data={positionData} />}
        </>
      )}
    </main>
  );
}
