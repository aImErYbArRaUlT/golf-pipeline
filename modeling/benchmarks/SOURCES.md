# Benchmark data sources

Cited, externally-published golf benchmark numbers used by the modeling engine.
These are **factual reference values** (tour averages, expected-strokes baselines)
transcribed with attribution for a non-commercial learning project. We store the
numbers, not anyone's branded graphic, and do not redistribute the source files.

How each was collected is noted so it can be re-checked or refreshed. Plain HTML
tables can be pulled automatically (`collect.py`); PDF and image tables (like
TrackMan's averages graphic and Broadie's paper) are not machine-readable tables,
so their numbers were transcribed with a vision pass and verified against the
original.

## trackman_pga_tour_averages.csv / trackman_lpga_tour_averages.csv

- **What:** TrackMan PGA and LPGA Tour averages by club - club/ball speed, attack
  & launch angle, smash factor, spin rate, max height, land angle, carry. Yards
  version. (The LPGA bag carries a hybrid and no 3-iron.)
- **Source:** TrackMan's **updated (2024) Tour Averages** info-screen graphics,
  downloaded from <https://www.trackman.media/tour-averages> (announced at
  <https://www.trackman.com/blog/golf/introducing-updated-tour-averages>).
- **Vintage:** TrackMan's 2024 tour averages (PGA driver carry 282 yds, 7-iron 176;
  LPGA driver 223). Refreshed from the older ≈2010s set (PGA driver 275) so the
  demos reflect modern tour distance.
- **Collected:** 2026-06-23, via vision-read of the 8000×4500 JPGs (image tables,
  not selectable text). Units: carry/height in yards, speeds in mph, angles in
  degrees. A couple of woods' spin/height values are best-effort at that scale.

## strokes-gained baseline (encoded in `modeling/scoring.py`)

- **What:** PGA Tour expected-strokes-to-hole-out benchmark by distance and lie
  (tee, fairway, rough, sand, recovery) and the putting curve.
- **Source:** Mark Broadie, "Assessing Golfer Performance on the PGA TOUR"
  (Columbia / *Interfaces*, ShotLink 2003-2010):
  <https://columbia.edu/~mnb2/broadie/Assets/strokes_gained_pga_broadie_20110408.pdf>,
  and "Every Shot Counts" (2014).
- **Collected:** 2026-06-22, vision-read of the paper's figures/text; the per-lie
  curves live inline in `scoring.py` with verified anchors asserted in tests
  (fairway 100yd=2.80, rough 120yd=3.08, etc.).
