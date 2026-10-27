# Signal-to-Rain

Turning mobile networks into flood early warning sensors. Nokia Student Network Challenge 2026, AI Challenge.
See [Signal-to-Rain_Product_Document.pdf](Signal-to-Rain_Product_Document.pdf) for the idea and business case.

Rain weakens the microwave links between cell towers. The pipeline turns that signal loss into rain rates per
link, a rainfall map and flood risk per neighbourhood, and stores them in PostgreSQL. The web app replays the storm
with alerts and checks the estimates against rain gauges.

```
pipeline/   Python + pycomlink: signal levels -> wet/dry -> rain rate -> map -> flood risk -> PostgreSQL  (signal processing & AI)
backend/    FastAPI: reads PostgreSQL, serves JSON                                                     (backend)
frontend/   React + TypeScript + Vite + Leaflet + Recharts + Tailwind: map, replay, gauge chart, alerts  (web app)
db/         schema.sql, applied automatically by the pipeline
data/       hotspots/ is tracked; raw/ (downloaded OpenMRG files) is not
```

## Setup (once per laptop)

1. **PostgreSQL 14+** running locally. On Windows:
   `winget install PostgreSQL.PostgreSQL.17 --override "--mode unattended --superpassword postgres"`.
   The code connects to `postgresql://postgres:postgres@localhost:5432/signal_to_rain` unless `DATABASE_URL` is set,
   and creates the `signal_to_rain` database on first run.
