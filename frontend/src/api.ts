import type {
  Alert,
  DatasetSummary,
  FloodRisk,
  GaugeComparison,
  Gauges,
  GridFrame,
  Hotspots,
  LinkRain,
  Links,
  Meta,
} from "./types";

// All calls go to /api, which Vite proxies to the FastAPI backend in development.
// Set VITE_API_URL to call a backend on another origin instead.
const BASE: string = import.meta.env.VITE_API_URL ?? "";

async function get<T>(path: string, params: Record<string, string | undefined> = {}): Promise<T> {
  const query = new URLSearchParams(
    Object.entries(params).filter((e): e is [string, string] => e[1] != null),
  ).toString();
  const res = await fetch(`${BASE}/api${path}${query ? `?${query}` : ""}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  datasets: () => get<DatasetSummary[]>("/datasets"),

  /** Endpoints for one dataset, e.g. api.dataset("synthetic").meta() */
  dataset(id: string) {
    const ds = `/datasets/${encodeURIComponent(id)}`;
    return {
      meta: () => get<Meta>(`${ds}/meta`),
      links: () => get<Links>(`${ds}/links`),
      linkRain: (time: string) => get<LinkRain>(`${ds}/links/rain`, { time }),
      grid: (time: string, lead = 0) =>
        get<GridFrame>(`${ds}/rainfall/grid`, { time, lead: String(lead) }),
      gauges: () => get<Gauges>(`${ds}/gauges`),
      gaugeComparison: (gaugeId: string) =>
        get<GaugeComparison>(`${ds}/gauges/${encodeURIComponent(gaugeId)}/comparison`),
      hotspots: () => get<Hotspots>(`${ds}/hotspots`),
      floodRisk: (time: string) => get<FloodRisk>(`${ds}/flood-risk`, { time }),
      alerts: () => get<Alert[]>(`${ds}/alerts`),
    };
  },
};

export type DatasetApi = ReturnType<typeof api.dataset>;
