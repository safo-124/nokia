"""Wet/dry classification: is a drop in signal level caused by rain?

Two methods share one interface, both returning a boolean DataArray shaped like
`trsl` (cml_id, sublink_id, time):

- `rolling_std`: the classic rule (Schleiss and Berne 2010), no training needed.
- `train_classifier` + `predict`: a gradient-boosted model, trained against a
  reference such as gauges, radar or synthetic truth.

The model sees each link's own signal and what the links around it are doing,
at three distances. Rain covers kilometres, so if the nearby links show it too,
a dip is much more likely to be rain than wind or multipath on one link.

All rolling windows are centred, so a time step's features include the next
few minutes to hours. That suits replaying a storm; a live system would need
trailing windows, which scored MCC 0.53 instead of 0.62 on OpenMRG.
"""

import warnings

import numpy as np
import pandas as pd
import xarray as xr
from scipy.spatial import cKDTree
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, matthews_corrcoef

WET_THRESHOLD_MM_H = 0.1
KM_PER_DEG = 111.0
# (number of nearest links, max distance in km) for the neighbour features
NEIGHBOUR_SCALES = ((4, 10.0), (8, 10.0), (16, 15.0))
SMOOTH = "11min"  # average predicted probabilities over this window


def _steps(trsl, window):
    """Convert a time window like "60min" into a number of samples."""
    dt = pd.Timedelta(trsl.time.values[1] - trsl.time.values[0])
    return max(3, int(round(pd.Timedelta(window) / dt)))


def _any_sublink(wet, like):
    # A link is wet when any of its sublinks is wet
    return wet.any("sublink_id").broadcast_like(like).transpose(*like.dims)


