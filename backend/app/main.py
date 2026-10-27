"""Signal-to-Rain API. Reads what the pipeline stored in PostgreSQL (db/schema.sql)."""

from datetime import datetime, timedelta

import numpy as np
import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from .db import database_url, query

TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

app = FastAPI(title="Signal-to-Rain API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


@app.exception_handler(PoolTimeout)
@app.exception_handler(psycopg.OperationalError)
def database_unavailable(request: Request, exc: Exception):
    return JSONResponse(
        status_code=503,
        content={"detail": f"Can't reach PostgreSQL ({type(exc).__name__}). Is it running? DATABASE_URL host: "
                           f"{database_url().rsplit('@', 1)[-1]}"},
    )


def _iso(t):
    return t.strftime(TIME_FORMAT)


def _nan_to_none(values):
    return [None if v is None or np.isnan(v) else float(v) for v in values]


def _feature(geometry_type, coordinates, properties):
    return {"type": "Feature", "geometry": {"type": geometry_type, "coordinates": coordinates},
            "properties": properties}


def _collection(features):
    return {"type": "FeatureCollection", "features": features}


def _meta(dataset):
    row = query(
        """
        SELECT d.id, d.meta,
               (SELECT array_agg(g.time ORDER BY g.time) FROM rain_grid g WHERE g.dataset = d.id) AS times
        FROM datasets d WHERE d.id = %s
        """,
        (dataset,),
        one=True,
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset} not found")
    return {**row["meta"], "id": row["id"], "times": [_iso(t) for t in row["times"] or []]}


def _step(dataset, time):
    """The stored time step nearest to `time` (the first one if None)."""
    row = query(
        """
        SELECT time FROM rain_grid WHERE dataset = %(ds)s
        ORDER BY CASE WHEN %(t)s::timestamp IS NULL THEN 0
                      ELSE abs(extract(epoch FROM time - %(t)s::timestamp)) END, time
        LIMIT 1
        """,
        {"ds": dataset, "t": time},
        one=True,
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset} not found")
    return row["time"]


@app.get("/api/health")
def health():
    try:
        query("SELECT 1")
        return {"status": "ok", "database": True}
    except (psycopg.OperationalError, PoolTimeout):
        return {"status": "ok", "database": False}


@app.get("/api/datasets")
def datasets():
    """Every stored pipeline run, oldest first."""
    rows = query("SELECT id, meta FROM datasets ORDER BY created_at")
    keys = ("source", "region", "n_links", "has_flood_risk", "generated_at")
    return [{"id": r["id"], **{k: r["meta"].get(k) for k in keys}} for r in rows]


@app.get("/api/datasets/{dataset}/meta")
def meta(dataset: str):
    return _meta(dataset)


@app.get("/api/datasets/{dataset}/links")
def links(dataset: str):
    """Link geometry and radio metadata, as GeoJSON."""
    _meta(dataset)
    rows = query("SELECT * FROM links WHERE dataset = %s ORDER BY id", (dataset,))
    return _collection([
        _feature(
            "LineString",
            [[r["site_0_lon"], r["site_0_lat"]], [r["site_1_lon"], r["site_1_lat"]]],
            {"id": r["id"], "length_km": round(r["length_km"], 2),
             "frequency_ghz": round(r["frequency_ghz"], 1), "polarization": r["polarization"]},
        )
        for r in rows
    ])


@app.get("/api/datasets/{dataset}/links/rain")
def links_rain(dataset: str, time: datetime | None = None):
    """Rain rate on every link at one time step."""
    t = _step(dataset, time)
    rows = query("SELECT cml_id, rain_rate FROM link_rain WHERE dataset = %s AND time = %s", (dataset, t))
    return {"time": _iso(t), "rain_rate": {r["cml_id"]: r["rain_rate"] for r in rows}}


@app.get("/api/datasets/{dataset}/links/{cml_id}/series")
def link_series(dataset: str, cml_id: str):
    rows = query(
        "SELECT time, rain_rate FROM link_rain WHERE dataset = %s AND cml_id = %s ORDER BY time",
        (dataset, cml_id),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Link {cml_id} not found")
    return {"cml_id": cml_id, "time": [_iso(r["time"]) for r in rows],
            "rain_rate": [r["rain_rate"] for r in rows]}


def _shift(field, dy, dx):
    """Move a 2D field by (dy, dx) cells (rounded); cells with no source are NaN.

    Same as shift_field in pipeline/s2r/nowcast.py.
    """
    dy, dx = int(round(dy)), int(round(dx))
    out = np.full_like(field, np.nan)
    ny, nx = field.shape
    if abs(dy) >= ny or abs(dx) >= nx:
        return out
    out[max(0, dy): min(ny, ny + dy), max(0, dx): min(nx, nx + dx)] = \
        field[max(0, -dy): min(ny, ny - dy), max(0, -dx): min(nx, nx - dx)]
    return out


@app.get("/api/datasets/{dataset}/rainfall/grid")
def rainfall_grid(dataset: str, time: datetime | None = None, lead: int = Query(0, ge=0, le=60)):
    """Rainfall map [mm/h] at one time step, or the nowcast `lead` minutes after it.

    Rows run south to north. The nowcast moves the map along the storm motion
    estimated at `time`.
    """
    t = _step(dataset, time)
    row = query(
        """
        SELECT g.rain_rate, g.motion_dy, g.motion_dx, g.speed_kmh, g.bearing_deg, d.grid_lat, d.grid_lon
        FROM rain_grid g JOIN datasets d ON d.id = g.dataset
        WHERE g.dataset = %s AND g.time = %s
        """,
        (dataset, t),
        one=True,
    )
    lat, lon = row["grid_lat"], row["grid_lon"]
    frame = np.frombuffer(row["rain_rate"], dtype="<f4").reshape(len(lat), len(lon))
    if lead:
        frame = _shift(frame, row["motion_dy"] * lead, row["motion_dx"] * lead)
    return {
        "time": _iso(t),
        "lead_min": lead,
        "valid_time": _iso(t + timedelta(minutes=lead)),
        "motion": {"speed_kmh": row["speed_kmh"], "bearing_deg": row["bearing_deg"]},
        "lat": [round(v, 5) for v in lat],
        "lon": [round(v, 5) for v in lon],
        "rain_rate": [_nan_to_none(r) for r in frame.round(1)],
    }


@app.get("/api/datasets/{dataset}/gauges")
def gauges(dataset: str):
    _meta(dataset)
    rows = query("SELECT id, lat, lon FROM gauges WHERE dataset = %s ORDER BY id", (dataset,))
    return _collection([_feature("Point", [r["lon"], r["lat"]], {"id": r["id"]}) for r in rows])


@app.get("/api/datasets/{dataset}/gauges/{gauge_id}/comparison")
def gauge_comparison(dataset: str, gauge_id: str, minutes: int = 15):
    """Gauge measurement against the link-based estimate at the gauge, as `minutes` means."""
    rows = query(
        """
        SELECT date_bin(make_interval(mins => %(m)s), time, timestamp '2000-01-01') AS t,
               avg(gauge) AS gauge, avg(estimate) AS estimate
        FROM gauge_rain WHERE dataset = %(ds)s AND gauge_id = %(g)s
        GROUP BY 1 ORDER BY 1
        """,
        {"m": minutes, "ds": dataset, "g": gauge_id},
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Gauge {gauge_id} not found")
    both = np.array([(r["gauge"], r["estimate"]) for r in rows
                     if r["gauge"] is not None and r["estimate"] is not None]).reshape(-1, 2)
    hours = minutes / 60
    return {
        "gauge_id": gauge_id,
        "minutes": minutes,
        "time": [_iso(r["t"]) for r in rows],
        "gauge": [r["gauge"] for r in rows],
        "estimate": [r["estimate"] for r in rows],
        "stats": {
            "correlation": round(float(np.corrcoef(both.T)[0, 1]), 3) if len(both) > 2 else None,
            "total_gauge_mm": round(float(both[:, 0].sum() * hours), 1),
            "total_estimate_mm": round(float(both[:, 1].sum() * hours), 1),
        },
    }


@app.get("/api/datasets/{dataset}/hotspots")
def hotspots(dataset: str):
    rows = query("SELECT * FROM hotspots WHERE dataset = %s ORDER BY id", (dataset,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"No hotspots in dataset {dataset}")
    return _collection([
        _feature("Point", [r["lon"], r["lat"]],
                 {"id": r["id"], "name": r["name"], "vulnerability": r["vulnerability"]})
        for r in rows
    ])


@app.get("/api/datasets/{dataset}/flood-risk")
def flood_risk(dataset: str, time: datetime | None = None):
    """Risk level per hotspot at one time step, highest risk first.

    fc_level / fc_eta_min / fc_acc_1h: the highest level the nowcast expects
    within the next hour, minutes until then, and rain expected in that hour.
    """
    t = _step(dataset, time)
    rows = query(
        """
        SELECT hotspot_id, rain_rate, acc_1h, acc_3h, risk, level, fc_level, fc_eta_min, fc_acc_1h
        FROM flood_risk
        WHERE dataset = %s AND time = %s ORDER BY risk DESC, hotspot_id
        """,
        (dataset, t),
    )
    return {"time": _iso(t), "hotspots": rows}


@app.get("/api/datasets/{dataset}/alerts")
def alerts(dataset: str, until: datetime | None = None):
    """Alerts issued up to `until` (all of them if omitted).

    kind is "forecast" (early warning from the nowcast, with eta_min) or "observed".
    """
    rows = query(
        """
        SELECT time, hotspot_id, name, kind, level, eta_min, acc_1h, message FROM alerts
        WHERE dataset = %(ds)s AND (%(until)s::timestamp IS NULL OR time <= %(until)s::timestamp)
        ORDER BY time, kind  -- 'forecast' before 'observed' at the same minute
        """,
        {"ds": dataset, "until": until},
    )
    return [{**r, "time": _iso(r["time"])} for r in rows]
