import os

import numpy as np
import psycopg
import pytest

from s2r import data, db, interpolate, nowcast, quality, rain, run, wetdry


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


def test_nowcast_tracks_the_synthetic_storm(synthetic):
    cmls, _ = synthetic
    r_link = rain.link_rain_rate(rain.estimate_rain_rate(cmls, wetdry.rolling_std(rain.trsl(cmls))))
    mid_lat = ((cmls.site_0_lat + cmls.site_1_lat) / 2).values
    mid_lon = ((cmls.site_0_lon + cmls.site_1_lon) / 2).values
    lat, lon = interpolate.make_grid(mid_lat.min(), mid_lat.max(), mid_lon.min(), mid_lon.max())
    grid = interpolate.idw_grid(r_link, mid_lat, mid_lon, lat, lon)

    motion = nowcast.estimate_motion(grid)
    # The squall line moves west at about 12 km/h; check while it is fully over the network
    core = motion.loc["2026-06-15 15:30":"2026-06-15 16:30"]
    assert core.speed_kmh.between(8, 16).all(), core.speed_kmh.describe()
    assert core.bearing_deg.between(225, 300).all(), core.bearing_deg.describe()

    s = nowcast.skill(grid, motion, lead_min=30)
    assert s["csi"]["nowcast"] > s["csi"]["persistence"]


def test_quality_check_names_each_fault(synthetic):
    cmls, _ = synthetic
    cmls = rain.estimate_rain_rate(cmls, wetdry.rolling_std(rain.trsl(cmls)))
    r_link = rain.link_rain_rate(cmls)
    clean = quality.check_links(cmls, r_link).query("reason.isna()").index[:4]
    noisy, short, odd, dead = clean

    rng = np.random.default_rng(0)
    trsl = cmls.trsl.copy()
    trsl.loc[{"cml_id": noisy}] = trsl.sel(cml_id=noisy) + rng.normal(0, 2, trsl.sel(cml_id=noisy).shape)
    trsl.loc[{"cml_id": dead}] = np.nan
    cmls = cmls.assign(trsl=trsl).assign_coords(length=cmls.length.where(cmls.cml_id != short, 0.3))
    r_link = r_link.where(r_link.cml_id != odd, r_link * 10)

    reasons = quality.check_links(cmls, r_link).reason
    assert reasons[noisy] == "noisy"
    assert reasons[short] == "too short"
    assert reasons[odd] == "disagrees with neighbours"
    assert reasons[dead] == "no data"

    filtered, _ = quality.apply(r_link, quality.check_links(cmls, r_link))
    assert filtered.sel(cml_id=odd).isnull().all()


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
