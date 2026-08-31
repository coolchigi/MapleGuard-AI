"use client";

/**
 * Says, at all times, where the numbers on screen came from.
 *
 * This is not decoration. The app has three possible provenances — the bundled demo document, a
 * live engine response for the profile you entered, and the bundled document standing in for an
 * unreachable server — and two of them are *not your numbers*. A dashboard that shows a CRS of
 * 496 without saying which of those it is would be lying by omission, so the state is always on
 * screen and the fallback case is stated in words, not implied by a colour.
 */
import React from "react";

import type { ApiError } from "@/lib/api";
import { API_BASE_URL } from "@/lib/api";
import type { DashboardSource } from "@/hooks/useDashboard";

export function SourceBar({
  source,
  loading,
  error,
  asOfHuman,
  onRetry,
}: {
  source: DashboardSource;
  loading: boolean;
  error: ApiError | null;
  asOfHuman: string;
  onRetry?: () => void;
}) {
  if (loading) {
    return (
      <div className="mg-sourcebar" data-tone="busy">
        <Dot />
        <span className="mg-sourcebar-text">
          Computing on the Python engine at <code>{API_BASE_URL}</code>…
        </span>
      </div>
    );
  }

  // A rejected profile: the server is up and said no. Whatever is on screen is stale, and the
  // reason belongs in front of the user rather than in a console.
  if (error && !error.isFallbackAppropriate) {
    return (
      <div className="mg-sourcebar" data-tone="error">
        <Dot />
        <span className="mg-sourcebar-text">
          <strong>Not computed.</strong> The engine refused that profile: {error.message}
        </span>
      </div>
    );
  }

  if (source === "fallback") {
    return (
      <div className="mg-sourcebar" data-tone="warn">
        <Dot />
        <span className="mg-sourcebar-text">
          <strong>Showing the bundled demo profile — not yours.</strong>{" "}
          {error?.message ?? "The API is unreachable."} Start it with{" "}
          <code>cd server && uvicorn api.asgi:app --reload</code>.
        </span>
        {onRetry && (
          <button type="button" className="mg-sourcebar-action" onClick={onRetry}>
            RETRY
          </button>
        )}
      </div>
    );
  }

  if (source === "live") {
    return (
      <div className="mg-sourcebar" data-tone="live">
        <Dot />
        <span className="mg-sourcebar-text">
          Computed for your profile by the CRS engine · assessed {asOfHuman}
        </span>
      </div>
    );
  }

  return (
    <div className="mg-sourcebar" data-tone="demo">
      <Dot />
      <span className="mg-sourcebar-text">
        Demo profile, precomputed from the same engine. Fill in the{" "}
        <strong>PROFILE</strong> tab to compute your own.
      </span>
    </div>
  );
}

function Dot() {
  return <span className="mg-sourcebar-dot" aria-hidden />;
}