def _rolling_std(trsl, window):
    n = _steps(trsl, window)
    return trsl.rolling(time=n, center=True, min_periods=n // 2).std()


def rolling_std(trsl, window="60min", threshold=0.8):
    return _any_sublink(_rolling_std(trsl, window) > threshold, trsl)


def _neighbour_features(trsl, own, k, max_km):
    """What the k nearest links (within max_km) are doing at each time step."""
    lat = ((trsl.site_0_lat + trsl.site_1_lat) / 2).values
    lon = ((trsl.site_0_lon + trsl.site_1_lon) / 2).values
    xy = np.column_stack([lon * KM_PER_DEG * np.cos(np.deg2rad(lat.mean())), lat * KM_PER_DEG])
    k = min(k, len(lat) - 1)
    dist, idx = cKDTree(xy).query(xy, k=k + 1)
    far = dist[:, 1:] > max_km
    idx = idx[:, 1:]

    def across_neighbours(per_link, how):
        values = per_link.transpose("cml_id", "time").values[idx]  # (link, neighbour, time)
        values[far] = np.nan
        with warnings.catch_warnings():  # links with no neighbour in range give NaN
            warnings.simplefilter("ignore", RuntimeWarning)
            return how(values, axis=1)

    std15 = own["std15"].mean("sublink_id")
    std60 = own["std60"].mean("sublink_id")
    loss_per_km = (own["loss"] / trsl.length).mean("sublink_id")
    return [
        across_neighbours(std15, np.nanmedian),
        across_neighbours(loss_per_km, np.nanmedian),
        across_neighbours(loss_per_km, np.nanmax),
        across_neighbours((std60 > 0.8).where(std60.notnull()), np.nanmean),  # share the rule calls wet
    ]


def features(trsl):
    """Per-sample features, shape (cml_id * sublink_id * time, n_features).

    Computed for the whole network at once, because the neighbour features of
    one link depend on all the others.
    """
    n_long = _steps(trsl, "6h")
    dry_level = trsl.rolling(time=n_long, center=True, min_periods=n_long // 4).median()
    own = {
        "std15": _rolling_std(trsl, "15min"),
        "std60": _rolling_std(trsl, "60min"),
        "std180": _rolling_std(trsl, "180min"),
        "loss": trsl - dry_level,  # extra loss compared with the recent dry level
        "diff": trsl.diff("time").reindex(time=trsl.time),
    }
    n30 = _steps(trsl, "30min")
    own["loss_mean30"] = own["loss"].rolling(time=n30, center=True, min_periods=n30 // 6).mean()

    shape = trsl.transpose("cml_id", "sublink_id", "time").shape
    cols = [f.transpose("cml_id", "sublink_id", "time").values for f in own.values()]
    for k, max_km in NEIGHBOUR_SCALES:
        for per_link in _neighbour_features(trsl, own, k, max_km):
            cols.append(np.broadcast_to(per_link[:, None, :], shape))
    return np.column_stack([c.reshape(-1) for c in cols])


def labels_from_reference(r_ref, like):
    """Wet/dry truth from a reference rain rate per link (cml_id, time)."""
    wet = (r_ref > WET_THRESHOLD_MM_H).broadcast_like(like).transpose(*like.dims)
    return wet.values.reshape(-1)


def _has_data(trsl):
    """Samples of links that reported anything at that time; only these are trained and scored."""
    return trsl.notnull().any("sublink_id").broadcast_like(trsl).transpose(*trsl.dims).values.reshape(-1)


def _fit(X, y):
    model = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.1, random_state=0)
    return model.fit(X, y)


def _classify(model, X, trsl):
    proba = xr.DataArray(model.predict_proba(X)[:, 1].reshape(trsl.shape), coords=trsl.coords, dims=trsl.dims)
    n = _steps(trsl, SMOOTH)
    wet = proba.rolling(time=n, center=True, min_periods=1).mean() > 0.5
    return _any_sublink(wet, trsl)


def widen(wet, window="30min"):
    """Extend each wet period by `window` on both sides.

    The rain estimate measures loss against the signal just before a wet
    period. The classifier marks rain from its onset, when the signal is
    already dropping, which puts that baseline too low and under-counts rain
    (Chalmers gauge on OpenMRG: 9.9 mm estimated against 25.1 mm measured).
    A 30 min margin, the same as the 60 min centred rolling-std rule has,
    fixed it (26.0 mm). Use this for rain estimation, not for scoring.
    """
    n = 2 * _steps(wet, window) + 1
    return wet.astype(float).rolling(time=n, center=True, min_periods=1).max() > 0


def train_classifier(trsl, r_ref):
    X, y, ok = features(trsl), labels_from_reference(r_ref, trsl), _has_data(trsl)
    return _fit(X[ok], y[ok])


def predict(model, trsl):
    return _classify(model, features(trsl), trsl)


def evaluate(trsl, r_ref, test_fraction=0.5, seed=0):
    """Train on some links, test on the rest, and compare with the rolling-std rule.

    Splitting by link (not by time) keeps neighbouring samples of the same link
    out of both sets, so the score reflects links the model has not seen. The
    test links' signals still feed their neighbours' features, as they would
    in operation; their reference labels are never used for training.
    """
    rng = np.random.default_rng(seed)
    ids = trsl.cml_id.values.copy()
    rng.shuffle(ids)
    test_ids = ids[: int(len(ids) * test_fraction)]

    X, y, ok = features(trsl), labels_from_reference(r_ref, trsl), _has_data(trsl)
    row_link = np.broadcast_to(trsl.cml_id.values[:, None, None], trsl.shape).reshape(-1)
    test = np.isin(row_link, test_ids)
    model = _fit(X[~test & ok], y[~test & ok])

    scores = {}
    for name, wet in [("rolling_std", rolling_std(trsl)), ("ml", _classify(model, X, trsl))]:
        pred = wet.values.reshape(-1)
        scored = test & ok
        scores[name] = {
            "accuracy": round(float(accuracy_score(y[scored], pred[scored])), 3),
            "mcc": round(float(matthews_corrcoef(y[scored], pred[scored])), 3),
        }
    return model, scores
