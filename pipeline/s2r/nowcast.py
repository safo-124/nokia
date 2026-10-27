"""Nowcasting: move the current rainfall map along the storm's motion to see 0-60 min ahead.

This is the simplest useful nowcast (Lagrangian persistence): rain keeps its
shape and intensity and drifts with one motion vector for the whole map. The
motion is the shift that best lines up the map with the map `LAG` minutes
earlier. Real nowcasting systems (e.g. pysteps) use a motion field and let
intensity grow and decay; this is the hackathon version of the same idea.

Grid convention: rows run south to north, columns west to east, so a motion
of (dy, dx) cells per minute is (northward, eastward).
"""

import numpy as np
import pandas as pd
from scipy import ndimage

KM_PER_DEG = 111.0
LAG_MIN = 5           # compare the map with the map this many minutes earlier
EVERY_MIN = 5         # estimate motion this often, hold in between
SMOOTH_MIN = 30       # median over this window, so one bad match doesn't flip the arrow
MAX_SPEED_KMH = 90.0
MIN_RAIN_FRACTION = 0.05  # need this share of cells above 1 mm/h to trust a match


def cell_km(grid):
    lat = grid.lat.values
    lon = grid.lon.values
    dy = (lat[1] - lat[0]) * KM_PER_DEG
    dx = (lon[1] - lon[0]) * KM_PER_DEG * np.cos(np.deg2rad(lat.mean()))
    return dy, dx


def _shift_between(a, b, iterations=8, smooth_cells=2.0, ridge=2e-2):
    """(dy, dx) in cells that best moves field `a` onto field `b`.

    Global Lucas-Kanade: one translation for the whole map, from the image
    gradients, refined by warping `a` and solving again. Along a long rain
    band the gradients carry no information, and the small ridge term keeps
    that component near zero instead of letting it wander, so a squall line
    gets the motion across the line, which is the part that matters.
    """
    valid = ~np.isnan(a) & ~np.isnan(b)
    valid = ndimage.binary_erosion(valid, iterations=3)  # stay clear of coverage edges
    if valid.sum() < 50:
        return 0.0, 0.0
    a = ndimage.gaussian_filter(np.nan_to_num(a), smooth_cells)
    b = ndimage.gaussian_filter(np.nan_to_num(b), smooth_cells)

    d = np.zeros(2)
    for _ in range(iterations):
        warped = ndimage.shift(a, d, order=1, mode="nearest")
        gy, gx = np.gradient((warped + b) / 2)
        it = (b - warped)[valid]
        gy, gx = gy[valid], gx[valid]
        h = np.array([[gy @ gy, gy @ gx], [gy @ gx, gx @ gx]])
        h += ridge * np.trace(h) * np.eye(2)
        step = np.linalg.solve(h, -np.array([gy @ it, gx @ it]))
        d += step
        if np.abs(step).max() < 0.01:
            break
    return float(d[0]), float(d[1])


def estimate_motion(grid):
    """Storm motion per time step as a DataFrame: dy, dx [cells/min], speed_kmh, bearing_deg.

    bearing_deg is the compass direction the rain is moving towards (0 = north,
    90 = east). Steps without enough rain to match get the last good estimate.
    """
    times = pd.DatetimeIndex(grid.time.values)
    step_min = (times[1] - times[0]) / pd.Timedelta("1min")
    lag = max(1, int(round(LAG_MIN / step_min)))
    every = max(1, int(round(EVERY_MIN / step_min)))
    km_y, km_x = cell_km(grid)
    max_cells_per_min = MAX_SPEED_KMH / 60 / min(km_y, km_x)

    fields = grid.values
    raw = pd.DataFrame(index=times, columns=["dy", "dx"], dtype=float)
    for i in range(lag, len(times), every):
        a, b = fields[i - lag], fields[i]
        if min(np.nanmean(a > 1), np.nanmean(b > 1)) < MIN_RAIN_FRACTION:
            continue
        dy, dx = np.array(_shift_between(a, b)) / (lag * step_min)
        if np.hypot(dy, dx) <= max_cells_per_min:  # faster than any storm: a bad match
            raw.iloc[i] = [dy, dx]

    motion = raw.rolling(f"{SMOOTH_MIN}min", min_periods=1).median().ffill().fillna(0.0)
    vy, vx = motion.dy * km_y * 60, motion.dx * km_x * 60  # km/h north, east
    motion["speed_kmh"] = np.hypot(vy, vx)
    motion["bearing_deg"] = np.degrees(np.arctan2(vx, vy)) % 360
    return motion


