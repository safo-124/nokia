import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import main
from app.store import Store

TIMES = ["2026-06-15T12:00:00", "2026-06-15T12:01:00", "2026-06-15T12:02:00"]


def _write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


def _point(pid, lon, lat, **props):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"id": pid, **props}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A tiny pipeline output: two links, one gauge, one hotspot, three time steps."""
    _write(tmp_path / "meta.json", {"source": "test", "times": TIMES, "has_flood_risk": True})
    _write(tmp_path / "links.geojson", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0], [0.01, 0.01]]},
         "properties": {"id": cml}} for cml in ("10001", "10002")]})
    _write(tmp_path / "gauges.geojson", {"type": "FeatureCollection", "features": [_point("G1", 0, 0)]})
    _write(tmp_path / "hotspots.geojson",
           {"type": "FeatureCollection", "features": [_point("h1", 0, 0, name="Here")]})
    _write(tmp_path / "alerts.json", [{"time": TIMES[2], "hotspot_id": "h1", "level": "medium"}])
    pd.DataFrame({"time": TIMES * 2, "cml_id": ["10001"] * 3 + ["10002"] * 3,
                  "rain_rate": [0, 5, 10, 0, 0, np.nan], "wet": [0, 1, 1, 0, 0, 0]}
                 ).to_csv(tmp_path / "link_rain.csv", index=False)
    pd.DataFrame({"time": TIMES, "gauge_id": "G1", "gauge": [0, 4, 8], "estimate": [0, 5, 9]}
                 ).to_csv(tmp_path / "gauge_rain.csv", index=False)
    pd.DataFrame({"time": TIMES, "hotspot_id": "h1", "rain_rate": [0, 5, 10], "acc_1h": [0, 0.1, 0.2],
                  "acc_3h": [0, 0.1, 0.2], "risk": [0, 0, 0.6], "level": ["low", "low", "medium"]}
                 ).to_csv(tmp_path / "flood_risk.csv", index=False)
    rain = np.zeros((3, 2, 2), dtype="float32")
    rain[1, 0, 0] = np.nan
    np.savez(tmp_path / "grid.npz", lat=np.array([0.0, 0.01]), lon=np.array([0.0, 0.01]), rain_rate=rain)

    monkeypatch.setattr(main, "store", Store(tmp_path))
    return TestClient(main.app)


def test_link_rain_at_nearest_time(client):
    body = client.get("/api/links/rain", params={"time": "2026-06-15T12:01:10"}).json()
    assert body["time"] == TIMES[1]
    assert body["rain_rate"] == {"10001": 5.0, "10002": 0.0}


def test_numeric_looking_link_ids_stay_strings(client):
    body = client.get("/api/links/10002/series").json()
    assert body["rain_rate"] == [0.0, 0.0, None]


def test_grid_nan_becomes_null(client):
    body = client.get("/api/rainfall/grid", params={"time": TIMES[1]}).json()
    assert body["rain_rate"][0][0] is None


def test_gauge_comparison_and_alerts(client):
    body = client.get("/api/gauges/G1/comparison", params={"resample": "1min"}).json()
    assert body["estimate"] == [0.0, 5.0, 9.0]
    assert client.get("/api/alerts", params={"until": TIMES[1]}).json() == []
    assert len(client.get("/api/alerts").json()) == 1


def test_unknown_ids_are_404(client):
    assert client.get("/api/links/nope/series").status_code == 404
    assert client.get("/api/gauges/nope/comparison").status_code == 404


def test_missing_data_is_503(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", Store(tmp_path))
    c = TestClient(main.app)
    assert c.get("/api/meta").status_code == 503
    assert c.get("/api/health").json() == {"status": "ok", "data": False}
