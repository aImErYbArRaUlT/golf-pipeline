"""Calibrate the engine's aerodynamic coefficients (Stage A).

Fits drag (`cd`), spin-drag (`cd_spin`) and lift (`cl_coeff`) so the engine's
simulated carry matches *measured* carry - an inverse problem solved with least
squares. The calibration set wants a spread of spin ratios, because `cd_spin`
(drag rising with spin) is what separates a low-spin driver from a high-spin
wedge; the TrackMan tour bag is exactly that. Fit on all of it and report the
carry residual.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from .contracts import ShotInput
from .physics import DEFAULT_CD, DEFAULT_CD_SPIN, DEFAULT_CL_COEFF, simulate

# Physically plausible bounds for a golf ball.
_CD_BOUNDS = (0.10, 0.40)
_CL_BOUNDS = (0.5, 6.0)
_CD_SPIN_BOUNDS = (0.0, 2.0)


@dataclass(frozen=True)
class CalibrationResult:
    cd: float
    cl: float
    cd_spin: float
    mae_before_yards: float  # mean abs carry error at the defaults
    mae_after_yards: float  # mean abs carry error at the fitted coefficients
    median_ae_after_yards: float  # median abs error - robust to outliers
    n_shots: int


def _carry(shot: ShotInput, cd: float, cl: float, cd_spin: float) -> float:
    return simulate(shot, cd, cl, cd_spin).carry_yards


def _abs_errors(shots: list[ShotInput], cd: float, cl: float, cd_spin: float) -> list[float]:
    return [
        abs(_carry(s, cd, cl, cd_spin) - s.measured_carry_yards)
        for s in shots
        if s.measured_carry_yards is not None
    ]


def mean_abs_carry_error(shots: list[ShotInput], cd: float, cl: float, cd_spin: float) -> float:
    """Mean absolute carry error (yards) over shots with a measured carry."""
    errs = _abs_errors(shots, cd, cl, cd_spin)
    return float(np.mean(errs)) if errs else float("nan")


def calibrate(shots: list[ShotInput]) -> CalibrationResult:
    """Fit (cd, cl_coeff, cd_spin) to the measured carries in `shots`.

    Uses every shot with a measured carry. Needs a handful spanning a range of
    spin so the spin-drag term is identifiable.
    """
    measured = [s for s in shots if s.measured_carry_yards is not None]
    if len(measured) < 4:
        raise ValueError(f"need >= 4 measured-carry shots to calibrate, got {len(measured)}")

    targets = np.array([s.measured_carry_yards for s in measured], dtype=float)

    def residuals(params: np.ndarray) -> np.ndarray:
        cd, cl, cd_spin = params
        sim = np.array([_carry(s, cd, cl, cd_spin) for s in measured])
        return sim - targets

    # Robust (soft-L1) loss so an odd point can't drag the fit; f_scale sets the
    # residual (yards) beyond which a shot is down-weighted.
    fit = least_squares(
        residuals,
        x0=np.array([DEFAULT_CD, DEFAULT_CL_COEFF, 0.3]),
        bounds=(
            [_CD_BOUNDS[0], _CL_BOUNDS[0], _CD_SPIN_BOUNDS[0]],
            [_CD_BOUNDS[1], _CL_BOUNDS[1], _CD_SPIN_BOUNDS[1]],
        ),
        loss="soft_l1",
        f_scale=12.0,
    )
    cd, cl, cd_spin = float(fit.x[0]), float(fit.x[1]), float(fit.x[2])

    return CalibrationResult(
        cd=cd,
        cl=cl,
        cd_spin=cd_spin,
        mae_before_yards=mean_abs_carry_error(
            measured, DEFAULT_CD, DEFAULT_CL_COEFF, DEFAULT_CD_SPIN
        ),
        mae_after_yards=mean_abs_carry_error(measured, cd, cl, cd_spin),
        median_ae_after_yards=float(np.median(_abs_errors(measured, cd, cl, cd_spin))),
        n_shots=len(measured),
    )
