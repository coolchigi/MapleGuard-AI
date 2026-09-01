/**
 * The typed client for the Python API.
 *
 * One function matters — `fetchDashboard` — because the server composes the whole document in
 * `POST /dashboard`. The other endpoints are here for the panels that will need them, but the
 * dashboard deliberately costs a single round trip.
 *
 * Base URL comes from `NEXT_PUBLIC_API_BASE_URL` (see `.env.local.example`); it must be inlined
 * at build time, so it is read as a whole property access rather than destructured off `env`.
 */
import type { DashboardData, DashboardRequest, Profile } from "@/data/types";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000"
).replace(/\/+$/, "");

/** How long we wait before deciding the server is not there and falling back to demo data. */
export const DEFAULT_TIMEOUT_MS = 8000;

/**
 * A failed call, classified so the UI can say something true about *why*.
 *
 * `kind` drives the copy in the status bar:
 *   - "offline"  — the server never answered (down, wrong port, CORS, DNS). Fallback is right.
 *   - "timeout"  — it answered too slowly. Fallback is right.
 *   - "rejected" — it answered 4xx: the profile is wrong, not the connection. Do NOT paper over
 *                  this with demo data, or the user sees a score for a profile they didn't enter.
 *   - "server"   — 5xx.
 *   - "malformed"— 200 with a body we cannot parse as a dashboard.
 */
export type ApiErrorKind = "offline" | "timeout" | "rejected" | "server" | "malformed";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;

  constructor(kind: ApiErrorKind, message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
  }

  /** Whether serving the bundled demo document instead is honest. A rejected profile is not: the
   *  numbers would belong to a different candidate than the one on screen. */
  get isFallbackAppropriate(): boolean {
    return this.kind === "offline" || this.kind === "timeout" || this.kind === "server";
  }
}

/** FastAPI's error envelope is `{detail: ...}`; `detail` is a string for our HTTPExceptions and
 *  a list of per-field objects for pydantic validation failures. Render either as one line. */
function readDetail(body: unknown, fallback: string): string {
  if (typeof body !== "object" || body === null) return fallback;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const lines = detail
      .map((d) => {
        if (typeof d !== "object" || d === null) return null;
        const { loc, msg } = d as { loc?: unknown[]; msg?: string };
        const where = Array.isArray(loc) ? loc.filter((p) => p !== "body").join(".") : "";
        return where ? `${where}: ${msg ?? "invalid"}` : (msg ?? null);
      })
      .filter(Boolean);
    if (lines.length) return lines.join("; ");
  }
  return fallback;
}

/** Enough of a shape check that a wrong-service 200 (a proxy page, another API) is caught here
 *  rather than as a render crash three components deep. */
function isDashboardData(value: unknown): value is DashboardData {
  if (typeof value !== "object" || value === null) return false;
  const d = value as Partial<DashboardData>;
  return (
    typeof d.asOf === "string" &&
    typeof d.position?.total === "number" &&
    Array.isArray(d.position?.categories) &&
    Array.isArray(d.trajectory?.points) &&
    d.trajectory!.points.length > 0
  );
}

async function postJson<T>(
  path: string,
  body: unknown,
  { signal, timeoutMs = DEFAULT_TIMEOUT_MS }: { signal?: AbortSignal; timeoutMs?: number } = {},
): Promise<T> {
  // Two abort sources: the caller's (a superseded request) and our own timeout. Link them so
  // either one cancels the fetch, and so we can tell afterwards which one fired.
  const timer = new AbortController();
  const timeout = setTimeout(() => timer.abort(), timeoutMs);
  const onCallerAbort = () => timer.abort();
  signal?.addEventListener("abort", onCallerAbort);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: timer.signal,
      cache: "no-store",
    });
  } catch (err) {
    if (signal?.aborted) throw err; // the caller superseded this call; let it propagate
    if (timer.signal.aborted) {
      throw new ApiError("timeout", `the API did not answer within ${timeoutMs / 1000}s`);
    }
    throw new ApiError(
      "offline",
      `cannot reach the API at ${API_BASE_URL} — is the Python server running?`,
    );
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", onCallerAbort);
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = readDetail(body, response.statusText || `HTTP ${response.status}`);
    throw new ApiError(
      response.status >= 500 ? "server" : "rejected",
      detail,
      response.status,
    );
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("malformed", "the API returned a body that is not JSON");
  }
}

/**
 * The whole dashboard for one profile: position categories + time-machine trajectory.
 * Throws `ApiError`; callers decide whether to fall back (see `ApiError.isFallbackAppropriate`).
 */
export async function fetchDashboard(
  request: DashboardRequest,
  options: { signal?: AbortSignal; timeoutMs?: number } = {},
): Promise<DashboardData> {
  const data = await postJson<unknown>("/dashboard", request, options);
  if (!isDashboardData(data)) {
    throw new ApiError("malformed", "the API answered, but not with a dashboard document");
  }
  return data;
}

export type SaveProfileResponse = { id: string; monitored: boolean };

/**
 * The intake call: persist a profile into the monitored set so the autonomous monitor watches
 * it and alerts when a draw or rule moves this candidate. It takes the SAME `Profile` the form
 * already builds and `/dashboard` scores — no shape change — wrapped as `{ profile }` exactly
 * like `DashboardRequest`. Pass `id` to update an existing profile; omit it for a new one.
 * Throws `ApiError` (a rejected profile is a real 4xx, not a reason to fall back).
 */
export async function saveProfile(
  profile: Profile,
  options: {
    id?: string;
    bcOffer?: Record<string, unknown>;
    signal?: AbortSignal;
    timeoutMs?: number;
  } = {},
): Promise<SaveProfileResponse> {
  const { id, bcOffer, ...fetchOpts } = options;
  return postJson<SaveProfileResponse>(
    "/profiles",
    { profile, ...(id ? { id } : {}), ...(bcOffer ? { bc_offer: bcOffer } : {}) },
    fetchOpts,
  );
}

export type HealthResponse = {
  status: string;
  noc_model: { configured: boolean; backend: string; model: string; detail: string };
};

/** A cheap liveness probe for the status bar. Resolves `null` rather than throwing: a health
 *  check that fails is itself the answer. */
export async function checkHealth(timeoutMs = 2500): Promise<HealthResponse | null> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const r = await fetch(`${API_BASE_URL}/health`, {
      signal: controller.signal,
      cache: "no-store",
    });
    return r.ok ? ((await r.json()) as HealthResponse) : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

/** Raw `POST /position` — the engine's flat score dict, no view-model grouping. Not used by the
 *  dashboard (which gets the same numbers already grouped) but the honest primitive to build on. */
export async function fetchPosition(
  profile: Profile,
  asOf?: string,
  options: { signal?: AbortSignal; timeoutMs?: number } = {},
) {
  return postJson<{
    total: number;
    core: number;
    spouse: number;
    skill_transfer: number;
    additional: number;
    breakdown: { factor: string; points: number }[];
  }>("/position", { profile, as_of: asOf ?? null }, options);
}
