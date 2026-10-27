"""Signal-to-Rain API. Serves the files the pipeline writes to DATA_DIR."""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .store import DataNotReady, Store

DATA_DIR = Path(
    os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data" / "processed")
)

app = FastAPI(title="Signal-to-Rain API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
store = Store(DATA_DIR)


@app.exception_handler(DataNotReady)
def data_not_ready(request: Request, exc: DataNotReady):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _found(value, what):
    if value is None:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return value


@app.get("/api/health")
def health():
    try:
        store.ready()
        return {"status": "ok", "data": True}
    except DataNotReady:
        return {"status": "ok", "data": False}


@app.get("/api/meta")
def meta():
    return store.ready().meta


@app.get("/api/links")
def links():
    """Link geometry and radio metadata, as GeoJSON."""
    return store.ready().links


@app.get("/api/links/rain")
def links_rain(time: str | None = None):
    """Rain rate on every link at one time step."""
    s = store.ready()
    return s.link_rain_at(s.index(time))


@app.get("/api/links/{cml_id}/series")
def link_series(cml_id: str):
    return _found(store.ready().link_series(cml_id), f"Link {cml_id}")


@app.get("/api/rainfall/grid")
def rainfall_grid(time: str | None = None):
    """Interpolated rainfall map [mm/h] at one time step. Rows run south to north."""
    s = store.ready()
    return s.grid_frame(s.index(time))


@app.get("/api/gauges")
def gauges():
    return store.ready().gauges


@app.get("/api/gauges/{gauge_id}/comparison")
def gauge_comparison(gauge_id: str, resample: str = "15min"):
    """Gauge measurement against the link-based estimate at the gauge location."""
    return _found(store.ready().gauge_comparison(gauge_id, resample), f"Gauge {gauge_id}")


@app.get("/api/hotspots")
def hotspots():
    return _found(store.ready().hotspots, "Hotspots")


@app.get("/api/flood-risk")
def flood_risk(time: str | None = None):
    s = store.ready()
    return _found(s.flood_risk_at(s.index(time)), "Flood risk")


@app.get("/api/alerts")
def alerts(until: str | None = None):
    """Alerts issued up to `until` (all of them if omitted)."""
    s = store.ready()
    return s.alerts_until(s.index(until) if until else len(s.times) - 1)
