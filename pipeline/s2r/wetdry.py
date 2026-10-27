"""Wet/dry classification: is a drop in signal level caused by rain?

Two methods share one interface, both returning a boolean DataArray shaped like
`trsl` (cml_id, sublink_id, time):

- `rolling_std`: the classic rule (Schleiss and Berne 2010), no training needed.
- `train_classifier` + `predict`: a gradient-boosted model on signal features,
  trained against a reference such as gauges, radar or synthetic truth.
"""

import numpy as np
import pandas as pd
import xarray as xr
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, matthews_corrcoef

WET_THRESHOLD_MM_H = 0.1


def _steps(trsl, window):
    """Convert a time window like "60min" into a number of samples."""
    dt = pd.Timedelta(trsl.time.values[1] - trsl.time.values[0])
    return max(3, int(round(pd.Timedelta(window) / dt)))


def _any_sublink(wet, like):
    # A link is wet when any of its sublinks is wet
    return wet.any("sublink_id").broadcast_like(like).transpose(*like.dims)


def rolling_std(trsl, window="60min", threshold=0.8):
    n = _steps(trsl, window)
    std = trsl.rolling(time=n, center=True, min_periods=n // 2).std()
    return _any_sublink(std > threshold, trsl)


def features(trsl):
    """Per-sample features, shape (cml_id * sublink_id * time, n_features)."""
    cols = []
    for window in ("15min", "60min"):
        n = _steps(trsl, window)
        cols.append(trsl.rolling(time=n, center=True, min_periods=n // 2).std())
    n_long = _steps(trsl, "6h")
    dry_level = trsl.rolling(time=n_long, center=True, min_periods=n_long // 4).median()
    cols.append(trsl - dry_level)
    cols.append(trsl.diff("time").reindex(time=trsl.time))
    stacked = xr.concat(cols, dim="feature").transpose("cml_id", "sublink_id", "time", "feature")
    return stacked.values.reshape(-1, len(cols))


def labels_from_reference(r_ref, like):
    """Wet/dry truth from a reference rain rate per link (cml_id, time)."""
    wet = (r_ref > WET_THRESHOLD_MM_H).broadcast_like(like).transpose(*like.dims)
    return wet.values.reshape(-1)


def train_classifier(trsl, r_ref):
    model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, random_state=0)
    model.fit(features(trsl), labels_from_reference(r_ref, trsl))
    return model


def predict(model, trsl):
    wet = model.predict(features(trsl)).reshape(trsl.shape).astype(bool)
    return _any_sublink(xr.DataArray(wet, coords=trsl.coords, dims=trsl.dims), trsl)


def evaluate(trsl, r_ref, test_fraction=0.5, seed=0):
    """Train on some links, test on the rest, and compare with the rolling-std rule.

    Splitting by link (not by time) keeps neighbouring samples of the same link
    out of both sets, so the score reflects links the model has not seen.
    """
    rng = np.random.default_rng(seed)
    ids = trsl.cml_id.values.copy()
    rng.shuffle(ids)
    n_test = int(len(ids) * test_fraction)
    test_ids, train_ids = ids[:n_test], ids[n_test:]

    model = train_classifier(trsl.sel(cml_id=train_ids), r_ref.sel(cml_id=train_ids))
    test_trsl, test_ref = trsl.sel(cml_id=test_ids), r_ref.sel(cml_id=test_ids)
    truth = labels_from_reference(test_ref, test_trsl)

    scores = {}
    for name, wet in [
        ("rolling_std", rolling_std(test_trsl)),
        ("ml", predict(model, test_trsl)),
    ]:
        pred = wet.values.reshape(-1)
        scores[name] = {
            "accuracy": round(float(accuracy_score(truth, pred)), 3),
            "mcc": round(float(matthews_corrcoef(truth, pred)), 3),
        }
    return model, scores
