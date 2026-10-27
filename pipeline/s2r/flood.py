"""Flood risk per neighbourhood from recent and forecast rainfall, and the alerts it triggers.

This is a placeholder rule, not a trained model: risk rises with rain
accumulated over the last 1 and 3 hours, scaled by a vulnerability factor per
hotspot. Replace `score` with a model that uses terrain and drainage data.
The thresholds are demo assumptions, not GMet or NADMO warning levels.

With a storm motion from `s2r.nowcast`, the same rule is applied to the next
60 minutes: rain already fallen plus rain the nowcast expects. When that says
a hotspot will reach a higher level than it is at now, a warning goes out
before the rain arrives.
"""

import json

import numpy as np
import pandas as pd

from . import nowcast
from .interpolate import sample_grid

LEVELS = ("low", "medium", "high")
RANK = {lvl: i for i, lvl in enumerate(LEVELS)}
# (mm in last 1 h, mm in last 3 h) at which each level starts
THRESHOLDS = {"medium": (15.0, 25.0), "high": (30.0, 50.0)}
# A warning counts as a hit if the level is observed within this time
HIT_WINDOW = pd.Timedelta("90min")


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


def _rank(acc_1h, acc_3h, vulnerability):
    """Level rank (0 low, 1 medium, 2 high) from accumulations; works on any array shape."""
    rank = np.zeros(np.shape(acc_1h), dtype=int)
    for name in ("medium", "high"):
        t1, t3 = THRESHOLDS[name]
        rank[(acc_1h * vulnerability >= t1) | (acc_3h * vulnerability >= t3)] = RANK[name]
    return rank


def _long(columns):
    out = None
    for name, wide in columns.items():
        long = wide.rename_axis(index="time", columns="hotspot_id").reset_index()
        long = long.melt(id_vars="time", var_name="hotspot_id", value_name=name)
        out = long if out is None else out.merge(long, on=["time", "hotspot_id"])
    return out


def _forecast(grid, motion, hotspots, rate):
    """Highest level expected in the next hour, when it starts, and the rain expected."""
    fc_rates, leads = nowcast.hotspot_rates(grid, motion, hotspots.lat, hotspots.lon)
    hours_per_step = (rate.index[1] - rate.index[0]) / pd.Timedelta("1h")
    steps_1h, steps_3h = int(round(1 / hours_per_step)), int(round(3 / hours_per_step))
    fc_acc = np.cumsum(fc_rates, axis=2) * hours_per_step  # rain between now and now + lead

    # Rain already fallen that is still inside the 1 h / 3 h window at now + lead
    fallen = np.vstack([np.zeros((1, rate.shape[1])), np.cumsum(rate.values * hours_per_step, axis=0)])
    t = np.arange(len(rate))
    ranks = np.zeros(fc_acc.shape, dtype=int)
    vuln = hotspots.vulnerability.values
    for k in range(len(leads)):
        still_1h = fallen[t + 1] - fallen[np.clip(t + 1 + (k + 1) - steps_1h, 0, None)]
        still_3h = fallen[t + 1] - fallen[np.clip(t + 1 + (k + 1) - steps_3h, 0, None)]
        ranks[:, :, k] = _rank(still_1h + fc_acc[:, :, k], still_3h + fc_acc[:, :, k], vuln)

    fc_rank = ranks.max(axis=2)
    first = np.argmax(ranks == fc_rank[:, :, None], axis=2)
    frame = lambda values: pd.DataFrame(values, index=rate.index, columns=rate.columns)  # noqa: E731
    return {
        "fc_level": frame(np.array(LEVELS)[fc_rank]),
        "fc_eta_min": frame(leads[first]),
        "fc_acc_1h": frame(fc_acc[:, :, -1]),
    }


