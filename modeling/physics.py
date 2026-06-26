"""Ball-flight physics engine (Stage A).

Integrates the equations of motion for a golf ball under four forces - gravity,
drag, Magnus lift (backspin), and spin-axis tilt (draw/fade) - from launch until
it returns to the ground. The drag and lift coefficients (Cd, Cl) are fit once by
calibration (see calibration.py); everything above this layer inherits its
accuracy.

Coordinate frame: x = downrange (toward the target), y = lateral (+ = right),
z = up. Standard 4-force model only - no CFD, no spin decay (out of scope; they
don't change the recommendation).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_ivp

from .contracts import M_TO_YARDS, ShotInput

# Golf ball constants (R&A/USGA conforming ball).
_MASS_KG = 0.0459
_DIAMETER_M = 0.04267
_RADIUS_M = _DIAMETER_M / 2.0
_AREA_M2 = np.pi * _RADIUS_M**2
_G = 9.80665

# Calibrated defaults (overwritten by calibration.py once fit). Lift uses a
# spin-aware coefficient: Cl = CL_COEFF * spin_ratio, where spin_ratio = ωr/v.
# So more backspin -> more lift -> more carry/height, as it should.
DEFAULT_CD = 0.23
DEFAULT_CL_COEFF = 2.0
# Drag also rises with spin (Cd = cd + cd_spin * spin_ratio); 0 = off until fit.
DEFAULT_CD_SPIN = 0.0

# A real golf ball's lift coefficient saturates - it does not grow without bound
# as spin rises. The linear Cl = cl_coeff * spin_ratio is only valid at the low
# spin ratios it was fit on (drivers); past this ceiling it would "float" a
# high-spin iron unphysically (lift ~ gravity, a 5° descent). Cap it. Wind-tunnel
# data puts a golf ball's max Cl around here.
CL_MAX = 0.32

# Bounce-and-roll: roll grows with carry (a proxy for landing speed) and falls off
# with backspin - a low-spin driver releases and runs, a high-spin wedge checks up.
# (Backspin, not descent angle, because the engine reproduces spin exactly but its
# landing angle is only approximate.) Defaults anchored to tour roll figures
# (driver ~+16 yds, wedge ~+3); the integrator models flight, total = carry + this.
ROLL_COEFF = 0.091
ROLL_SPIN_DECAY = 1.55e-3  # per rad/s


def roll_yards(
    carry_yards: float | np.ndarray,
    spin_rate_rad_s: float | np.ndarray,
    *,
    roll_coeff: float = ROLL_COEFF,
    firmness: float = 1.0,
) -> float | np.ndarray:
    """Heuristic roll-out distance from carry and backspin (yards)."""
    check = np.exp(-ROLL_SPIN_DECAY * np.asarray(spin_rate_rad_s))
    return firmness * roll_coeff * np.asarray(carry_yards) * check


@dataclass(frozen=True)
class Trajectory:
    """The result of a simulated shot."""

    points: np.ndarray  # (N, 3) positions in metres, launch to landing
    carry_yards: float  # horizontal distance to first landing
    total_yards: float  # carry plus modelled bounce-and-roll
    lateral_yards: float  # signed sideways offset at landing (+ = right)
    peak_height_yards: float
    descent_angle_deg: float  # angle below horizontal at landing


@dataclass(frozen=True)
class BatchResult:
    """Landing outcomes for a batch of shots flown in lock-step (Stage B).

    Each field is a (N,) array aligned with the input shots. Only landing
    metrics are kept, not full paths - Monte-Carlo dispersion needs where the
    balls land, not every point along the way.
    """

    carry_yards: np.ndarray
    total_yards: np.ndarray
    lateral_yards: np.ndarray
    peak_height_yards: np.ndarray
    descent_angle_deg: np.ndarray


def _spin_axis_unit(shot: ShotInput, v_hat: np.ndarray) -> np.ndarray:
    """Unit spin-axis vector in the world frame.

    Pure backspin is a horizontal axis perpendicular to the launch direction,
    oriented so the Magnus force points up. A positive spin_axis tilts it about
    the launch-velocity direction so a right-hander gets a fade (curve right).
    """
    azim = shot.launch_direction_rad
    backspin_axis = np.array([np.sin(azim), -np.cos(azim), 0.0])
    # Rodrigues rotation of the backspin axis about the launch velocity. Negative
    # tilt so +spin_axis_rad produces a fade (+y Magnus), matching convention.
    theta = -shot.spin_axis_rad
    k = v_hat
    rotated = (
        backspin_axis * np.cos(theta)
        + np.cross(k, backspin_axis) * np.sin(theta)
        + k * np.dot(k, backspin_axis) * (1.0 - np.cos(theta))
    )
    norm = np.linalg.norm(rotated)
    return rotated / norm if norm > 0 else backspin_axis


def _initial_velocity(shot: ShotInput) -> np.ndarray:
    elev, azim = shot.launch_angle_rad, shot.launch_direction_rad
    return shot.ball_speed_ms * np.array(
        [np.cos(elev) * np.cos(azim), np.cos(elev) * np.sin(azim), np.sin(elev)]
    )


def simulate(
    shot: ShotInput,
    cd: float = DEFAULT_CD,
    cl_coeff: float = DEFAULT_CL_COEFF,
    cd_spin: float = DEFAULT_CD_SPIN,
    wind: np.ndarray | None = None,
    landing_height: float = 0.0,
) -> Trajectory:
    """Simulate one shot to first landing. Returns the full trajectory + metrics.

    Counterfactual-capable: pass a different air_density (via the ShotInput) or a
    `wind` vector (m/s, see conditions.wind_vector) to re-fly the same launch in
    conditions it was never measured in. `landing_height` (metres) is the ground
    height of the target relative to the launch - uphill ground (>0) catches the
    ball earlier so it carries shorter, downhill (<0) later so it carries longer.
    """
    v0 = _initial_velocity(shot)
    s_hat = _spin_axis_unit(shot, v0 / np.linalg.norm(v0))
    rho = shot.air_density
    omega_r = shot.spin_rate_rad_s * _RADIUS_M  # spin tip speed (for the spin ratio)
    k_area = 0.5 * rho * _AREA_M2
    w = np.zeros(3) if wind is None else np.asarray(wind, dtype=float)

    def accel(_t: float, state: np.ndarray) -> np.ndarray:
        vel = state[3:]
        v_rel = vel - w  # aerodynamic forces act on velocity relative to the air
        speed = np.linalg.norm(v_rel)
        if speed == 0:
            return np.array([0.0, 0.0, 0.0, 0.0, 0.0, -_G])
        v_hat = v_rel / speed
        spin_ratio = omega_r / speed
        # Lift: Cl = cl_coeff * spin_ratio, capped at the physical ceiling.
        # Drag rises with spin too (Cd = cd + cd_spin * spin_ratio), so high-spin
        # shots shed speed faster - the effect that separates the bag.
        cl = min(cl_coeff * spin_ratio, CL_MAX)
        cd_eff = cd + cd_spin * spin_ratio
        f_drag = -k_area * cd_eff * speed * v_rel
        f_lift = k_area * cl * speed * speed * np.cross(s_hat, v_hat)
        f_grav = np.array([0.0, 0.0, -_MASS_KG * _G])
        return np.concatenate([vel, (f_drag + f_lift + f_grav) / _MASS_KG])

    def landed(_t: float, state: np.ndarray) -> float:
        return state[2] - landing_height  # fires when z crosses the target height

    landed.terminal = True
    landed.direction = -1  # only when descending

    # Single-shot integration, written for clarity and used as the calibration
    # reference. The batched Monte-Carlo path lives in simulate_batch below - it
    # flies thousands of these in lock-step with the same force model.
    sol = solve_ivp(
        accel,
        t_span=(0.0, 15.0),
        y0=np.concatenate([np.zeros(3), v0]),
        events=landed,
        max_step=0.02,
        rtol=1e-7,
        atol=1e-9,
    )

    points = sol.y[:3].T
    land = points[-1]
    vel_land = sol.y[3:, -1]
    horiz = float(np.hypot(land[0], land[1]))
    descent = float(np.degrees(np.arctan2(-vel_land[2], np.hypot(vel_land[0], vel_land[1]))))
    carry = horiz * M_TO_YARDS
    return Trajectory(
        points=points,
        carry_yards=carry,
        total_yards=carry + float(roll_yards(carry, shot.spin_rate_rad_s)),
        lateral_yards=float(land[1]) * M_TO_YARDS,
        peak_height_yards=float(points[:, 2].max()) * M_TO_YARDS,
        descent_angle_deg=descent,
    )


def simulate_batch(
    shots: list[ShotInput],
    cd: float = DEFAULT_CD,
    cl_coeff: float = DEFAULT_CL_COEFF,
    cd_spin: float = DEFAULT_CD_SPIN,
    dt: float = 0.002,
    t_max: float = 15.0,
    wind: np.ndarray | None = None,
    landing_height: float = 0.0,
) -> BatchResult:
    """Fly many shots at once with a fixed-step RK4 over an (N, 6) state array.

    Same four-force model as `simulate`, vectorised across shots so a whole
    Monte-Carlo sample integrates in lock-step. Each shot is frozen the step it
    lands (z crosses zero descending), its landing point recovered by linear
    interpolation across that step. Cross-checked against `simulate` in the
    tests to within a fraction of a yard.
    """
    n = len(shots)
    if n == 0:
        empty = np.empty(0)
        return BatchResult(*(empty.copy() for _ in range(5)))

    v0 = np.array([_initial_velocity(s) for s in shots])  # (N, 3)
    v_hat0 = v0 / np.linalg.norm(v0, axis=1, keepdims=True)
    s_hat = np.array([_spin_axis_unit(s, v_hat0[i]) for i, s in enumerate(shots)])  # (N, 3)
    rho = np.array([s.air_density for s in shots])
    omega_r = np.array([s.spin_rate_rad_s for s in shots]) * _RADIUS_M
    k_area = 0.5 * rho * _AREA_M2  # (N,)
    f_grav = np.array([0.0, 0.0, -_MASS_KG * _G])
    w = np.zeros(3) if wind is None else np.asarray(wind, dtype=float)

    def deriv(state: np.ndarray) -> np.ndarray:
        vel = state[:, 3:]
        v_rel = vel - w  # forces act on velocity relative to the air
        speed = np.linalg.norm(v_rel, axis=1)
        safe = np.where(speed == 0.0, 1.0, speed)
        v_hat = v_rel / safe[:, None]
        spin_ratio = omega_r / safe
        cl = np.minimum(cl_coeff * spin_ratio, CL_MAX)  # capped lift coefficient
        cd_eff = cd + cd_spin * spin_ratio  # drag rises with spin
        f_drag = -(k_area * cd_eff * speed)[:, None] * v_rel
        f_lift = (k_area * cl * speed * speed)[:, None] * np.cross(s_hat, v_hat)
        acc = (f_drag + f_lift + f_grav) / _MASS_KG
        out = np.empty_like(state)
        out[:, :3] = vel
        out[:, 3:] = acc
        return out

    state = np.zeros((n, 6))
    state[:, 3:] = v0

    landed = np.zeros(n, dtype=bool)
    carry = np.full(n, np.nan)
    lateral = np.full(n, np.nan)
    descent = np.full(n, np.nan)
    peak = np.zeros(n)  # max height reached (metres)

    t = 0.0
    while not landed.all() and t < t_max:
        active = ~landed
        z_prev = state[:, 2].copy()

        k1 = deriv(state)
        k2 = deriv(state + 0.5 * dt * k1)
        k3 = deriv(state + 0.5 * dt * k2)
        k4 = deriv(state + dt * k3)
        new = state + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)

        peak = np.where(active, np.maximum(peak, new[:, 2]), peak)

        # Landing: z went from at/above the target height to below it this step.
        crossed = active & (z_prev >= landing_height) & (new[:, 2] < landing_height)
        if crossed.any():
            zp = z_prev[crossed] - landing_height
            frac = zp / (zp - (new[crossed, 2] - landing_height))  # step fraction to the height
            land_state = state[crossed] + frac[:, None] * (new[crossed] - state[crossed])
            cx, cy = land_state[:, 0], land_state[:, 1]
            vlx, vly, vlz = land_state[:, 3], land_state[:, 4], land_state[:, 5]
            carry[crossed] = np.hypot(cx, cy) * M_TO_YARDS
            lateral[crossed] = cy * M_TO_YARDS
            descent[crossed] = np.degrees(np.arctan2(-vlz, np.hypot(vlx, vly)))
            landed[crossed] = True

        state = np.where(active[:, None], new, state)  # frozen shots stay put
        t += dt

    return BatchResult(
        carry_yards=carry,
        total_yards=carry + roll_yards(carry, omega_r / _RADIUS_M),
        lateral_yards=lateral,
        peak_height_yards=peak * M_TO_YARDS,
        descent_angle_deg=descent,
    )
