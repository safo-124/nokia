"""Write pipeline results to PostgreSQL (tables in db/schema.sql).

Set DATABASE_URL to point somewhere else than the local default.
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

DEFAULT_URL = "postgresql://postgres:postgres@localhost:5432/signal_to_rain"
SCHEMA = Path(__file__).resolve().parents[2] / "db" / "schema.sql"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


def database_url():
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def connect(url=None):
    """Connect, creating the database first if it doesn't exist yet."""
    url = url or database_url()
    try:
        return psycopg.connect(url)
    except psycopg.OperationalError as e:
        if "does not exist" not in str(e):
            raise
    name = conninfo_to_dict(url)["dbname"]
    with psycopg.connect(make_conninfo(url, dbname="postgres"), autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return psycopg.connect(url)


def _rows(df):
    """DataFrame rows as plain Python values, with NaN as NULL."""
    return df.astype(object).where(df.notna(), None).itertuples(index=False, name=None)


def _copy(conn, table, df):
    stmt = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, df.columns))
    )
    with conn.cursor().copy(stmt) as copy:
        for row in _rows(df):
            copy.write_row(row)


def _links_frame(dataset, cmls):
    return pd.DataFrame(
        {
            "dataset": dataset,
            "id": cmls.cml_id.values.astype(str),
            "site_0_lat": cmls.site_0_lat.values,
            "site_0_lon": cmls.site_0_lon.values,
            "site_1_lat": cmls.site_1_lat.values,
            "site_1_lon": cmls.site_1_lon.values,
            "length_km": cmls.length.values.round(2),
            "frequency_ghz": cmls.frequency.mean("sublink_id").values.round(1),
            "polarization": cmls.polarization.isel(sublink_id=0).values.astype(str),
        }
    )


def save(conn, dataset, *, meta, cmls, r_link, wet_link, gauges, gauge_estimate, grid,
         hotspots=None, risk=None, alert_list=None):
    """Replace `dataset` with this run's results, in one transaction."""
    times = pd.DatetimeIndex(grid.time.values)
    with conn.transaction():
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        conn.execute("DELETE FROM datasets WHERE id = %s", (dataset,))
        conn.execute(
            "INSERT INTO datasets (id, meta, grid_lat, grid_lon) VALUES (%s, %s, %s, %s)",
            (dataset, Jsonb(meta), grid.lat.values.tolist(), grid.lon.values.tolist()),
        )
        _copy(conn, "links", _links_frame(dataset, cmls))

        link_rain = r_link.to_dataframe(name="rain_rate").reset_index()
        link_rain["wet"] = wet_link.transpose(*r_link.dims).values.reshape(-1)
        link_rain["rain_rate"] = link_rain.rain_rate.round(2)
        link_rain["cml_id"] = link_rain.cml_id.astype(str)
        link_rain.insert(0, "dataset", dataset)
        _copy(conn, "link_rain", link_rain[["dataset", "time", "cml_id", "rain_rate", "wet"]])

        frames = grid.values.astype("<f4")
        _copy(conn, "rain_grid", pd.DataFrame(
            {"dataset": dataset, "time": times, "rain_rate": [f.tobytes() for f in frames]}
        ))

        _copy(conn, "gauges", pd.DataFrame(
            {"dataset": dataset, "id": gauges.id.values.astype(str),
             "lat": gauges.lat.values, "lon": gauges.lon.values}
        ))
        _copy(conn, "gauge_rain", pd.DataFrame(
            {
                "dataset": dataset,
                "gauge_id": np.repeat(gauges.id.values.astype(str), len(gauges.time)),
                "time": np.tile(gauges.time.values, len(gauges.id)),
                "gauge": gauges.rainfall_rate.transpose("id", "time").values.reshape(-1).round(2),
                "estimate": gauge_estimate.reshape(-1).round(2),
            }
        ))

        if hotspots is not None:
            _copy(conn, "hotspots", hotspots[["id", "name", "vulnerability", "lat", "lon"]]
                  .assign(dataset=dataset)[["dataset", "id", "name", "vulnerability", "lat", "lon"]])
            risk = risk.assign(dataset=dataset)
            for col in ("rain_rate", "acc_1h", "acc_3h", "risk"):
                risk[col] = risk[col].astype(float).round(2)
            _copy(conn, "flood_risk", risk[["dataset", "time", "hotspot_id", "rain_rate",
                                            "acc_1h", "acc_3h", "risk", "level"]])
            if alert_list:
                alerts = pd.DataFrame(alert_list).assign(dataset=dataset)
                alerts["time"] = pd.to_datetime(alerts.time)
                _copy(conn, "alerts", alerts[["dataset", "time", "hotspot_id", "name", "level",
                                              "acc_1h", "message"]])
