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

import { PathwaysPanel } from "@/components/PathwaysPanel";
import { PositionPanel } from "@/components/PositionPanel";
import { ProfileForm } from "@/components/ProfileForm";
import { SourceBar } from "@/components/SourceBar";
import { TimeMachine } from "@/components/TimeMachine";
import type { Profile } from "@/data/types";
import { useDashboard } from "@/hooks/useDashboard";
import { usePathways } from "@/hooks/usePathways";
import { DEFAULT_PROFILE } from "@/lib/profile";

type Tab = "profile" | "position" | "pathways" | "time";

const TABS: { id: Tab; label: string }[] = [
  { id: "profile", label: "PROFILE" },
  { id: "position", label: "POSITION" },
  { id: "pathways", label: "PATHWAYS" },
  { id: "time", label: "TIME MACHINE" },
];

export default function Page() {
  const [tab, setTab] = useState<Tab>("profile");
  const [profile, setProfile] = useState<Profile>(DEFAULT_PROFILE);
  const { data, source, loading, error, compute, reset } = useDashboard();
  const pathways = usePathways();

  const submit = useCallback(
    async (submitted: Profile) => {
      setProfile(submitted);
      // Both documents describe the same candidate; compute them together so PATHWAYS is ready
      // the moment the user switches to it, and never shows a different profile than POSITION.
      void pathways.compute(submitted);
      const ok = await compute(submitted);
      if (ok) setTab("position");
    },
    [compute, pathways],
  );

  // A rejected profile is the form's problem to show; an unreachable server is the whole app's,
  // so it stays in the source bar on every tab.
  const rejection = error && !error.isFallbackAppropriate ? error.message : null;

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
          source={source}
          loading={loading}
          error={error}
          asOfHuman={data.asOfHuman}
          onRetry={() => void compute(profile)}
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
      {tab === "position" && <PositionPanel data={data} />}
      {tab === "pathways" && <PathwaysPanel data={pathways.data} />}
      {tab === "time" && <TimeMachine data={data} />}
    </main>
  );
}
