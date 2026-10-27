import json

import numpy as np
import pytest

from s2r import data, rain, run, wetdry


@pytest.fixture(scope="module")
def synthetic():
    return data.load_synthetic()


def test_rain_rate_tracks_synthetic_truth(synthetic):
    cmls, _ = synthetic
    wet = wetdry.rolling_std(rain.trsl(cmls))
    r_link = rain.link_rain_rate(rain.estimate_rain_rate(cmls, wet))
    est, ref = r_link.values.ravel(), cmls.R_ref.values.ravel()
    ok = ~np.isnan(est)
    assert np.corrcoef(est[ok], ref[ok])[0, 1] > 0.9


def test_ml_wet_dry_beats_rolling_std_on_synthetic(synthetic):
    cmls, _ = synthetic
    _, scores = wetdry.evaluate(rain.trsl(cmls), cmls.R_ref)
    assert scores["ml"]["mcc"] > scores["rolling_std"]["mcc"]


def test_run_writes_all_outputs(tmp_path):
    run.main(["--out", str(tmp_path)])
    for name in ("meta.json", "links.geojson", "link_rain.csv", "gauges.geojson",
                 "gauge_rain.csv", "grid.npz", "hotspots.geojson", "flood_risk.csv", "alerts.json"):
        assert (tmp_path / name).exists(), name
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert len(meta["times"]) == np.load(tmp_path / "grid.npz")["rain_rate"].shape[0]
