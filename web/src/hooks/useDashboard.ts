"use client";

/**
 * Owns the dashboard document and how it was obtained.
 *
 * The rule this hook exists to enforce: **the panels never render numbers that belong to a
 * different profile than the one on screen.** So `source` travels with the data, and a request
 * the server *rejected* does not silently fall back to demo numbers — only an unreachable or
 * broken server does, because in that case the demo document is honestly labelled as such.
 *
 * Requests are superseded, not queued: a new submit aborts the one in flight, and a response
 * that arrives after being superseded is dropped rather than written over newer state.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import demo from "@/data/demo.json";
import type { DashboardData, DashboardRequest, Profile } from "@/data/types";
import { ApiError, fetchDashboard } from "@/lib/api";
import { toRequestProfile } from "@/lib/profile";

/** The bundled offline document. Same shape as the live response, by construction — it is
 *  produced by `web/scripts/precompute.py` calling the very function behind POST /dashboard. */
export const DEMO_DATA = demo as unknown as DashboardData;

export type DashboardSource =
  /** Never computed anything yet; showing the bundled document for the demo profile. */
  | "demo"
  /** Live from the Python API for the profile the user submitted. */
  | "live"
  /** The API was unreachable, so this is the bundled document — it is NOT the user's profile. */
  | "fallback";

export type DashboardState = {
  data: DashboardData;
  source: DashboardSource;
  loading: boolean;
  /** Set when the last attempt failed, whether or not we fell back. */
  error: ApiError | null;
  /** The profile the displayed `data` was computed for; null while showing demo/fallback. */
  computedFor: Profile | null;
};

export type UseDashboard = DashboardState & {
  /** Compute `profile` on the server. Resolves true when live data landed. */
  compute: (profile: Profile, options?: Partial<DashboardRequest>) => Promise<boolean>;
  /** Drop back to the bundled demo document and clear any error. */
  reset: () => void;
};

export function useDashboard(): UseDashboard {
  const [state, setState] = useState<DashboardState>({
    data: DEMO_DATA,
    source: "demo",
    loading: false,
    error: null,
    computedFor: null,
  });

  // Identifies the newest request. A response whose id is stale is discarded — this is what
  // stops a slow first submit from overwriting a fast second one.
  const requestId = useRef(0);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => () => inFlight.current?.abort(), []);

  const compute = useCallback(
    async (profile: Profile, options: Partial<DashboardRequest> = {}): Promise<boolean> => {
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;
      const id = ++requestId.current;
      const isCurrent = () => id === requestId.current;

      setState((s) => ({ ...s, loading: true, error: null }));

      try {
        const data = await fetchDashboard(
          { ...options, profile: toRequestProfile(profile) },
          { signal: controller.signal },
        );
        if (!isCurrent()) return false;
        setState({
          data,
          source: "live",
          loading: false,
          error: null,
          computedFor: profile,
        });
        return true;
      } catch (err) {
        if (!isCurrent() || controller.signal.aborted) return false;

        const error =
          err instanceof ApiError
            ? err
            : new ApiError("offline", err instanceof Error ? err.message : String(err));

        setState((s) => {
          if (error.isFallbackAppropriate) {
            // The server is gone. Show the bundled document, but label it a fallback so the UI
            // can say out loud that these are not the user's numbers.
            return { data: DEMO_DATA, source: "fallback", loading: false, error, computedFor: null };
          }
          // The server answered and refused this profile. Keep whatever is on screen and surface
          // the reason; swapping in demo numbers here would be a lie.
          return { ...s, loading: false, error };
        });
        return false;
      } finally {
        if (inFlight.current === controller) inFlight.current = null;
      }
    },
    [],
  );

  const reset = useCallback(() => {
    inFlight.current?.abort();
    requestId.current++;
    setState({
      data: DEMO_DATA,
      source: "demo",
      loading: false,
      error: null,
      computedFor: null,
    });
  }, []);

  return { ...state, compute, reset };
}
