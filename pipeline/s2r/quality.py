"""Link quality checks: find links whose rain can't be trusted and leave them out of the map.

Each excluded link gets one reason, checked in this order:

- no data: the link reported nothing for most of the window.
- too short: on links under MIN_LENGTH_KM, water on the antennas and
  0.1 dB rounding are a large part of the measured loss, and dividing by a
  tiny length turns them into tens of mm/h of fake rain.
- noisy: the signal varies more in dry weather than the wet/dry rule's
  threshold, so the link can't tell rain from noise.
- disagrees with neighbours: far more rain over the event than the links
  around it, which rain doesn't do over a few kilometres.

Single readings above MAX_RAIN_MM_H are removed even on links that pass.
The thresholds are demo choices checked on OpenMRG and the synthetic data,
not values from the literature.
"""

import warnings

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .wetdry import _steps

MAX_MISSING = 0.5
MIN_LENGTH_KM = 0.5
MAX_DRY_NOISE_DB = 0.8        # same as the rolling-std wet/dry threshold
NEIGHBOUR_KM = 5.0
NEIGHBOUR_RATIO = 4.0         # times the median total of the links around it
NEIGHBOUR_MIN_EXCESS_MM = 10.0
MAX_RAIN_MM_H = 200.0
KM_PER_DEG = 111.0


def dry_noise_db(trsl):
    """Typical short-term signal variation in dry weather, per link [dB].

    The 25th percentile over time of the 15-minute rolling standard
    deviation, so it reflects quiet periods without needing a wet/dry
    classification. The worse of the two sublinks counts.
    """
    n = _steps(trsl, "15min")
    std = trsl.rolling(time=n, center=True, min_periods=n // 2).std()
    with warnings.catch_warnings():  # links with no data at all give NaN, which is fine
        warnings.simplefilter("ignore", RuntimeWarning)
        return std.quantile(0.25, dim="time").max("sublink_id")


def check_links(cmls, r_link):
    """One row per link: the measures and the reason it is excluded (None if kept)."""
    hours_per_step = (cmls.time.values[1] - cmls.time.values[0]) / np.timedelta64(1, "h")
    q = pd.DataFrame(
        {
            "missing": cmls.trsl.isnull().any("sublink_id").mean("time").values,
            "length_km": cmls.length.values,
            "noise_db": dry_noise_db(cmls.trsl).values,
            "total_mm": (r_link.fillna(0) * hours_per_step).sum("time").values,
        },
        index=cmls.cml_id.values.astype(str),
    )
    q["reason"] = None
    q.loc[q.missing > MAX_MISSING, "reason"] = "no data"
    q.loc[q.reason.isna() & (q.length_km < MIN_LENGTH_KM), "reason"] = "too short"
    q.loc[q.reason.isna() & (q.noise_db > MAX_DRY_NOISE_DB), "reason"] = "noisy"

    # Compare each link's event total with the median of the kept links around it
    mid_lat = ((cmls.site_0_lat + cmls.site_1_lat) / 2).values
    mid_lon = ((cmls.site_0_lon + cmls.site_1_lon) / 2).values
    xy = np.column_stack([mid_lon * KM_PER_DEG * np.cos(np.deg2rad(mid_lat.mean())), mid_lat * KM_PER_DEG])
    kept = q.reason.isna().values
    q["neighbour_mm"] = np.nan
    for i, nbrs in enumerate(cKDTree(xy).query_ball_point(xy, r=NEIGHBOUR_KM)):
        nbrs = [j for j in nbrs if j != i and kept[j]]
        if len(nbrs) >= 3:
            q.iloc[i, q.columns.get_loc("neighbour_mm")] = np.median(q.total_mm.values[nbrs])
    odd = (q.total_mm > NEIGHBOUR_RATIO * q.neighbour_mm) & (q.total_mm - q.neighbour_mm > NEIGHBOUR_MIN_EXCESS_MM)
    q.loc[q.reason.isna() & odd, "reason"] = "disagrees with neighbours"
    return q


def describe(row):
    """Plain-language reason for the map tooltip."""
    return {
        "no data": f"no data for {row.missing:.0%} of the time",
        "too short": f"too short ({row.length_km:.2f} km): antenna wetting errors dominate",
        "noisy": f"noisy in dry weather ({row.noise_db:.1f} dB, rule needs under {MAX_DRY_NOISE_DB})",
        "disagrees with neighbours": (
            f"{row.total_mm:.0f} mm against {row.neighbour_mm:.0f} mm for nearby links"
        ),
    }[row.reason]


def apply(r_link, quality):
    """Rain per link with excluded links and impossible readings set to NaN."""
    excluded = quality.index[quality.reason.notna()]
    filtered = r_link.where(~r_link.cml_id.astype(str).isin(excluded))
    spikes = int((filtered > MAX_RAIN_MM_H).sum())
    return filtered.where(~(filtered > MAX_RAIN_MM_H)), spikes


def summary(quality, spikes):
    reasons = quality.reason.dropna()
    return {
        "links": int(len(quality)),
        "excluded": int(len(reasons)),
        "by_reason": {k: int(v) for k, v in reasons.value_counts().items()},
        "readings_removed": spikes,
    }
