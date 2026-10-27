"""API tests against a real PostgreSQL test database.

Uses TEST_DATABASE_URL (default: local signal_to_rain_test, created if missing)
and skips everything when PostgreSQL isn't reachable.
"""

import os
from datetime import datetime
from pathlib import Path

import numpy as np
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from app import db
from app.main import app

TEST_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/signal_to_rain_test"
)
SCHEMA = Path(__file__).resolve().parents[2] / "db" / "schema.sql"
T = [datetime(2026, 6, 15, 12, m) for m in range(3)]
ISO = [t.strftime("%Y-%m-%dT%H:%M:%S") for t in T]


def _connect():
    try:
        return psycopg.connect(TEST_URL, autocommit=True)
    except psycopg.OperationalError as e:
        if "does not exist" not in str(e):
            pytest.skip(f"PostgreSQL not reachable: {e}")
    name = conninfo_to_dict(TEST_URL)["dbname"]
    with psycopg.connect(make_conninfo(TEST_URL, dbname="postgres"), autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return psycopg.connect(TEST_URL, autocommit=True)


@pytest.fixture(scope="module")
def client():
    """A tiny dataset 'test': two links, one gauge, one hotspot, three time steps."""
    with _connect() as conn:
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        conn.execute("DELETE FROM datasets WHERE id = 'test'")
        conn.execute(
            "INSERT INTO datasets (id, meta, grid_lat, grid_lon) VALUES ('test', %s, %s, %s)",
            (Jsonb({"source": "test", "region": "Nowhere", "has_flood_risk": True}), [0.0, 0.01], [0.0, 0.01]),
        )
        for cml, reason in (("10001", None), ("10002", "too short")):
            conn.execute(
                "INSERT INTO links (dataset, id, site_0_lat, site_0_lon, site_1_lat, site_1_lon, length_km, "
                "frequency_ghz, polarization, excluded, exclude_reason) "
                "VALUES ('test', %s, 0, 0, 0.01, 0.01, 1.5, 23, 'V', %s, %s)",
                (cml, reason is not None, reason),
            )
        for t, a, b in zip(T, [0, 5, 10], [0, 0, None]):
            conn.execute("INSERT INTO link_rain (dataset, time, cml_id, rain_rate, wet) "
                         "VALUES ('test', %s, '10001', %s, true), ('test', %s, '10002', %s, false)",
                         (t, a, t, b))
            # 2 x 2 map with rain only in the south-west cell; storm moves 1 cell east per minute
            frame = np.array([[4, 0], [0, 0]], dtype="<f4")
            if t == T[1]:
                frame[1, 1] = np.nan
            conn.execute("INSERT INTO rain_grid (dataset, time, rain_rate, motion_dx, speed_kmh, bearing_deg, "
                         "speed_sd_kmh) VALUES ('test', %s, %s, 1, 30, 90, 3)", (t, frame.tobytes()))
        conn.execute("INSERT INTO gauges (dataset, id, lat, lon) VALUES ('test', 'G1', 0, 0)")
        for t, g, e in zip(T, [0, 4, 8], [0, 5, 9]):
            conn.execute("INSERT INTO gauge_rain (dataset, gauge_id, time, gauge, estimate) "
                         "VALUES ('test', 'G1', %s, %s, %s)", (t, g, e))
        conn.execute("INSERT INTO hotspots (dataset, id, name, vulnerability, lat, lon) "
                     "VALUES ('test', 'h1', 'Here', 1.0, 0, 0)")
        for t, level, fc in zip(T, ["low", "low", "medium"], ["medium", "medium", "medium"]):
            conn.execute(
                "INSERT INTO flood_risk (dataset, time, hotspot_id, rain_rate, acc_1h, acc_3h, risk, level, "
                "fc_level, fc_eta_min, fc_acc_1h) VALUES ('test', %s, 'h1', 1, 1, 1, 0.5, %s, %s, 20, 18)",
                (t, level, fc),
            )
        conn.execute(
            "INSERT INTO alerts (dataset, time, hotspot_id, name, kind, level, eta_min, eta_low_min, eta_high_min, "
            "acc_1h, message) VALUES "
            "('test', %s, 'h1', 'Here', 'forecast', 'medium', 2, 1, 5, 18, 'Expect rain'), "
            "('test', %s, 'h1', 'Here', 'observed', 'medium', NULL, NULL, NULL, 16, 'Watch out')",
            (T[0], T[2]),
        )

    db.configure(TEST_URL)
    yield TestClient(app)
    db.configure(db.database_url())


def test_datasets_and_meta(client):
    assert {"id": "test", "source": "test", "region": "Nowhere", "n_links": None,
            "has_flood_risk": True, "generated_at": None} in client.get("/api/datasets").json()
    assert client.get("/api/datasets/test/meta").json()["times"] == ISO


def test_links_carry_quality_flags(client):
    props = {f["properties"]["id"]: f["properties"] for f in client.get("/api/datasets/test/links").json()["features"]}
    assert (props["10001"]["excluded"], props["10001"]["exclude_reason"]) == (False, None)
    assert (props["10002"]["excluded"], props["10002"]["exclude_reason"]) == (True, "too short")


def test_link_rain_at_nearest_time(client):
    body = client.get("/api/datasets/test/links/rain", params={"time": "2026-06-15T12:01:10"}).json()
    assert body["time"] == ISO[1]
    assert body["rain_rate"] == {"10001": 5.0, "10002": 0.0}


def test_link_series_keeps_nulls(client):
    assert client.get("/api/datasets/test/links/10002/series").json()["rain_rate"] == [0.0, 0.0, None]


def test_grid_nan_becomes_null(client):
    body = client.get("/api/datasets/test/rainfall/grid", params={"time": ISO[1]}).json()
    assert body["rain_rate"] == [[4.0, 0.0], [0.0, None]]
    assert body["motion"] == {"speed_kmh": 30.0, "bearing_deg": 90.0, "speed_sd_kmh": 3.0}


def test_grid_nowcast_moves_rain_with_the_storm(client):
    body = client.get("/api/datasets/test/rainfall/grid", params={"time": ISO[0], "lead": 1}).json()
    assert body["valid_time"] == "2026-06-15T12:01:00"
    assert body["rain_rate"] == [[None, 4.0], [None, 0.0]]  # one cell east, nothing known behind it
    assert client.get("/api/datasets/test/rainfall/grid", params={"lead": 61}).status_code == 422


def test_gauge_comparison_and_alerts(client):
    body = client.get("/api/datasets/test/gauges/G1/comparison", params={"minutes": 1}).json()
    assert body["estimate"] == [0.0, 5.0, 9.0]
    assert body["stats"]["correlation"] > 0.99
    early = client.get("/api/datasets/test/alerts", params={"until": ISO[1]}).json()
    assert [(a["kind"], a["eta_min"], a["eta_low_min"], a["eta_high_min"]) for a in early] == [("forecast", 2, 1, 5)]
    assert [a["message"] for a in client.get("/api/datasets/test/alerts").json()] == ["Expect rain", "Watch out"]


def test_flood_risk_includes_forecast(client):
    body = client.get("/api/datasets/test/flood-risk", params={"time": ISO[0]}).json()
    h = body["hotspots"][0]
    assert (h["level"], h["fc_level"], h["fc_eta_min"], h["fc_acc_1h"]) == ("low", "medium", 20, 18.0)


def test_unknown_things_are_404(client):
    assert client.get("/api/datasets/nope/meta").status_code == 404
    assert client.get("/api/datasets/nope/rainfall/grid").status_code == 404
    assert client.get("/api/datasets/test/links/nope/series").status_code == 404
    assert client.get("/api/datasets/test/gauges/nope/comparison").status_code == 404
