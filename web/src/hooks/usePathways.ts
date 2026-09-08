"use client";

/**
 * Owns the pathways document (`POST /pathways`) and how it was obtained.
 *
 * Same contract as `useDashboard`: `source` travels with the data so the panel never shows a
 * qualification map that belongs to a different profile than the one on screen. A rejected profile
 * does not fall back to the demo map (that would be a lie); only an unreachable or broken server
 * does, and the demo map is then labelled a fallback.
 *
 * Requests are superseded, not queued.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import pathwaysDemo from "@/data/pathways.demo.json";
import type { DashboardRequest, PathwaysData, Profile } from "@/data/types";
import { ApiError, fetchPathways } from "@/lib/api";
import { toRequestProfile } from "@/lib/profile";

/** The bundled offline pathways map, produced by `web/scripts/precompute.py` calling the very
 *  `eligible_pathways` function behind POST /pathways. */
export const PATHWAYS_DEMO = pathwaysDemo as unknown as PathwaysData;

export type PathwaysSource = "demo" | "live" | "fallback";

export type PathwaysState = {
  data: PathwaysData;
  source: PathwaysSource;
  loading: boolean;
  error: ApiError | null;
  computedFor: Profile | null;
};

export type UsePathways = PathwaysState & {
  compute: (profile: Profile, options?: Partial<DashboardRequest>) => Promise<boolean>;
  reset: () => void;
};

export function usePathways(): UsePathways {
  const [state, setState] = useState<PathwaysState>({
    data: PATHWAYS_DEMO,
    source: "demo",
    loading: false,
    error: null,
    computedFor: null,
  });

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
        const data = await fetchPathways(
          { ...options, profile: toRequestProfile(profile) },
          { signal: controller.signal },
        );
        if (!isCurrent()) return false;
        setState({ data, source: "live", loading: false, error: null, computedFor: profile });
        return true;
      } catch (err) {
        if (!isCurrent() || controller.signal.aborted) return false;

        const error =
          err instanceof ApiError
            ? err
            : new ApiError("offline", err instanceof Error ? err.message : String(err));

        setState((s) => {
          if (error.isFallbackAppropriate) {
            return { data: PATHWAYS_DEMO, source: "fallback", loading: false, error, computedFor: null };
          }
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
    setState({ data: PATHWAYS_DEMO, source: "demo", loading: false, error: null, computedFor: null });
  }, []);

  return { ...state, compute, reset };
}
