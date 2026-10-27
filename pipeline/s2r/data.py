"""Data loaders. Each returns (cmls, gauges) in the layout described in `s2r.synthetic`.

`cmls.R_ref` is a reference rain rate along each link (synthetic truth or
radar). It is used to train and score the wet/dry classifier, never as input
to the rain-rate estimate itself.
"""

import numpy as np
import xarray as xr

from . import synthetic

# The wettest night in the OpenMRG 8-day sample, with two dry hours before it
# so the baseline has something to settle on.
OPENMRG_DEFAULT_WINDOW = ("2015-07-25T22:00", "2015-07-26T06:00")


def load_synthetic():
    return synthetic.make_dataset()


def load_openmrg(raw_dir, start=None, end=None, subset="8d"):
    """OpenMRG (Gothenburg, July 2015): 364 links, municipal gauges and SMHI radar.

    Downloads about 28 MB into `raw_dir` on first use.
    """
    import poligrain as plg

    start = start or OPENMRG_DEFAULT_WINDOW[0]
    end = end or OPENMRG_DEFAULT_WINDOW[1]
    window = slice(start, end)
    radar, cmls, gauges, _ = plg.example_data.load_openmrg(data_dir=str(raw_dir), subset=subset)

    # Native resolution is 10 s; 1 min is plenty for rainfall and much faster
    cmls = cmls[["tsl", "rsl"]].sel(time=window).resample(time="1min").mean()
    cmls = cmls.transpose("cml_id", "sublink_id", "time")
    cmls = cmls.assign_coords(
        cml_id=cmls.cml_id.astype(str),
        frequency=cmls.frequency.transpose("cml_id", "sublink_id") / 1000,  # MHz to GHz
        polarization=cmls.polarization.transpose("cml_id", "sublink_id").str.upper(),
        length=cmls.length / 1000,  # m to km
    )
    cmls.attrs = {"source": "openmrg", "region": "Gothenburg"}

    # Radar rain rate averaged along each link path, as the reference
    radar_rate = radar.R.sel(time=window)
    along_links = plg.spatial.GridAtLines(radar_rate, cmls, use_lon_lat=True)
    r_ref = along_links(radar_rate).reindex(time=cmls.time, method="ffill")
    cmls["R_ref"] = r_ref.transpose("cml_id", "time").reset_coords(drop=True)

    g = gauges.sel(time=window)
    hours_per_step = (g.time.values[1] - g.time.values[0]) / np.timedelta64(1, "h")
    gauges = xr.Dataset(
        data_vars={
            "rainfall_rate": (("id", "time"), g.rainfall_amount.transpose("id", "time").values / hours_per_step)
        },
        coords={"id": g.id.values.astype(str), "time": g.time.values, "lat": ("id", g.lat.values), "lon": ("id", g.lon.values)},
    ).reindex(time=cmls.time)
    return cmls, gauges
