"""Loads the pipeline's output files and answers queries on them.

Files are re-read whenever meta.json changes, so re-running the pipeline is
picked up without restarting the server.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd


class DataNotReady(Exception):
    pass


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _nan_to_none(values):
    return [None if np.isnan(v) else float(v) for v in values]


class Store:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self._mtime = None

    def _refresh(self):
        meta_path = self.data_dir / "meta.json"
        if not meta_path.exists():
            raise DataNotReady(
                f"No pipeline output in {self.data_dir}. Run: cd pipeline && python -m s2r.run"
            )
        mtime = meta_path.stat().st_mtime
        if mtime == self._mtime:
            return
        d = self.data_dir
        self.meta = _read_json(meta_path)
        self.times = pd.DatetimeIndex(self.meta["times"])
        self.links = _read_json(d / "links.geojson")
        self.gauges = _read_json(d / "gauges.geojson")

        # IDs stay strings even when they look like numbers (OpenMRG uses 10001, ...)
        link_rain = pd.read_csv(d / "link_rain.csv", parse_dates=["time"], dtype={"cml_id": str})
        self.link_rain = link_rain.pivot(index="time", columns="cml_id", values="rain_rate")
        self.gauge_rain = pd.read_csv(d / "gauge_rain.csv", parse_dates=["time"], dtype={"gauge_id": str})

        with np.load(d / "grid.npz") as grid:
            self.grid_lat = grid["lat"]
            self.grid_lon = grid["lon"]
            self.grid = grid["rain_rate"]

        self.hotspots = self.risk = None
        self.alerts = []
        if self.meta.get("has_flood_risk"):
            self.hotspots = _read_json(d / "hotspots.geojson")
            self.risk = pd.read_csv(d / "flood_risk.csv", parse_dates=["time"], dtype={"hotspot_id": str})
            self.alerts = _read_json(d / "alerts.json")
        self._mtime = mtime

    def ready(self):
        self._refresh()
        return self

    def index(self, time=None):
        """Index of the time step nearest to `time` (ISO string); the first if None."""
        if time is None:
            return 0
        return int(self.times.get_indexer([pd.Timestamp(time)], method="nearest")[0])

    def grid_frame(self, i):
        frame = np.round(self.grid[i], 1)
        return {
            "time": self.meta["times"][i],
            "lat": self.grid_lat.round(5).tolist(),
            "lon": self.grid_lon.round(5).tolist(),
            "rain_rate": [_nan_to_none(row) for row in frame],
        }

    def link_rain_at(self, i):
        row = self.link_rain.iloc[i]
        return {"time": self.meta["times"][i], "rain_rate": dict(zip(row.index, _nan_to_none(row.values)))}

    def link_series(self, cml_id):
        if cml_id not in self.link_rain.columns:
            return None
        return {"cml_id": cml_id, "time": self.meta["times"], "rain_rate": _nan_to_none(self.link_rain[cml_id].values)}

    def gauge_comparison(self, gauge_id, resample="15min"):
        g = self.gauge_rain[self.gauge_rain.gauge_id == gauge_id]
        if g.empty:
            return None
        series = g.set_index("time")[["gauge", "estimate"]].resample(resample).mean()
        hours = pd.Timedelta(resample) / pd.Timedelta("1h")
        both = series.dropna()
        return {
            "gauge_id": gauge_id,
            "resample": resample,
            "time": [t.strftime("%Y-%m-%dT%H:%M:%S") for t in series.index],
            "gauge": _nan_to_none(series.gauge.values),
            "estimate": _nan_to_none(series.estimate.values),
            "stats": {
                "correlation": round(float(both.gauge.corr(both.estimate)), 3) if len(both) > 2 else None,
                "total_gauge_mm": round(float(both.gauge.sum() * hours), 1),
                "total_estimate_mm": round(float(both.estimate.sum() * hours), 1),
            },
        }

    def flood_risk_at(self, i):
        if self.risk is None:
            return None
        rows = self.risk[self.risk.time == self.times[i]]
        return {
            "time": self.meta["times"][i],
            "hotspots": rows.drop(columns="time").to_dict(orient="records"),
        }

    def alerts_until(self, i):
        until = self.meta["times"][i]
        return [a for a in self.alerts if a["time"] <= until]
