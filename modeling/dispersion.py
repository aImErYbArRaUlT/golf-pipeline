"""Monte-Carlo shot dispersion (Stage B).

Stage A flies one nominal shot; real shots scatter. A club's launch conditions
vary shot to shot, and that variation is exactly what makes a club land in an
oval rather than a point. This module estimates a club's launch-condition
distribution from its gold shots, samples it, flies every sample through the
calibrated engine (vectorised - see `physics.simulate_batch`), and summarises
where the balls land: carry centre and spread, and the 1-sigma landing ellipse.

The launch-condition vector modelled jointly (so correlations like
faster-ball-speed-with-lower-spin are preserved) is, in SI units:

    [ball_speed, launch_angle, launch_direction, spin_rate, spin_axis]
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .contracts import RHO_SEA_LEVEL, ShotInput
from .physics import DEFAULT_CD, DEFAULT_CD_SPIN, DEFAULT_CL_COEFF, simulate_batch

# Need enough real shots to estimate a 5x5 covariance without it being noise.
MIN_SHOTS = 8


@dataclass(frozen=True)
class ClubDispersion:
    """Where one club's shots land, from Monte-Carlo over its launch spread."""

    source: str
    player: str
    club: str
    n_observed: int  # real shots the distribution was fit on
    n_samples: int  # Monte-Carlo draws flown

    carry_mean_yards: float
    carry_std_yards: float
    lateral_mean_yards: float
    lateral_std_yards: float
    carry_p10_yards: float
    carry_p90_yards: float

    # 1-sigma landing ellipse in the (downrange, lateral) plane.
    ellipse_semi_major_yards: float
    ellipse_semi_minor_yards: float
    ellipse_angle_deg: float  # major-axis tilt from the downrange axis

    # Landing scatter, kept for plotting (each (n_samples,)).
    landings_carry: np.ndarray
    landings_lateral: np.ndarray


def _launch_matrix(shots: list[ShotInput]) -> np.ndarray:
    """(N, 5) matrix of the jointly-modelled launch conditions, SI units."""
    return np.array(
        [
            [
                s.ball_speed_ms,
                s.launch_angle_rad,
                s.launch_direction_rad,
                s.spin_rate_rad_s,
                s.spin_axis_rad,
            ]
            for s in shots
        ]
    )


def _ellipse(carry: np.ndarray, lateral: np.ndarray) -> tuple[float, float, float]:
    """1-sigma ellipse (semi-major, semi-minor, angle°) of the landing cloud."""
    cov = np.cov(np.vstack([carry, lateral]))  # 2x2: row 0 downrange, row 1 lateral
    vals, vecs = np.linalg.eigh(cov)  # ascending eigenvalues
    vals = np.clip(vals, 0.0, None)
    major = vecs[:, 1]  # eigh: last column is the largest-eigenvalue vector
    semi_major = float(np.sqrt(vals[1]))
    semi_minor = float(np.sqrt(vals[0]))
    angle = float(np.degrees(np.arctan2(major[1], major[0])))
    return semi_major, semi_minor, angle


def simulate_dispersion(
    shots: list[ShotInput],
    *,
    source: str,
    player: str,
    club: str,
    cd: float = DEFAULT_CD,
    cl_coeff: float = DEFAULT_CL_COEFF,
    cd_spin: float = DEFAULT_CD_SPIN,
    n_samples: int = 2000,
    seed: int = 0,
) -> ClubDispersion:
    """Fit one club's launch distribution, fly a Monte-Carlo sample, summarise.

    The sample is drawn from a multivariate normal fit to the observed launch
    conditions (mean + full covariance), so shot-to-shot correlations are kept.
    Draws are clipped to physical ranges (positive ball speed, non-negative
    spin). `seed` makes the result reproducible.
    """
    if len(shots) < MIN_SHOTS:
        raise ValueError(f"need >= {MIN_SHOTS} shots to estimate dispersion, got {len(shots)}")

    x = _launch_matrix(shots)
    mean = x.mean(axis=0)
    cov = np.cov(x, rowvar=False)

    rng = np.random.default_rng(seed)
    draws = rng.multivariate_normal(mean, cov, size=n_samples)
    draws[:, 0] = np.clip(draws[:, 0], 1.0, None)  # ball speed > 0
    draws[:, 3] = np.clip(draws[:, 3], 0.0, None)  # spin rate >= 0

    samples = [
        ShotInput(
            ball_speed_ms=d[0],
            launch_angle_rad=d[1],
            launch_direction_rad=d[2],
            spin_rate_rad_s=d[3],
            spin_axis_rad=d[4],
            air_density=RHO_SEA_LEVEL,
        )
        for d in draws
    ]

    batch = simulate_batch(samples, cd, cl_coeff, cd_spin)
    ok = ~np.isnan(batch.carry_yards)
    carry = batch.carry_yards[ok]
    lateral = batch.lateral_yards[ok]

    semi_major, semi_minor, angle = _ellipse(carry, lateral)
    return ClubDispersion(
        source=source,
        player=player,
        club=club,
        n_observed=len(shots),
        n_samples=int(carry.size),
        carry_mean_yards=float(carry.mean()),
        carry_std_yards=float(carry.std()),
        lateral_mean_yards=float(lateral.mean()),
        lateral_std_yards=float(lateral.std()),
        carry_p10_yards=float(np.percentile(carry, 10)),
        carry_p90_yards=float(np.percentile(carry, 90)),
        ellipse_semi_major_yards=semi_major,
        ellipse_semi_minor_yards=semi_minor,
        ellipse_angle_deg=angle,
        landings_carry=carry,
        landings_lateral=lateral,
    )
