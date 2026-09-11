"use client";

/**
 * The shell for the three-view design: DASHBOARD (the agent's read of the case, and the front
 * door), PROFILE (the inputs + the watch), TIME MACHINE (the score over the next years). The
 * monitor is not a tab you go find — its status rides the top of the dashboard, and the agentic
 * read of the case is the whole dashboard.
 *
 * One compute serves every view. POSITION and PATHWAYS come from two independent requests; the
 * consistency guard renders live numbers only when BOTH landed live, else both from their demo
 * documents, so the screen never mixes two candidates.
 */
import React, { useCallback, useState } from "react";

import { BriefView } from "@/components/BriefView";
import { Dashboard } from "@/components/Dashboard";
import { PathwaysPanel } from "@/components/PathwaysPanel";
import { ProfileForm } from "@/components/ProfileForm";
import { TimeMachine } from "@/components/TimeMachine";
import type { BriefLetterAudit, Profile } from "@/data/types";
import { DEMO_DATA, useDashboard } from "@/hooks/useDashboard";
import { PATHWAYS_DEMO, usePathways } from "@/hooks/usePathways";
import { useWatchCase } from "@/hooks/useWatchCase";
import { DEFAULT_PROFILE } from "@/lib/profile";

type Tab = "dashboard" | "profile" | "time";

const TABS: { id: Tab; label: string }[] = [
  { id: "dashboard", label: "DASHBOARD" },
  { id: "profile", label: "PROFILE" },
  { id: "time", label: "TIME MACHINE" },
];

export default function Page() {
  const [tab, setTab] = useState<Tab>("dashboard");
  const [profile, setProfile] = useState<Profile>(DEFAULT_PROFILE);
  const [briefOpen, setBriefOpen] = useState(false);
  // The reference-letter audit, lifted out of the brief flow so the dashboard's officer's-test
  // block shows the real coverage once the letter has been read (never a fabricated number).
  const [letterAudit, setLetterAudit] = useState<BriefLetterAudit | null>(null);
  const { data, source, loading, error, compute } = useDashboard();
  const pathways = usePathways();
  const watchCase = useWatchCase();

  // Submitting the profile computes the position AND, when that lands live, starts the watch.
  const submit = useCallback(
    async (submitted: Profile) => {
      setProfile(submitted);
      const [ok] = await Promise.all([compute(submitted), pathways.compute(submitted)]);
      if (ok) await watchCase.watch(submitted);
      setTab("dashboard");
    },
    [compute, pathways, watchCase],
  );

  const rejection = error && !error.isFallbackAppropriate ? error.message : null;

  // Consistency guard: show live numbers only when BOTH requests went live; otherwise render both
  // from their own demo documents (same profile, so they agree). Never live beside demo.
  const jointlyLive = source === "live" && pathways.source === "live";
  const positionData = jointlyLive ? data : DEMO_DATA;
  const pathwaysData = jointlyLive ? pathways.data : PATHWAYS_DEMO;

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
            data-active={tab === t.id && !briefOpen}
            onClick={() => { setBriefOpen(false); setTab(t.id); }}
            aria-current={tab === t.id ? "page" : undefined}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {briefOpen ? (
        <BriefView
          profile={profile}
          onClose={() => setBriefOpen(false)}
          onAudit={setLetterAudit}
        />
      ) : (
        <>
          {tab === "dashboard" && (
            <Dashboard
              data={positionData}
              pathways={pathwaysData}
              profile={profile}
              watched={watchCase.watched}
              alerts={watchCase.alerts}
              letterAudit={letterAudit}
              onDraftFix={() => setBriefOpen(true)}
            />
          )}
          {tab === "profile" && (
            <ProfileForm
              initialProfile={profile}
              onSubmit={submit}
              loading={loading || watchCase.saving}
              submitLabel={watchCase.watched ? "RECOMPUTE & KEEP WATCHING" : "COMPUTE & WATCH MY CASE"}
              serverError={rejection}
            />
          )}
          {tab === "time" && <TimeMachine data={positionData} />}
        </>
      )}
    </main>
  );
}
