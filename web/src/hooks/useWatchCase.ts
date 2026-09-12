"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { Alert, Profile } from "@/data/types";
import { ApiError, fetchAlerts, saveProfile } from "@/lib/api";
import { toRequestProfile } from "@/lib/profile";

const STORAGE_KEY = "mapleguard_profile_id";

export type UseWatchCase = {
  profileId: string | null;
  watched: boolean;
  saving: boolean;
  saveError: string | null;
  alerts: Alert[];
  alertsLoading: boolean;
  alertsError: string | null;
  watch: (profile: Profile) => Promise<void>;
  refreshAlerts: () => Promise<void>;
};

export function useWatchCase(): UseWatchCase {
  // Initialize to the server-render values (nothing watched). Reading localStorage here would make
  // the first client render disagree with the SSR HTML for any returning user (server: not watched,
  // client: watched) — a hydration mismatch. So the saved id is read in a mount effect below, after
  // hydration, and the watched state flips then.
  const [profileId, setProfileId] = useState<string | null>(null);
  const [watched, setWatched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [alertsLoading, setAlertsLoading] = useState(false);
  const [alertsError, setAlertsError] = useState<string | null>(null);

  const profileIdRef = useRef(profileId);
  useEffect(() => {
    profileIdRef.current = profileId;
  }, [profileId]);

  const refreshAlerts = useCallback(async () => {
    const id = profileIdRef.current;
    if (!id) return;
    setAlertsLoading(true);
    setAlertsError(null);
    try {
      const data = await fetchAlerts(id);
      setAlerts(data);
    } catch (err) {
      setAlertsError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setAlertsLoading(false);
    }
  }, []);

  // After hydration, restore the saved profile from localStorage and load its alerts. Running this
  // in an effect (not the initial render) is what keeps SSR and the first client render identical.
  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = localStorage.getItem(STORAGE_KEY);
    } catch {
      stored = null; // storage can throw (private mode, blocked) — degrade to not-watched
    }
    if (stored) {
      profileIdRef.current = stored;
      setProfileId(stored);
      setWatched(true);
      void refreshAlerts();
    }
  }, [refreshAlerts]); // once, after mount

  const watch = useCallback(async (profile: Profile) => {
    setSaving(true);
    setSaveError(null);
    try {
      const { id } = await saveProfile(toRequestProfile(profile), {
        id: profileIdRef.current ?? undefined,
      });
      localStorage.setItem(STORAGE_KEY, id);
      profileIdRef.current = id;
      setProfileId(id);
      setWatched(true);
      // Immediately fetch alerts for the newly saved profile.
      void refreshAlerts();
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }, [refreshAlerts]);

  return {
    profileId,
    watched,
    saving,
    saveError,
    alerts,
    alertsLoading,
    alertsError,
    watch,
    refreshAlerts,
  };
}
