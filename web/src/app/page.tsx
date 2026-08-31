"use client";

/**
 * The dashboard shell: three tabs over one document.
 *
 * PROFILE collects the inputs, POSITION and TIME MACHINE render what the Python engine returned
 * for them. All three read the same `useDashboard` state, so the panels can never disagree with
 * each other — they are two views of a single response, not two independent fetches.
 *
 * On a successful compute the view moves to POSITION: the user asked a question by submitting,
 * and the answer is on another tab, so leaving them on the form would hide the result. A failure
 * keeps them on the form, where the reason is.
 */
import React, { useCallback, useState } from "react";

import { PositionPanel } from "@/components/PositionPanel";
import { ProfileForm } from "@/components/ProfileForm";
import { SourceBar } from "@/components/SourceBar";
import { TimeMachine } from "@/components/TimeMachine";
import type { Profile } from "@/data/types";
import { useDashboard } from "@/hooks/useDashboard";
import { DEFAULT_PROFILE } from "@/lib/profile";

type Tab = "profile" | "position" | "time";

const TABS: { id: Tab; label: string }[] = [
  { id: "profile", label: "PROFILE" },
  { id: "position", label: "POSITION" },
  { id: "time", label: "TIME MACHINE" },
];

export default function Page() {
  const [tab, setTab] = useState<Tab>("profile");
  const [profile, setProfile] = useState<Profile>(DEFAULT_PROFILE);
  const { data, source, loading, error, compute, reset } = useDashboard();

  const submit = useCallback(
    async (submitted: Profile) => {
      setProfile(submitted);
      const ok = await compute(submitted);
      if (ok) setTab("position");
    },
    [compute],
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
      {tab === "time" && <TimeMachine data={data} />}
    </main>
  );
}
