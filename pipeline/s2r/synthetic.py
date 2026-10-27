"""Synthetic microwave link network and storm over Accra.

Lets the whole stack run before real data is loaded, and doubles as the Ghana
mock-up. The output has the same layout as the real-data loaders in `s2r.data`:

    cmls:   dims (cml_id, sublink_id, time)
            data vars tsl, rsl [dBm], R_ref [mm/h] (true path-averaged rain)
            coords site_0_lat/lon, site_1_lat/lon, length [km],
            frequency [GHz], polarization ("H"/"V")
    gauges: dims (id, time), data var rainfall_rate [mm/h], coords lat, lon
"""

import numpy as np
import pandas as pd
import xarray as xr
from pycomlink.processing.k_R_relation import a_b
from scipy.spatial import cKDTree

# Box around Greater Accra: lat_min, lat_max, lon_min, lon_max
ACCRA_BOUNDS = (5.53, 5.68, -0.32, -0.10)
KM_PER_DEG = 111.0


def rain_rate(lat, lon, minutes, bounds=ACCRA_BOUNDS, start=120, end=300):
    """Rain rate [mm/h] of a squall line crossing the box from east to west.

    West African squall lines usually travel westward: a narrow convective line
    in front, followed by a wide band of light stratiform rain.

    lat, lon: arrays of shape (n,); minutes: array of shape (t,).
    Returns an array of shape (t, n).
    """
    lat_min, lat_max, lon_min, lon_max = bounds
    lat = np.asarray(lat)[None, :]
    lon = np.asarray(lon)[None, :]
    minutes = np.asarray(minutes, dtype=float)[:, None]

    progress = (minutes - start) / (end - start)
    lon_front = lon_max + 0.05 - progress * (lon_max - lon_min + 0.10)
    lat_centre = (lat_min + lat_max) / 2 + 0.02 * progress
    active = (minutes >= start) & (minutes <= end)

    cos_lat = np.cos(np.deg2rad(lat))
    dy = (lat - lat_centre) * KM_PER_DEG

    def cell(peak, lon_offset, r_ew_km, r_ns_km):
        dx = (lon - (lon_front + lon_offset)) * KM_PER_DEG * cos_lat
        return peak * np.exp(-0.5 * ((dx / r_ew_km) ** 2 + (dy / r_ns_km) ** 2))

    convective = cell(peak=95.0, lon_offset=0.0, r_ew_km=3.5, r_ns_km=14.0)
    stratiform = cell(peak=7.0, lon_offset=0.09, r_ew_km=10.0, r_ns_km=25.0)
    return np.where(active, convective + stratiform, 0.0)


def _make_links(rng, n_sites, bounds):
    lat_min, lat_max, lon_min, lon_max = bounds
    lat = rng.uniform(lat_min, lat_max, n_sites)
    lon = rng.uniform(lon_min, lon_max, n_sites)
    xy_km = np.column_stack(
        [lon * KM_PER_DEG * np.cos(np.deg2rad(lat.mean())), lat * KM_PER_DEG]
    )

    # Connect every site to its two nearest neighbours, like a backhaul mesh
    _, neighbours = cKDTree(xy_km).query(xy_km, k=3)
    pairs = {tuple(sorted((i, j))) for i, row in enumerate(neighbours) for j in row[1:]}
    pairs = sorted(pairs)
    length = np.array([np.linalg.norm(xy_km[i] - xy_km[j]) for i, j in pairs])
    keep = (length > 0.5) & (length < 10.0)
    pairs = [p for p, k in zip(pairs, keep) if k]
    return lat, lon, pairs, length[keep]


def _frequency_for_length(length_km):
    # Short hops use high bands, long hops low bands, as in real networks
    return np.select(
        [length_km < 2, length_km < 4, length_km < 7], [38.0, 23.0, 18.0], default=15.0
    )


