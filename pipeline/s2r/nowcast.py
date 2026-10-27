"""Nowcasting: move the current rainfall map along the storm's motion to see 0-60 min ahead.

This is the simplest useful nowcast (Lagrangian persistence): rain keeps its
shape and intensity and drifts with one motion vector for the whole map. Real
nowcasting systems (e.g. pysteps) use a motion field and let intensity grow
and decay; this is the hackathon version of the same idea.

The motion comes in two steps:

1. Every few minutes, measure the shift that best lines up the map with the
   map `LAG_MIN` earlier (global Lucas-Kanade), with an error estimate: larger
   along a long rain band (where sliding the band changes nothing) and when
   the rain is at the edge of the network (a storm entering looks like it is
   growing, not moving).
2. A Kalman filter combines those measurements with the motion so far,
   trusting each one according to its error. It uses only the past, so it
   would work live, and it gives the uncertainty of the speed, which turns
   into a time range on warnings.

Grid convention: rows run south to north, columns west to east, so a motion
of (dy, dx) cells per minute is (northward, eastward).
"""

import numpy as np
import pandas as pd
from scipy import ndimage

KM_PER_DEG = 111.0
LAG_MIN = 5           # compare the map with the map this many minutes earlier
EVERY_MIN = 5         # measure motion this often
MAX_SPEED_KMH = 90.0
MIN_RAIN_FRACTION = 0.05  # need this share of cells above 1 mm/h to try a match
EDGE_CELLS = 3            # rain this close to the edge of coverage counts as "at the edge"

# Kalman filter settings, in km/h. Picked from a small sweep: on OpenMRG all
# combinations scored within 0.01 CSI of each other; this one also held up best
# on the synthetic storm, whose first matches are biased by the network layout.
MEASUREMENT_SD_KMH = 4.0      # error of one match on a storm well inside the network
DRIFT_SD_KMH_PER_MIN = 0.3    # how quickly a storm's real motion can change
START_SD_KMH = 10.0           # before the first match: assume a slow storm, don't jump to the first reading


def cell_km(grid):
    lat = grid.lat.values
    lon = grid.lon.values
    dy = (lat[1] - lat[0]) * KM_PER_DEG
    dx = (lon[1] - lon[0]) * KM_PER_DEG * np.cos(np.deg2rad(lat.mean()))
    return dy, dx


def _shift_between(a, b, iterations=8, smooth_cells=2.0, ridge=2e-2):
    """Shift (dy, dx) in cells that best moves field `a` onto field `b`, and its error shape.

    Global Lucas-Kanade: one translation for the whole map, from the image
    gradients, refined by warping `a` and solving again. Along a long rain
    band the gradients carry no information, and the small ridge term keeps
    that component near zero instead of letting it wander.

    The error shape is the inverse of the gradient matrix, scaled so an evenly
    textured map gives the identity: it is stretched along a rain band.
    Returns None when there is too little overlap to match.
    """
    valid = ~np.isnan(a) & ~np.isnan(b)
    valid = ndimage.binary_erosion(valid, iterations=3)  # stay clear of coverage edges
    if valid.sum() < 50:
        return None
    a = ndimage.gaussian_filter(np.nan_to_num(a), smooth_cells)
    b = ndimage.gaussian_filter(np.nan_to_num(b), smooth_cells)

    d = np.zeros(2)
    for _ in range(iterations):
        warped = ndimage.shift(a, d, order=1, mode="nearest")
        gy, gx = np.gradient((warped + b) / 2)
        it = (b - warped)[valid]
        gy, gx = gy[valid], gx[valid]
        h = np.array([[gy @ gy, gy @ gx], [gy @ gx, gx @ gx]])
        step = np.linalg.solve(h + ridge * np.trace(h) * np.eye(2), -np.array([gy @ it, gx @ it]))
        d += step
        if np.abs(step).max() < 0.01:
            break
    # Error shape from the undamped gradients, so a long band really is uncertain along itself
    shape = np.linalg.inv(h + 1e-6 * np.trace(h) * np.eye(2)) * np.trace(h) / 2
    return d, shape


def _edge_share(field):
    """Share of the rain (above 1 mm/h) lying within EDGE_CELLS of the edge of coverage."""
    valid = ~np.isnan(field)
    rain = valid & (np.nan_to_num(field) > 1)
    if not rain.any():
        return 1.0
    inner = ndimage.binary_erosion(valid, iterations=EDGE_CELLS, border_value=0)
    return float((rain & ~inner).sum() / rain.sum())


def estimate_motion(grid):
    """Storm motion per time step as a DataFrame.

    Columns: dy, dx [cells/min], speed_kmh, bearing_deg (compass direction the
    rain moves towards, 0 = north, 90 = east), speed_sd_kmh (one standard
    deviation of the speed), and measured (whether a match was used at that step).
    """
    times = pd.DatetimeIndex(grid.time.values)
    step_min = (times[1] - times[0]) / pd.Timedelta("1min")
    lag = max(1, int(round(LAG_MIN / step_min)))
    every = max(1, int(round(EVERY_MIN / step_min)))
    km_y, km_x = cell_km(grid)
    to_kmh = np.array([km_y, km_x]) * 60 / (lag * step_min)  # cells per lag -> km/h

    # Kalman filter on the velocity (north, east) in km/h, constant-velocity model
    x = np.zeros(2)
    p = np.eye(2) * START_SD_KMH**2
    q = np.eye(2) * DRIFT_SD_KMH_PER_MIN**2 * step_min
    fields = grid.values
    rows = []
    for i in range(len(times)):
        if i:
            p = p + q
        measured = False
        a, b = fields[i - lag], fields[i]
        if i >= lag and (i - lag) % every == 0 and min(np.nanmean(a > 1), np.nanmean(b > 1)) >= MIN_RAIN_FRACTION:
            match = _shift_between(a, b)
            if match is not None:
                d, shape = match
                z = d * to_kmh
                if np.hypot(*z) <= MAX_SPEED_KMH:  # faster than any storm: a bad match
                    # A storm entering the network looks like it is growing rather than moving
                    edge = _edge_share(b)
                    r = MEASUREMENT_SD_KMH**2 * shape * (1 + (edge / 0.25) ** 2)
                    gain = p @ np.linalg.inv(p + r)
                    x = x + gain @ (z - x)
                    p = (np.eye(2) - gain) @ p
                    measured = True
        speed = float(np.hypot(*x))
        along = x / speed if speed > 0.5 else np.array([np.sqrt(0.5), np.sqrt(0.5)])
        rows.append((x[0] / (km_y * 60), x[1] / (km_x * 60), speed,
                     float(np.degrees(np.arctan2(x[1], x[0])) % 360),
                     float(np.sqrt(along @ p @ along)), measured))
    return pd.DataFrame(rows, index=times,
                        columns=["dy", "dx", "speed_kmh", "bearing_deg", "speed_sd_kmh", "measured"])


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
