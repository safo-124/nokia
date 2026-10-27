// All calls go to /api, which Vite proxies to the FastAPI backend in development.
// Set VITE_API_URL to call a backend on another origin instead.
const BASE = import.meta.env.VITE_API_URL ?? "";

async function get(path, params = {}) {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v != null),
  ).toString();
  const res = await fetch(`${BASE}/api${path}${query ? `?${query}` : ""}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  meta: () => get("/meta"),
  links: () => get("/links"),
  linkRain: (time) => get("/links/rain", { time }),
  grid: (time) => get("/rainfall/grid", { time }),
  gauges: () => get("/gauges"),
  gaugeComparison: (id) => get(`/gauges/${encodeURIComponent(id)}/comparison`),
  hotspots: () => get("/hotspots"),
  floodRisk: (time) => get("/flood-risk", { time }),
  alerts: () => get("/alerts"),
};