def make_dataset(n_sites=60, n_gauges=6, hours=6, bounds=ACCRA_BOUNDS, seed=42):
    """Return (cmls, gauges) for a synthetic storm at 1-minute resolution."""
    rng = np.random.default_rng(seed)
    time = pd.date_range("2026-06-15 12:00", periods=hours * 60, freq="1min")
    minutes = np.arange(len(time))

    site_lat, site_lon, pairs, length = _make_links(rng, n_sites, bounds)
    n_cml = len(pairs)
    i0 = np.array([p[0] for p in pairs])
    i1 = np.array([p[1] for p in pairs])

    # Path-averaged rain: sample the rain field at points along each link
    frac = np.linspace(0, 1, 12)
    pts_lat = site_lat[i0][:, None] + frac * (site_lat[i1] - site_lat[i0])[:, None]
    pts_lon = site_lon[i0][:, None] + frac * (site_lon[i1] - site_lon[i0])[:, None]
    r_pts = rain_rate(pts_lat.ravel(), pts_lon.ravel(), minutes, bounds)
    r_pts = r_pts.reshape(len(time), n_cml, len(frac))  # (time, cml, point)

    base_freq = _frequency_for_length(length)
    frequency = np.stack([base_freq, base_freq + 1.0], axis=1)  # duplex pair
    polarization = rng.choice(["H", "V"], size=n_cml)
    pol_2d = np.repeat(polarization[:, None], 2, axis=1)
    a, b = a_b(frequency, pol_2d)  # (cml, sublink)

    # Specific attenuation is a*R^b at each point, averaged along the path
    k = (a[None, :, :, None] * r_pts[:, :, None, :] ** b[None, :, :, None]).mean(-1)
    attenuation = k * length[None, :, None]  # (time, cml, sublink) in dB
    r_path = r_pts.mean(-1)  # (time, cml)

    tsl = np.round(rng.uniform(5, 20, size=(n_cml, 2)))
    path_loss = rng.uniform(40, 70, size=(n_cml, 2))
    noise_std = rng.uniform(0.1, 0.3, size=(n_cml, 2))
    noise_std[rng.random(n_cml) < 0.1] = 1.0  # a few links with strong multipath
    diurnal = 0.4 * np.sin(2 * np.pi * (minutes / (24 * 60)))[:, None, None]
    noise = rng.normal(0, 1, size=attenuation.shape) * noise_std[None]
    wet_antenna = 1.8 * (1 - np.exp(-r_path))[:, :, None]

    rsl = tsl[None] - path_loss[None] - diurnal - attenuation - wet_antenna + noise
    rsl = np.round(rsl, 1)  # equipment reports 0.1 dB steps

    cml_ids = [f"CML{i:03d}" for i in range(n_cml)]
    cmls = xr.Dataset(
        data_vars={
            "tsl": (("cml_id", "sublink_id", "time"), np.broadcast_to(tsl[:, :, None], (n_cml, 2, len(time))).copy()),
            "rsl": (("cml_id", "sublink_id", "time"), rsl.transpose(1, 2, 0)),
            "R_ref": (("cml_id", "time"), r_path.T),
        },
        coords={
            "cml_id": cml_ids,
            "sublink_id": ["sublink_1", "sublink_2"],
            "time": time,
            "site_0_lat": ("cml_id", site_lat[i0]),
            "site_0_lon": ("cml_id", site_lon[i0]),
            "site_1_lat": ("cml_id", site_lat[i1]),
            "site_1_lon": ("cml_id", site_lon[i1]),
            "length": ("cml_id", length),
            "frequency": (("cml_id", "sublink_id"), frequency),
            "polarization": (("cml_id", "sublink_id"), pol_2d),
        },
        attrs={"source": "synthetic", "region": "Accra"},
    )

    lat_min, lat_max, lon_min, lon_max = bounds
    g_lat = rng.uniform(lat_min + 0.02, lat_max - 0.02, n_gauges)
    g_lon = rng.uniform(lon_min + 0.03, lon_max - 0.03, n_gauges)
    g_rain = rain_rate(g_lat, g_lon, minutes, bounds)
    g_rain = np.clip(g_rain * rng.normal(1, 0.1, g_rain.shape), 0, None)
    gauges = xr.Dataset(
        data_vars={"rainfall_rate": (("id", "time"), g_rain.T)},
        coords={
            "id": [f"G{i + 1}" for i in range(n_gauges)],
            "time": time,
            "lat": ("id", g_lat),
            "lon": ("id", g_lon),
        },
    )
    return cmls, gauges
