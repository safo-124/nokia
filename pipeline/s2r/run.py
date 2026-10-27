"""Run the whole pipeline and store the results in PostgreSQL.

    python -m s2r.run                                  # synthetic Accra storm
    python -m s2r.run --source openmrg                 # real Gothenburg data
    python -m s2r.run --source openmrg --wet-dry std --dataset openmrg-28jul \\
        --start 2015-07-28T10:00 --end 2015-07-28T18:00
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import data, db, flood, interpolate, nowcast, quality, rain, wetdry

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_HOTSPOTS = {"synthetic": DATA_DIR / "hotspots" / "accra.geojson"}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Signal-to-Rain processing pipeline")
    p.add_argument("--source", choices=["synthetic", "openmrg"], default="synthetic")
    p.add_argument("--dataset", help="Name to store the results under (default: the source)")
    p.add_argument("--wet-dry", choices=["auto", "std", "ml"], default="auto",
                   help="std: rolling standard deviation rule; ml: trained classifier; "
                        "auto: ml when there is reference rain to train on, else std")
    p.add_argument("--start", help="Start of the time window (OpenMRG only)")
    p.add_argument("--end", help="End of the time window (OpenMRG only)")
    p.add_argument("--hotspots", type=Path, help="GeoJSON of flood hotspots")
    p.add_argument("--raw", type=Path, default=DATA_DIR / "raw")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    print(f"Loading {args.source} data")
    if args.source == "synthetic":
        cmls, gauges = data.load_synthetic()
    else:
        cmls, gauges = data.load_openmrg(args.raw / "openmrg", args.start, args.end)
    print(f"  {cmls.sizes['cml_id']} links, {gauges.sizes['id']} gauges, "
          f"{cmls.sizes['time']} time steps")

    trsl = rain.trsl(cmls)
    scores = None
    if "R_ref" in cmls:
        print("Scoring wet/dry methods against the reference (links held out)")
        model, scores = wetdry.evaluate(trsl, cmls.R_ref)
        print("  " + json.dumps(scores))
    method = args.wet_dry
    if method == "auto":
        method = "ml" if "R_ref" in cmls else "std"
    if method == "ml":
        if "R_ref" not in cmls:
            raise SystemExit("--wet-dry ml needs a reference rain rate to train on")
        wet = wetdry.widen(wetdry.predict(model, trsl))
    else:
        wet = wetdry.rolling_std(trsl)
    print(f"  using {method} for wet/dry")

    print("Estimating rain rate per link")
    cmls = rain.estimate_rain_rate(cmls, wet)
    r_link = rain.link_rain_rate(cmls)
    wet_link = cmls.wet.any("sublink_id")

    print("Checking link quality")
    link_quality = quality.check_links(cmls, r_link)
    r_link, spikes = quality.apply(r_link, link_quality)
    quality_meta = quality.summary(link_quality, spikes)
    print(f"  excluded {quality_meta['excluded']} of {quality_meta['links']} links "
          f"{quality_meta['by_reason']}, removed {spikes} impossible readings")

    print("Interpolating rainfall map")
    mid_lat = ((cmls.site_0_lat + cmls.site_1_lat) / 2).values
    mid_lon = ((cmls.site_0_lon + cmls.site_1_lon) / 2).values
    lats = np.concatenate([cmls.site_0_lat.values, cmls.site_1_lat.values])
    lons = np.concatenate([cmls.site_0_lon.values, cmls.site_1_lon.values])
    lat, lon = interpolate.make_grid(lats.min(), lats.max(), lons.min(), lons.max())
    grid = interpolate.idw_grid(r_link, mid_lat, mid_lon, lat, lon)
    gauge_estimate = interpolate.sample_grid(grid, gauges.lat.values, gauges.lon.values)

    print("Nowcasting: estimating storm motion")
    motion = nowcast.estimate_motion(grid)
    nowcast_meta = {"skill": [nowcast.skill(grid, motion, lead_min=lead) for lead in (15, 30, 60)]}
    for s in nowcast_meta["skill"]:
        print(f"  +{s['lead_min']} min CSI: nowcast {s['csi']['nowcast']}, "
              f"persistence {s['csi']['persistence']}")

    hotspots_path = args.hotspots or DEFAULT_HOTSPOTS.get(args.source)
    hotspots = risk = alert_list = None
    if hotspots_path:
        print(f"Scoring flood risk for {hotspots_path.name}")
        hotspots = flood.load_hotspots(hotspots_path)
        risk = flood.score(grid, hotspots, motion)
        alert_list = flood.alerts(risk, hotspots, motion)
        nowcast_meta["warnings"] = flood.warning_performance(alert_list)
        print(f"  {len(alert_list)} alerts; early warnings: {json.dumps(nowcast_meta['warnings'])}")

    meta = {
        "source": args.source,
        "region": cmls.attrs.get("region", ""),
        "bounds": [float(lat.min()), float(lat.max()), float(lon.min()), float(lon.max())],
        "n_links": int(cmls.sizes["cml_id"]),
        "n_gauges": int(gauges.sizes["id"]),
        "wet_dry_method": method,
        "wet_dry_scores": scores,
        "has_flood_risk": hotspots is not None,
        "nowcast": nowcast_meta,
        "quality": quality_meta,
        "generated_at": datetime.now(timezone.utc).strftime(db.TIME_FORMAT),
    }
    dataset = args.dataset or args.source
    print(f"Saving dataset '{dataset}' to PostgreSQL")
    with db.connect() as conn:
        db.save(
            conn,
            dataset,
            meta=meta,
            cmls=cmls,
            link_quality=link_quality,
            r_link=r_link,
            wet_link=wet_link,
            gauges=gauges,
            gauge_estimate=gauge_estimate,
            grid=grid,
            motion=motion,
            hotspots=hotspots,
            risk=risk,
            alert_list=alert_list,
        )
    print("Done")


if __name__ == "__main__":
    main()
