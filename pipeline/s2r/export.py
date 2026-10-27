"""Write pipeline results as plain files that the backend serves.

data/processed/
    meta.json           source, region, bounds, time steps, wet/dry scores
    links.geojson       one LineString per link
    link_rain.csv       time, cml_id, rain_rate [mm/h], wet
    gauges.geojson      rain gauge locations
    gauge_rain.csv      time, gauge_id, gauge [mm/h], estimate [mm/h]
    grid.npz            lat, lon, rain_rate (time, lat, lon) [mm/h]
    hotspots.geojson    flood hotspots (only with --hotspots)
    flood_risk.csv      time, hotspot_id, rain_rate, acc_1h, acc_3h, risk, level
    alerts.json         simulated SMS alerts
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)


def _links_geojson(cmls):
    features = []
    for cml_id in cmls.cml_id.values:
        c = cmls.sel(cml_id=cml_id)
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [float(c.site_0_lon), float(c.site_0_lat)],
                        [float(c.site_1_lon), float(c.site_1_lat)],
                    ],
                },
                "properties": {
                    "id": str(cml_id),
                    "length_km": round(float(c.length), 2),
                    "frequency_ghz": round(float(c.frequency.mean()), 1),
                    "polarization": str(np.atleast_1d(c.polarization.values)[0]),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _points_geojson(ids, lat, lon, extra=None):
    features = []
    for i, (pid, y, x) in enumerate(zip(ids, lat, lon)):
        props = {"id": str(pid)}
        if extra is not None:
            props.update({k: v[i] for k, v in extra.items()})
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(x), float(y)]},
                "properties": props,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def write_outputs(out_dir, *, meta, cmls, r_link, wet_link, gauges, gauge_estimate, grid,
                  hotspots=None, risk=None, alert_list=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    times = pd.DatetimeIndex(grid.time.values)

    meta = {**meta, "times": [t.strftime(TIME_FORMAT) for t in times]}
    _write_json(out / "meta.json", meta)
    _write_json(out / "links.geojson", _links_geojson(cmls))

    link_rain = r_link.to_dataframe(name="rain_rate").reset_index()
    link_rain["wet"] = wet_link.transpose(*r_link.dims).values.reshape(-1)
    link_rain["rain_rate"] = link_rain.rain_rate.round(2)
    link_rain[["time", "cml_id", "rain_rate", "wet"]].to_csv(
        out / "link_rain.csv", index=False, date_format=TIME_FORMAT
    )

    _write_json(
        out / "gauges.geojson",
        _points_geojson(gauges.id.values, gauges.lat.values, gauges.lon.values),
    )
    gauge_rain = pd.DataFrame(
        {
            "time": np.tile(gauges.time.values, len(gauges.id)),
            "gauge_id": np.repeat(gauges.id.values, len(gauges.time)),
            "gauge": gauges.rainfall_rate.transpose("id", "time").values.reshape(-1).round(2),
            "estimate": gauge_estimate.reshape(-1).round(2),
        }
    )
    gauge_rain.to_csv(out / "gauge_rain.csv", index=False, date_format=TIME_FORMAT)

    np.savez_compressed(
        out / "grid.npz",
        lat=grid.lat.values,
        lon=grid.lon.values,
        rain_rate=grid.values.astype("float32"),
    )

    for name in ("hotspots.geojson", "flood_risk.csv", "alerts.json"):
        (out / name).unlink(missing_ok=True)
    if hotspots is not None:
        _write_json(
            out / "hotspots.geojson",
            _points_geojson(
                hotspots.id, hotspots.lat, hotspots.lon,
                extra={"name": list(hotspots.name), "vulnerability": list(hotspots.vulnerability)},
            ),
        )
        risk = risk.copy()
        for col in ("rain_rate", "acc_1h", "acc_3h", "risk"):
            risk[col] = risk[col].astype(float).round(2)
        risk.to_csv(out / "flood_risk.csv", index=False, date_format=TIME_FORMAT)
        _write_json(out / "alerts.json", alert_list)
