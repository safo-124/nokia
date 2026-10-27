"""Flood risk per neighbourhood from recent rainfall, and the alerts it triggers.

This is a placeholder rule, not a trained model: risk rises with rain
accumulated over the last 1 and 3 hours, scaled by a vulnerability factor per
hotspot. Replace `score` with a model that uses terrain and drainage data.
The thresholds are demo assumptions, not GMet or NADMO warning levels.
"""

import json

import numpy as np
import pandas as pd

from .interpolate import sample_grid

LEVELS = ("low", "medium", "high")
# (mm in last 1 h, mm in last 3 h) at which each level starts
THRESHOLDS = {"medium": (15.0, 25.0), "high": (30.0, 50.0)}


def load_hotspots(path):
    with open(path, encoding="utf-8") as f:
        features = json.load(f)["features"]
    return pd.DataFrame(
        {
            "id": [ft["properties"]["id"] for ft in features],
            "name": [ft["properties"]["name"] for ft in features],
            "vulnerability": [ft["properties"].get("vulnerability", 1.0) for ft in features],
            "lon": [ft["geometry"]["coordinates"][0] for ft in features],
            "lat": [ft["geometry"]["coordinates"][1] for ft in features],
        }
    )


def score(grid, hotspots):
    """Risk per hotspot and time step. Returns a long DataFrame."""
    rate = pd.DataFrame(
        sample_grid(grid, hotspots.lat, hotspots.lon).T,
        index=pd.DatetimeIndex(grid.time.values),
        columns=hotspots.id,
    ).fillna(0.0)
    hours_per_step = (rate.index[1] - rate.index[0]) / pd.Timedelta("1h")
    acc_1h = (rate * hours_per_step).rolling("1h").sum()
    acc_3h = (rate * hours_per_step).rolling("3h").sum()

    vuln = hotspots.set_index("id").vulnerability
    level = pd.DataFrame("low", index=rate.index, columns=rate.columns)
    for name in ("medium", "high"):
        t1, t3 = THRESHOLDS[name]
        hit = (acc_1h.mul(vuln) >= t1) | (acc_3h.mul(vuln) >= t3)
        level = level.mask(hit, name)
    risk = np.clip(
        np.maximum(acc_1h / THRESHOLDS["high"][0], acc_3h / THRESHOLDS["high"][1]).mul(vuln),
        0,
        1,
    )

    columns = {"rain_rate": rate, "acc_1h": acc_1h, "acc_3h": acc_3h, "risk": risk, "level": level}
    out = None
    for name, wide in columns.items():
        long = wide.rename_axis(index="time", columns="hotspot_id").reset_index()
        long = long.melt(id_vars="time", var_name="hotspot_id", value_name=name)
        out = long if out is None else out.merge(long, on=["time", "hotspot_id"])
    return out


def alerts(risk, hotspots):
    """One alert each time a hotspot's level goes up, with an SMS-style message."""
    names = hotspots.set_index("id").name
    rank = {lvl: i for i, lvl in enumerate(LEVELS)}
    result = []
    for hotspot_id, group in risk.sort_values("time").groupby("hotspot_id"):
        previous = "low"
        for row in group.itertuples():
            if rank[row.level] > rank[previous]:
                result.append(
                    {
                        "time": row.time.isoformat(),
                        "hotspot_id": hotspot_id,
                        "name": names[hotspot_id],
                        "level": row.level,
                        "acc_1h": round(row.acc_1h, 1),
                        "message": (
                            f"Signal-to-Rain: {row.level.upper()} flood risk in "
                            f"{names[hotspot_id]}. {row.acc_1h:.0f} mm of rain in the "
                            "last hour. Avoid drains and low-lying roads."
                        ),
                    }
                )
            previous = row.level
    return sorted(result, key=lambda a: a["time"])
