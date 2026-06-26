"""Synthetic generator tests - believable means, skill-scaled spreads, no warehouse."""

from __future__ import annotations

import pytest

from modeling.benchmarks import calibrate_engine, load_trackman_pga
from modeling.dispersion import simulate_dispersion
from modeling.synthetic import AMATEUR, SCRATCH, TOUR, skill_from_name, synthesize_club_shots

_CAL = calibrate_engine()  # the bag-calibrated coefficients the generator uses


def _disperse(shots):
    return simulate_dispersion(
        shots,
        source="s",
        player="p",
        club="7i",
        n_samples=800,
        cd=_CAL.cd,
        cl_coeff=_CAL.cl,
        cd_spin=_CAL.cd_spin,
    )


def _seven_iron():
    return next(c for c in load_trackman_pga() if c.club == "7-iron")


def test_synthetic_carry_matches_the_tour_mean():
    club = _seven_iron()
    d = _disperse(synthesize_club_shots(club, TOUR, n=300))
    # the engine flying tour-skill shots lands near the published carry
    assert d.carry_mean_yards == pytest.approx(club.carry_yards, abs=8.0)


def test_tighter_skill_means_tighter_dispersion():
    club = _seven_iron()
    tour = _disperse(synthesize_club_shots(club, TOUR, n=300, seed=1))
    amateur = _disperse(synthesize_club_shots(club, AMATEUR, n=300, seed=1))
    assert amateur.carry_std_yards > tour.carry_std_yards
    assert amateur.lateral_std_yards > tour.lateral_std_yards


def test_consistency_knob_scales_spread():
    club = _seven_iron()
    base = _disperse(synthesize_club_shots(club, SCRATCH, n=300, seed=2))
    wider = _disperse(synthesize_club_shots(club, SCRATCH.scaled(2.0), n=300, seed=2))
    assert wider.carry_std_yards > base.carry_std_yards


def test_skill_from_name_rejects_unknown():
    with pytest.raises(ValueError, match="skill"):
        skill_from_name("pro")
