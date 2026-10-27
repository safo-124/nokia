"""Rain rate per link to a gridded rainfall map, by inverse distance weighting.

Each link is represented by its midpoint. That is the simplest approach and
good enough for a demo; better options (several points per link, kriging)
can replace `idw_grid` without changing its inputs or outputs.
"""

import numpy as np
import xarray as xr
from scipy.spatial import cKDTree

KM_PER_DEG = 111.0


def make_grid(lat_min, lat_max, lon_min, lon_max, cell_km=0.5, pad_km=1.0):
    pad_lat = pad_km / KM_PER_DEG
    pad_lon = pad_km / (KM_PER_DEG * np.cos(np.deg2rad((lat_min + lat_max) / 2)))
    lat = np.arange(lat_min - pad_lat, lat_max + pad_lat, cell_km / KM_PER_DEG)
    lon_step = cell_km / (KM_PER_DEG * np.cos(np.deg2rad(lat.mean())))
    lon = np.arange(lon_min - pad_lon, lon_max + pad_lon, lon_step)
    return lat, lon


def _to_km(lat, lon, lat0):
    return np.column_stack([lon * KM_PER_DEG * np.cos(np.deg2rad(lat0)), lat * KM_PER_DEG])


def idw_grid(r_link, mid_lat, mid_lon, lat, lon, power=2.0, n_near=8, max_km=6.0):
    """Interpolate link rain rates (cml_id, time) onto a lat/lon grid.

    Returns a DataArray (time, lat, lon) in mm/h. Grid cells further than
    `max_km` from every link are NaN, so the map does not invent rain where
    there is no network coverage.
    """
    lat0 = float(np.mean(mid_lat))
    tree = cKDTree(_to_km(mid_lat, mid_lon, lat0))
    grid_lat, grid_lon = np.meshgrid(lat, lon, indexing="ij")
    k = min(n_near, len(mid_lat))
    dist, idx = tree.query(_to_km(grid_lat.ravel(), grid_lon.ravel(), lat0), k=k)
    dist, idx = dist.reshape(len(dist), k), idx.reshape(len(idx), k)

    weights = 1.0 / np.maximum(dist, 0.05) ** power  # (cell, k)
    weights[dist > max_km] = 0.0

    values = r_link.transpose("time", "cml_id").values[:, idx]  # (time, cell, k)
    valid = ~np.isnan(values)
    w = np.where(valid, weights[None], 0.0)
    w_sum = w.sum(-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        field = np.where(w_sum > 0, (w * np.nan_to_num(values)).sum(-1) / w_sum, np.nan)

    return xr.DataArray(
        field.reshape(len(r_link.time), len(lat), len(lon)).astype("float32"),
        coords={"time": r_link.time.values, "lat": lat, "lon": lon},
        dims=("time", "lat", "lon"),
        name="rain_rate",
        attrs={"units": "mm/h"},
    )


def sample_grid(grid, lat, lon):
    """Time series of the grid at points (nearest cell), dims (point, time)."""
    lat_idx = np.abs(grid.lat.values[None, :] - np.asarray(lat)[:, None]).argmin(1)
    lon_idx = np.abs(grid.lon.values[None, :] - np.asarray(lon)[:, None]).argmin(1)
    return grid.values[:, lat_idx, lon_idx].T