2. **Python 3.12+** and **Node 20+**. From the repo root (on macOS/Linux use `.venv/bin/python`):

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r pipeline/requirements.txt -r backend/requirements.txt
cd frontend && npm install
```

## Run it

```bash
cd pipeline && ../.venv/Scripts/python -m s2r.run                   # synthetic Accra storm, about 20 s
cd pipeline && ../.venv/Scripts/python -m s2r.run --source openmrg  # real Gothenburg data, about 1 min (downloads 28 MB once)
```

Each run is stored as a dataset (named after the source, or `--dataset NAME`); re-running replaces it. Then, in two terminals:

```bash
.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000 --reload
```

```bash
cd frontend && npm run dev
```

Open http://localhost:5173 and pick a dataset in the header. API docs are at http://localhost:8000/docs.

### Checks

```bash
cd pipeline && ../.venv/Scripts/python -m pytest -q    # needs PostgreSQL; uses database signal_to_rain_test
cd backend && ../.venv/Scripts/python -m pytest -q
cd frontend && npm run typecheck
```

## Pipeline

```bash
python -m s2r.run [--source synthetic|openmrg] [--dataset NAME] [--wet-dry std|ml] [--start ISO --end ISO] [--hotspots FILE]
```

| Step | Module | What it does |
|---|---|---|
| Load | `s2r/data.py`, `s2r/synthetic.py` | Links as xarray (`cml_id`, `sublink_id`, `time`) with `tsl`, `rsl`, plus gauges. `R_ref` is reference rain along each link (synthetic truth, or radar for OpenMRG) |
| Wet/dry | `s2r/wetdry.py` | `std`: rolling standard deviation rule. `ml`: gradient-boosted classifier on signal features, trained and scored on held-out links |
| Rain rate | `s2r/rain.py` | pycomlink: constant baseline, wet antenna correction (Schleiss 2013), ITU-R P.838 k-R power law |
| Map | `s2r/interpolate.py` | Inverse distance weighting from link midpoints onto a 0.5 km grid |
| Nowcast | `s2r/nowcast.py` | Storm motion from consecutive maps (global Lucas-Kanade), then the map moved along it 0 to 60 min ahead. Scored against "rain stays put" |
| Flood risk | `s2r/flood.py` | Placeholder rule on 1 h / 3 h rain at each hotspot, applied to now and to the next hour (fallen + forecast rain). Early warnings when the forecast level is higher than now, plus alerts when a level is reached |
| Store | `s2r/db.py` | Replaces the dataset in PostgreSQL in one transaction (bulk `COPY`) |

**Data sources**
- `synthetic`: a squall line crossing Accra from east to west over 79 synthetic links, 6 gauges and 7 flood hotspots
  ([data/hotspots/accra.geojson](data/hotspots/accra.geojson)). Doubles as the Ghana mock-up.
- `openmrg`: the 8-day OpenMRG sample (Gothenburg, July 2015; 364 links, 10 city gauges, SMHI radar), loaded with
  `poligrain`. The default window is the wettest night, 25 July 22:00 to 26 July 06:00. There are no hotspots for
  Gothenburg, so no flood risk or alerts.

**Tables** ([db/schema.sql](db/schema.sql)): `datasets` (one row per run, with meta as JSON), `links`, `link_rain`,
`rain_grid` (one float32 frame per time step), `gauges`, `gauge_rain`, `hotspots`, `flood_risk`, `alerts`.
Deleting a `datasets` row deletes everything in it. Handy for exploring:

```sql
SELECT cml_id, max(rain_rate) FROM link_rain WHERE dataset = 'openmrg' GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
```

### Results so far

| Data | Wet/dry MCC, rule / AI | Gauges |
|---|---|---|
| Synthetic Accra | 0.71 / 0.97 | correlation 0.94 to 1.00 at all 6 gauges (15 min) |
| OpenMRG Gothenburg | 0.35 / 0.47 | correlation 0.85 to 0.99 at 7 of 10 gauges; 0.37 to 0.69 at the other 3 |

The synthetic numbers only show the pipeline is wired correctly. The OpenMRG numbers are the ones to quote.

**Nowcast**, critical success index for rain above 1 mm/h (higher is better), nowcast / rain stays put:

| Data | +15 min | +30 min | +60 min | Early warnings |
|---|---|---|---|---|
| Synthetic Accra | 0.85 / 0.83 | 0.78 / 0.70 | 0.53 / 0.47 | 14 of 14 came true, median 32 min ahead (at least 24), no false alarms or misses |
| OpenMRG Gothenburg | 0.49 / 0.44 | 0.37 / 0.26 | 0.26 / 0.14 | no hotspots |

On real data the nowcast gets 42% more of the rain right at +30 min and almost twice as much at +60 min.
The synthetic warnings come from a clean, steadily moving storm, so treat 32 minutes as the best case.

## API

Everything except `/api/health` and `/api/datasets` is under `/api/datasets/{dataset}/`.

| Endpoint | Returns |
|---|---|
| `GET /api/datasets` | stored datasets |
| `GET .../meta` | source, region, bounds, time steps, wet/dry scores |
| `GET .../links`, `GET .../links/rain?time=`, `GET .../links/{id}/series` | link geometry (GeoJSON); rain on every link at one step; one link's time series |
| `GET .../rainfall/grid?time=&lead=0..60` | rainfall map at one time step, or the nowcast `lead` minutes later, with the storm motion |
| `GET .../gauges`, `GET .../gauges/{id}/comparison?minutes=15` | gauge locations; gauge vs link estimate as N-minute means |
| `GET .../hotspots`, `GET .../flood-risk?time=` | hotspots; risk per hotspot at one step, highest first, with the level expected within the hour (`fc_level`, `fc_eta_min`, `fc_acc_1h`) |
| `GET .../alerts?until=` | alerts issued up to a time; `kind` is `forecast` (early warning, with `eta_min`) or `observed` |

`time` is ISO 8601; the nearest stored step is used.

## Hackathon plan

| Hours | Plan | Status in this scaffold |
|---|---|---|
| 0 to 1 | Repo, load OpenMRG, pick a storm | Done; storm window picked from gauge totals |
| 1 to 3 | Rain rate pipeline, wet/dry classifier | Working baseline; tune features, thresholds and the classifier |
| 3 to 5 | FastAPI endpoints, React map with replay and charts | Working baseline; polish the UI |
| 5 to 6 | Flood risk scoring, SMS alert panel, Ghana mock-up | Placeholder rule and alerts on synthetic Accra; replace with terrain/drainage model |
| 6 to 7 | Slides, business case, rehearsal | |

## Known gaps

- Hotspot coordinates in Accra are approximate and vulnerability is a placeholder 1.0; flood thresholds are demo assumptions,
  not GMet or NADMO warning levels.
- A few OpenMRG links give implausible peaks (over 200 mm/h); there are no quality flags yet.
- The nowcast moves the whole map with one motion vector and keeps rain intensity fixed: no growth, decay or new cells,
  and nothing is known about rain that is still outside the network. While a storm enters the map the direction wobbles
  (the synthetic storm shows north-west for a few minutes before settling on west).
- The map uses link midpoints for interpolation and fills the whole network bounding box.
- Base map tiles come from tile.openstreetmap.org and need internet at the venue.
