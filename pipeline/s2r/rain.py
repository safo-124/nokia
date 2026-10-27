"""Signal levels to rain rate per link, following the standard pycomlink workflow."""

import pandas as pd
from pycomlink.processing.baseline import baseline_constant
from pycomlink.processing.k_R_relation import calc_R_from_A
from pycomlink.processing.wet_antenna import waa_schleiss_2013


def trsl(cmls):
    """Total loss along the link: transmitted minus received signal level [dB]."""
    loss = cmls.tsl - cmls.rsl
    return loss.interpolate_na(dim="time", method="linear", max_gap="5min")


def estimate_rain_rate(cmls, wet, waa_max=2.2, tau_min=15):
    """Add trsl, baseline, waa, A and R [mm/h] to `cmls` and return it.

    wet: boolean DataArray (cml_id, sublink_id, time) from `s2r.wetdry`.
    """
    dt_min = pd.Timedelta(cmls.time.values[1] - cmls.time.values[0]).total_seconds() / 60
    cmls = cmls.copy()
    cmls["trsl"] = trsl(cmls)
    cmls["wet"] = wet

    # Dry baseline: the signal level just before rain started, held during rain
    cmls["baseline"] = baseline_constant(trsl=cmls.trsl, wet=cmls.wet, n_average_last_dry=5)
    # Water on the antennas adds loss that is not rain along the path
    cmls["waa"] = waa_schleiss_2013(
        rsl=cmls.trsl,
        baseline=cmls.baseline,
        wet=cmls.wet,
        waa_max=waa_max,
        delta_t=dt_min,
        tau=tau_min,
    )
    cmls["A"] = (cmls.trsl - cmls.baseline - cmls.waa).clip(min=0)

    # ITU-R P.838 power law, k = a * R^b, inverted for R
    cmls["R"] = calc_R_from_A(
        A=cmls.A,
        L_km=cmls.length,
        f_GHz=cmls.frequency,
        pol=cmls.polarization,
    )
    return cmls


def link_rain_rate(cmls):
    """One rain rate per link: the mean of its sublinks [mm/h], dims (cml_id, time)."""
    return cmls.R.mean("sublink_id")
