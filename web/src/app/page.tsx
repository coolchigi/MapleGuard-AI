"use client";

/**
 * The dashboard shell: PROFILE collects the inputs; POSITION and TIME MACHINE render the
 * `/dashboard` document the Python engine returned; PATHWAYS renders the `/pathways` document
 * (what the candidate qualifies for). One submit computes both, for the same profile, so the tabs
 * can never disagree about who is on screen.
 *
 * On a successful compute the view moves to POSITION: the user asked a question by submitting, and
 * the answer is on another tab, so leaving them on the form would hide the result. A failure keeps
 * them on the form, where the reason is.
 */
import React, { useCallback, useState } from "react";

import { AlertsPanel } from "@/components/AlertsPanel";
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

type Tab = "profile" | "position" | "pathways" | "time" | "alerts";

const TABS: { id: Tab; label: string }[] = [
  { id: "profile", label: "PROFILE" },
  { id: "position", label: "POSITION" },
  { id: "pathways", label: "PATHWAYS" },
  { id: "time", label: "TIME MACHINE" },
  { id: "alerts", label: "ALERTS" },
];

export default function Page() {
  const [tab, setTab] = useState<Tab>("profile");
  const [profile, setProfile] = useState<Profile>(DEFAULT_PROFILE);
  const { data, source, loading, error, compute, reset, computedFor } = useDashboard();
  const pathways = usePathways();
  const watchCase = useWatchCase();

  const submit = useCallback(
    async (submitted: Profile) => {
      setProfile(submitted);
      // Both documents describe the same candidate. Compute them together and wait for both, so the
      // screen advances only once each one's outcome (live vs fell-back) is known.
      const [ok] = await Promise.all([compute(submitted), pathways.compute(submitted)]);
      if (ok) setTab("position");
    },
    [compute, pathways],
  );

  // A rejected profile is the form's problem to show; an unreachable server is the whole app's,
  // so it stays in the source bar on every tab.
  const rejection = error && !error.isFallbackAppropriate ? error.message : null;

  // Consistency guard (do not remove in the dashboard revamp): POSITION and PATHWAYS come from two
  // independent requests, each of which falls back to its OWN demo document on failure. If only one
  // went live we would render live numbers beside demo numbers, two different candidates on screen,
  // which is the one thing this app must never do. So show live ONLY when BOTH are live; otherwise
  // render both from their demo documents (built from the same profile, so they agree) and label
  // the source bar honestly.
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

  return (
    <main className="stage">
      <nav className="tabs">
        <span className="tab-brand">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--maple)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3c1.6 3 1 5 3 6.5C17.3 11.2 19 12 19 15a7 7 0 0 1-14 0c0-3 1.7-3.8 4-5.5C11 8 10.4 6 12 3Z" />
          </svg>
          MAPLEGUARD
        </span>
        {TABS.map((t) => (
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

      {tab === "profile" && (
        <ProfileForm
          initialProfile={profile}
          onSubmit={submit}
          onReset={reset}
          loading={loading}
          serverError={rejection}
        />
      )}
      {tab === "position" && <PositionPanel data={positionData} />}
      {tab === "pathways" && <PathwaysPanel data={pathwaysData} />}
      {tab === "time" && <TimeMachine data={positionData} />}
      {tab === "alerts" && (
        <AlertsPanel
          profileId={watchCase.profileId}
          watched={watchCase.watched}
          saving={watchCase.saving}
          saveError={watchCase.saveError}
          alerts={watchCase.alerts}
          alertsLoading={watchCase.alertsLoading}
          alertsError={watchCase.alertsError}
          onWatch={() => void watchCase.watch(profile)}
          onRefresh={() => void watchCase.refreshAlerts()}
          canWatch={computedFor !== null}
        />
      )}
    </main>
  );
}