def score(grid, hotspots, motion=None):
    """Risk per hotspot and time step, plus the next-hour forecast if `motion` is given."""
    rate = pd.DataFrame(
        sample_grid(grid, hotspots.lat, hotspots.lon).T,
        index=pd.DatetimeIndex(grid.time.values),
        columns=hotspots.id,
    ).fillna(0.0)
    hours_per_step = (rate.index[1] - rate.index[0]) / pd.Timedelta("1h")
    acc_1h = (rate * hours_per_step).rolling("1h").sum()
    acc_3h = (rate * hours_per_step).rolling("3h").sum()

    vuln = hotspots.set_index("id").vulnerability
    level = pd.DataFrame(
        np.array(LEVELS)[_rank(acc_1h.values, acc_3h.values, vuln[rate.columns].values)],
        index=rate.index,
        columns=rate.columns,
    )
    risk = np.clip(
        np.maximum(acc_1h / THRESHOLDS["high"][0], acc_3h / THRESHOLDS["high"][1]).mul(vuln),
        0,
        1,
    )

    columns = {"rain_rate": rate, "acc_1h": acc_1h, "acc_3h": acc_3h, "risk": risk, "level": level}
    if motion is not None:
        columns.update(_forecast(grid, motion, hotspots.set_index("id").loc[rate.columns], rate))
    return _long(columns)


def alerts(risk, hotspots):
    """Alerts with SMS-style messages.

    "observed": a hotspot's level went up. "forecast": the nowcast expects a
    higher level within the hour than the hotspot has reached or been warned
    about so far.
    """
    names = hotspots.set_index("id").name
    has_forecast = "fc_level" in risk
    result = []
    for hotspot_id, group in risk.sort_values("time").groupby("hotspot_id"):
        name = names[hotspot_id]
        previous, warned = 0, 0
        for row in group.itertuples():
            observed = RANK[row.level]
            if has_forecast and RANK[row.fc_level] > max(observed, warned):
                warned = RANK[row.fc_level]
                eta = int(row.fc_eta_min)
                result.append({
                    "time": row.time.isoformat(),
                    "hotspot_id": hotspot_id,
                    "name": name,
                    "kind": "forecast",
                    "level": row.fc_level,
                    "eta_min": eta,
                    "acc_1h": round(row.fc_acc_1h, 1),
                    "message": (
                        f"Signal-to-Rain WARNING: {row.fc_level.upper()} flood risk expected in {name} "
                        f"in about {eta} min. About {row.fc_acc_1h:.0f} mm of rain forecast in the "
                        "next hour. Clear drains and stay away from low-lying roads."
                    ),
                })
            if observed > previous:
                result.append({
                    "time": row.time.isoformat(),
                    "hotspot_id": hotspot_id,
                    "name": name,
                    "kind": "observed",
                    "level": row.level,
                    "eta_min": None,
                    "acc_1h": round(row.acc_1h, 1),
                    "message": (
                        f"Signal-to-Rain: {row.level.upper()} flood risk in {name} now. "
                        f"{row.acc_1h:.0f} mm of rain in the last hour. Avoid drains and low-lying roads."
                    ),
                })
            previous = observed
            warned = max(warned, observed)
    return sorted(result, key=lambda a: (a["time"], a["kind"] != "forecast"))


def warning_performance(alert_list):
    """How much earlier the forecast warned than the observed alert, per hotspot and level.

    A warning is a hit if that level (or higher) is observed within HIT_WINDOW,
    otherwise a false alarm. An observed level with no earlier warning is a miss.
    """
    df = pd.DataFrame(alert_list)
    if df.empty:
        return None
    df["time"] = pd.to_datetime(df.time)
    df["rank"] = df.level.map(RANK)
    observed, forecast = df[df.kind == "observed"], df[df.kind == "forecast"]
    leads, false_alarms, misses = [], 0, 0
    for w in forecast.itertuples():
        reached = observed[(observed.hotspot_id == w.hotspot_id) & (observed["rank"] >= w.rank)
                           & (observed.time >= w.time)]
        if len(reached) and reached.time.min() - w.time <= HIT_WINDOW:
            leads.append((reached.time.min() - w.time) / pd.Timedelta("1min"))
        else:
            false_alarms += 1
    for o in observed.itertuples():
        earlier = forecast[(forecast.hotspot_id == o.hotspot_id) & (forecast["rank"] >= o.rank)
                           & (forecast.time <= o.time)]
        misses += earlier.empty
    return {
        "warnings": int(len(forecast)),
        "hits": len(leads),
        "false_alarms": false_alarms,
        "missed": int(misses),
        "median_lead_min": float(np.median(leads)) if leads else None,
        "min_lead_min": float(np.min(leads)) if leads else None,
    }