def shift_field(field, dy, dx):
    """Move a 2D field by (dy, dx) cells (rounded); cells with no source are NaN."""
    dy, dx = int(round(dy)), int(round(dx))
    out = np.full_like(field, np.nan)
    ny, nx = field.shape
    if abs(dy) >= ny or abs(dx) >= nx:
        return out
    src_y = slice(max(0, -dy), min(ny, ny - dy))
    dst_y = slice(max(0, dy), min(ny, ny + dy))
    src_x = slice(max(0, -dx), min(nx, nx - dx))
    dst_x = slice(max(0, dx), min(nx, nx + dx))
    out[dst_y, dst_x] = field[src_y, src_x]
    return out


def forecast_field(grid, motion, i, lead_min):
    """The map at time step `i` moved `lead_min` minutes ahead."""
    m = motion.iloc[i]
    return shift_field(grid.values[i], m.dy * lead_min, m.dx * lead_min)


def skill(grid, motion, lead_min=30, threshold=1.0):
    """Critical success index for rain above `threshold` mm/h, `lead_min` ahead.

    Compares the nowcast with persistence (assuming the map stays where it is),
    the baseline any nowcast has to beat. Only time steps with rain count.
    """
    times = pd.DatetimeIndex(grid.time.values)
    step_min = (times[1] - times[0]) / pd.Timedelta("1min")
    k = int(round(lead_min / step_min))
    hits = {"nowcast": np.zeros(3), "persistence": np.zeros(3)}  # hits, misses, false alarms
    for i in range(len(times) - k):
        observed = grid.values[i + k]
        if np.nanmean(observed > threshold) < MIN_RAIN_FRACTION:
            continue
        for name, fc in (("nowcast", forecast_field(grid, motion, i, lead_min)),
                         ("persistence", grid.values[i])):
            valid = ~np.isnan(fc) & ~np.isnan(observed)
            f, o = fc[valid] > threshold, observed[valid] > threshold
            hits[name] += [np.sum(f & o), np.sum(~f & o), np.sum(f & ~o)]
    csi = {name: round(float(h / (h + m + fa)), 3) if (h + m + fa) else None
           for name, (h, m, fa) in hits.items()}
    return {"lead_min": lead_min, "threshold_mm_h": threshold, "csi": csi}


def hotspot_rates(grid, motion, lat, lon, max_lead_min=60):
    """Forecast rain rate at points for every lead time.

    Returns an array (time, point, lead) in mm/h for leads of 1..max_lead steps.
    Looking up where the rain at a point will come from (the point moved
    backwards along the motion) is much cheaper than moving whole maps.
    """
    times = pd.DatetimeIndex(grid.time.values)
    step_min = (times[1] - times[0]) / pd.Timedelta("1min")
    leads = np.arange(1, int(round(max_lead_min / step_min)) + 1) * step_min
    row = np.abs(grid.lat.values[None, :] - np.asarray(lat)[:, None]).argmin(1)
    col = np.abs(grid.lon.values[None, :] - np.asarray(lon)[:, None]).argmin(1)
    ny, nx = grid.shape[1:]

    src_row = np.rint(row[None, :, None] - motion.dy.values[:, None, None] * leads).astype(int)
    src_col = np.rint(col[None, :, None] - motion.dx.values[:, None, None] * leads).astype(int)
    inside = (src_row >= 0) & (src_row < ny) & (src_col >= 0) & (src_col < nx)
    t_idx = np.broadcast_to(np.arange(len(times))[:, None, None], src_row.shape)
    rates = np.zeros(src_row.shape)
    rates[inside] = grid.values[t_idx[inside], src_row[inside], src_col[inside]]
    return np.nan_to_num(rates), leads
