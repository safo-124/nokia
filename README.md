# Signal-to-Rain

Turning mobile networks into flood early warning sensors. Nokia Student Network Challenge 2026, AI Challenge.
See [Signal-to-Rain_Product_Document.pdf](Signal-to-Rain_Product_Document.pdf) for the idea and business case.

Rain weakens the microwave links between cell towers. The pipeline turns that signal loss into rain rates per
link, a rainfall map and flood risk per neighbourhood; the web app replays the storm with alerts and checks the
estimates against rain gauges.

```
pipeline/   Python + pycomlink: signal levels -> wet/dry -> rain rate -> map -> flood risk   (signal processing & AI)
backend/    FastAPI: serves the pipeline's output files                                       (backend)
frontend/   React + Vite + Leaflet + Recharts + Tailwind: map, storm replay, gauge chart, alerts (web app)
data/       hotspots/ is tracked; raw/ (downloads) and processed/ (pipeline output) are not
```

## Run it

### With Docker

```bash
docker compose up --build
```

Open http://localhost:5173. The pipeline runs once on the synthetic Accra storm, then the backend and web app start.
For the real Gothenburg data (downloads about 28 MB the first time):

```bash
S2R_SOURCE=openmrg docker compose up --build
```

In PowerShell: `$env:S2R_SOURCE="openmrg"; docker compose up --build`.

### Without Docker

Needs Python 3.12+ and Node 20+. From the repo root (on macOS/Linux use `.venv/bin/python`):

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r pipeline/requirements.txt -r backend/requirements.txt
cd pipeline && ../.venv/Scripts/python -m s2r.run && cd ..
.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000 --reload
```

In a second terminal:

```bash
cd frontend && npm install && npm run dev
```

Re-running the pipeline is picked up by the backend without a restart; reload the page.

### Tests

```bash
cd pipeline && ../.venv/Scripts/python -m pytest -q
cd backend && ../.venv/Scripts/python -m pytest -q
```

## Pipeline

```bash
python -m s2r.run [--source synthetic|openmrg] [--wet-dry std|ml] [--start ISO --end ISO] [--hotspots FILE] [--out DIR]
```

| Step | Module | What it does |
|---|---|---|
| Load | `s2r/data.py`, `s2r/synthetic.py` | Links as xarray (`cml_id`, `sublink_id`, `time`) with `tsl`, `rsl`, plus gauges. `R_ref` is reference rain along each link (synthetic truth, or radar for OpenMRG) |
| Wet/dry | `s2r/wetdry.py` | `std`: rolling standard deviation rule. `ml`: gradient-boosted classifier on signal features, trained and scored on held-out links |
| Rain rate | `s2r/rain.py` | pycomlink: constant baseline, wet antenna correction (Schleiss 2013), ITU-R P.838 k-R power law |
| Map | `s2r/interpolate.py` | Inverse distance weighting from link midpoints onto a 0.5 km grid |
| Flood risk | `s2r/flood.py` | Placeholder rule on 1 h / 3 h rain at each hotspot, plus SMS-style alerts when a level goes up |
| Export | `s2r/export.py` | Writes the files below |

**Data sources**
- `synthetic`: a squall line crossing Accra from east to west over 79 synthetic links, 6 gauges and 7 flood hotspots
  ([data/hotspots/accra.geojson](data/hotspots/accra.geojson)). Doubles as the Ghana mock-up.
- `openmrg`: the 8-day OpenMRG sample (Gothenburg, July 2015; 364 links, 10 city gauges, SMHI radar), loaded with
  `poligrain`. The default window is the wettest night, 25 July 22:00 to 26 July 06:00. There are no hotspots for
  Gothenburg, so no flood risk or alerts.

**Output contract** (`data/processed/`, read by the backend):
`meta.json`, `links.geojson`, `link_rain.csv`, `gauges.geojson`, `gauge_rain.csv`, `grid.npz`, and with hotspots
`hotspots.geojson`, `flood_risk.csv`, `alerts.json`. Column details are in `s2r/export.py`.

### Results so far

| Data | Wet/dry MCC, rule / AI | Gauges |
|---|---|---|
| Synthetic Accra | 0.71 / 0.97 | correlation 0.94 to 1.00 at all 6 gauges (15 min) |
| OpenMRG Gothenburg | 0.35 / 0.47 | correlation 0.85 to 0.99 at 7 of 10 gauges; 0.37 to 0.69 at the other 3 |

The synthetic numbers only show the pipeline is wired correctly. The OpenMRG numbers are the ones to quote.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/meta` | source, region, bounds, time steps, wet/dry scores |
| `GET /api/links` | link geometry (GeoJSON) |
| `GET /api/links/rain?time=` | rain rate on every link at one time step |
| `GET /api/links/{id}/series` | rain rate time series for one link |
| `GET /api/rainfall/grid?time=` | rainfall map at one time step |
| `GET /api/gauges`, `GET /api/gauges/{id}/comparison` | gauge locations; gauge vs link estimate, 15 min means |
| `GET /api/hotspots`, `GET /api/flood-risk?time=` | hotspots; risk level per hotspot at one time step |
| `GET /api/alerts?until=` | alerts issued up to a time |

`time` is ISO 8601; the nearest available step is used. Interactive docs at http://localhost:8000/docs.

## Hackathon plan

| Hours | Plan | Status in this scaffold |
|---|---|---|
| 0 to 1 | Repo, Docker, load OpenMRG, pick a storm | Done; storm window picked from gauge totals. Docker files written but not yet tested |
| 1 to 3 | Rain rate pipeline, wet/dry classifier | Working baseline; tune features, thresholds and the classifier |
| 3 to 5 | FastAPI endpoints, React map with replay and charts | Working baseline; polish the UI |
| 5 to 6 | Flood risk scoring, SMS alert panel, Ghana mock-up | Placeholder rule and alerts on synthetic Accra; replace with terrain/drainage model |
| 6 to 7 | Slides, business case, rehearsal | |

## Known gaps

- Hotspot coordinates in Accra are approximate and vulnerability is a placeholder 1.0; flood thresholds are demo assumptions,
  not GMet or NADMO warning levels.
- A few OpenMRG links give implausible peaks (over 200 mm/h); there are no quality flags yet.
- The map uses link midpoints for interpolation and fills the whole network bounding box.
- Base map tiles come from tile.openstreetmap.org, which is fine for a demo but not for production traffic.
