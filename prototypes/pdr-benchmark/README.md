# PDR + map-matching benchmark (step 1)

De-risking spike for Apocalypto's positioning backbone. Question: can phone-only
pedestrian dead reckoning (PDR), map-matched to an OSM walking graph, hold
street-level accuracy over a real outdoor walk?

This step runs a real PDR + map-matching pipeline against the open **GEOLOC/ULISS**
pedestrian dataset (DOI 10.57745/ZCBIIB): 6 tracks (4 clean-outdoor, benchmarked;
231-565 m), handheld low-cost MEMS IMU (Xsens MTi-7) held flat (z-up), with a
foot-mounted ground-truth trajectory and per-stride ground truth. It is a *first
signal*, not proof: the IMU is a handheld low-cost sensor (not a phone), tracks are
sub-km, and GT is few-metre.

## Pipeline

`io/` GEOLOC loader -> `pdr/` (step detection, Weinberg step length, AHRS heading,
dead reckoning) -> `mapmatch/` (GNSS/UBX georeferencing, OSM walk graph, leuven HMM
matcher) -> `eval/` metrics -> `viz/` overlay.

Heading uses gyro + static-phase bias removal; the magnetometer is available but
(see findings) degrades heading here. Start pose (position + initial heading) is
anchored from ground truth, as a real system would have; everything after is open loop.

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# dataset: download DOI 10.57745/ZCBIIB (Geoloc_ds022023.7z) into data/geoloc/
.venv/bin/python -m pytest -q
.venv/bin/python -m pdr_bench.run --track TEST_05           # urban, with map-matching
.venv/bin/python -m pdr_bench.run --track TEST_02 --no-map  # campus (no OSM walk graph)
```

Writes `out/<track>_metrics.json` and `out/<track>_overlay.png`.

## Findings (2026-07-07)

- **PDR passes.** Gyro-only PDR: rmse ~3% of distance on every outdoor track
  (TEST_02 6.7 m, TEST_04 13.2 m, TEST_05 18.0 m, TEST_06 14.0 m) — the 2-5% regime
  the literature predicts.
- **The magnetometer hurt** here (rmse 28-137 m via naive Madgwick MARG fusion); gyro
  + static-bias-removal wins. Naive mag fusion is not a usable heading reference.
- **Heading drift is unbounded** without an absolute reference, so the longest track
  is the worst. This is the limiter for the multi-km claim.
- **Map-matching corrects "which street", not "where along it".** Graph/matcher floor
  is ~5 m (footway-centerline offset). On dense urban (TEST_05) matching recovered
  ~90% of the correct route and cut cross-track error 10.3 -> 7.2 m, but overall rmse
  only 18 -> 16.5 m because along-track (step-length) error dominates. On open/parking
  (TEST_06) it was near-neutral. It is not a drift-correction oracle and only
  disambiguates while drift stays below street spacing.
- **Periodic GNSS re-anchoring bounds the drift** (`scripts/reanchor_experiment.py`,
  `out/reanchor_curve.png`). A trusted fix every ~30 s (~35 m) holds residual RMSE
  <=5-6 m on every track; every ~15 s reaches the ~3-4 m GNSS noise floor. Continuous
  GPS is not required, only occasional trusted fixes, with PDR bridging the gaps.
- **Step-2 note (real phone, 2026-07-08):** these are Xsens (step-1) figures and do not
  transfer directly to a phone. A ~595 m phone shakedown drifted ~6.5% (2x this) and needed a
  tighter ~15-20 s re-anchor cadence (30 s gave ~15 m, not 5-6 m), because phone HEADING drifts
  ~2x faster (converged phone GPS itself was fine, ~1-2 m). Full step-2 findings in `../../STATUS.md`.

Run the sweep with `PYTHONPATH=. .venv/bin/python scripts/reanchor_experiment.py`.
See `../../STATUS.md` for the full verdict and next-step decision.
