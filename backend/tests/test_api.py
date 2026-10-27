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
        for cml in ("10001", "10002"):
            conn.execute("INSERT INTO links VALUES ('test', %s, 0, 0, 0.01, 0.01, 1.5, 23, 'V')", (cml,))
        for t, a, b in zip(T, [0, 5, 10], [0, 0, None]):
            conn.execute("INSERT INTO link_rain VALUES ('test', %s, '10001', %s, true)", (t, a))
            conn.execute("INSERT INTO link_rain VALUES ('test', %s, '10002', %s, false)", (t, b))
            frame = np.zeros((2, 2), dtype="<f4")
            if t == T[1]:
                frame[0, 0] = np.nan
            conn.execute("INSERT INTO rain_grid VALUES ('test', %s, %s)", (t, frame.tobytes()))
        conn.execute("INSERT INTO gauges VALUES ('test', 'G1', 0, 0)")
        for t, g, e in zip(T, [0, 4, 8], [0, 5, 9]):
            conn.execute("INSERT INTO gauge_rain VALUES ('test', 'G1', %s, %s, %s)", (t, g, e))
        conn.execute("INSERT INTO hotspots VALUES ('test', 'h1', 'Here', 1.0, 0, 0)")
        for t, level in zip(T, ["low", "low", "medium"]):
            conn.execute("INSERT INTO flood_risk VALUES ('test', %s, 'h1', 1, 1, 1, 0.5, %s)", (t, level))
        conn.execute("INSERT INTO alerts VALUES ('test', %s, 'h1', 'Here', 'medium', 16, 'Watch out')", (T[2],))

    db.configure(TEST_URL)
    yield TestClient(app)
    db.configure(db.database_url())


def test_datasets_and_meta(client):
    assert {"id": "test", "source": "test", "region": "Nowhere", "n_links": None,
            "has_flood_risk": True, "generated_at": None} in client.get("/api/datasets").json()
    assert client.get("/api/datasets/test/meta").json()["times"] == ISO


def test_link_rain_at_nearest_time(client):
    body = client.get("/api/datasets/test/links/rain", params={"time": "2026-06-15T12:01:10"}).json()
    assert body["time"] == ISO[1]
    assert body["rain_rate"] == {"10001": 5.0, "10002": 0.0}


def test_link_series_keeps_nulls(client):
    assert client.get("/api/datasets/test/links/10002/series").json()["rain_rate"] == [0.0, 0.0, None]


def test_grid_nan_becomes_null(client):
    body = client.get("/api/datasets/test/rainfall/grid", params={"time": ISO[1]}).json()
    assert body["rain_rate"][0][0] is None
    assert body["rain_rate"][1][1] == 0.0


def test_gauge_comparison_and_alerts(client):
    body = client.get("/api/datasets/test/gauges/G1/comparison", params={"minutes": 1}).json()
    assert body["estimate"] == [0.0, 5.0, 9.0]
    assert body["stats"]["correlation"] > 0.99
    assert client.get("/api/datasets/test/alerts", params={"until": ISO[1]}).json() == []
    assert client.get("/api/datasets/test/alerts").json()[0]["message"] == "Watch out"


def test_flood_risk_at_time(client):
    body = client.get("/api/datasets/test/flood-risk", params={"time": ISO[2]}).json()
    assert body["hotspots"][0]["level"] == "medium"


def test_unknown_things_are_404(client):
    assert client.get("/api/datasets/nope/meta").status_code == 404
    assert client.get("/api/datasets/nope/rainfall/grid").status_code == 404
    assert client.get("/api/datasets/test/links/nope/series").status_code == 404
    assert client.get("/api/datasets/test/gauges/nope/comparison").status_code == 404
