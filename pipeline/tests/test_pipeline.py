import os

import numpy as np
import psycopg
import pytest

from s2r import data, db, rain, run, wetdry


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


def test_run_saves_dataset(monkeypatch):
    url = os.environ.get(
        "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/signal_to_rain_test"
    )
    try:
        db.connect(url).close()
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not reachable: {e}")
    monkeypatch.setenv("DATABASE_URL", url)

    run.main(["--dataset", "pytest-synthetic"])

    with db.connect(url) as conn:
        counts = {
            table: conn.execute(
                f"SELECT count(*) FROM {table} WHERE dataset = 'pytest-synthetic'"
            ).fetchone()[0]
            for table in ("links", "link_rain", "rain_grid", "gauges", "gauge_rain",
                          "hotspots", "flood_risk", "alerts")
        }
        conn.execute("DELETE FROM datasets WHERE id = 'pytest-synthetic'")
    assert all(counts.values()), counts
    assert counts["link_rain"] == counts["links"] * counts["rain_grid"]
