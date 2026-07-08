# Phone-walk collection protocol (step 2)

The definitive test of phone-only positioning: does map-matched PDR with periodic
trusted-GNSS re-anchoring hold street-level accuracy over a real multi-km phone walk? The
software is built (`pdr_bench/io/phone.py`, `run_phone.py`, `scripts/reanchor_phone.py`,
`pdr_bench/eval/phone_metrics.py`); this is the legwork spec. Closes the two open unknowns:
phone-grade IMU noise, and true multi-km length.

> **Shakedown update (2026-07-08).** A ~595 m shakedown walk (full findings in `STATUS.md`)
> answered the phone-grade-IMU unknown (drift ~6.5%, bounded by re-anchoring) and refined this doc's
> SETUP, not its thresholds (which hold): (1) the "~3-10 m accurate" GPS premise is CONFIRMED once the
> receiver converges (measured ~1-2 m stationary; iOS self-reported `horizontalAccuracy` is ~7x
> pessimistic, so do not trust the reported 14 m), BUT the receiver must be WARMED to a full lock
> before recording (cold start gave 35 m scatter over the first ~90 s) and outlier fixes (one 808 m)
> rejected; (2) the PASS guard's "~5 m GPS floor" HOLDS (actual floor ~1-2 m); (3) the "mandated
> ~30 s" re-anchor cadence is too loose for a phone (30 s -> 14.7 m; needs ~15-20 s) -- a phone
> HEADING-drift penalty, independent of GPS quality.

## Why the protocol is shaped this way

A phone walk has no independent ground truth: the phone GPS is both the scoring reference
and the re-anchor source, and it is only ~3-10 m accurate. So the design manufactures
GPS-free truth:
- **Loop closure** (primary): walk back to the exact physical start mark. True start-to-end
  displacement is zero, known to foot precision, so open-loop PDR end-vs-start is pure drift
  with no GPS dependence.
- **Held-out GPS** (re-anchor metric): anchor on fixes at the cadence times, score only at
  the mid-cadence times that never pinned the track.
- **Surveyed checkpoints**: a few marks whose coordinates you measured, scored GPS-free.

## Logger

Sensor Logger by Kelvin Choi (cross-platform, free, one device clock, zipped per-sensor CSV).
- Enable: Accelerometer, Gravity, Gyroscope, Magnetometer, Location, Orientation (plus
  TotalAcceleration on Android). Gravity is required (the adapter reconstructs raw accel =
  Accelerometer + Gravity).
- IMU at the highest stable rate (target >= 100 Hz). Location at max (~1 Hz) with per-fix
  accuracy, course, and speed. Log raw GNSS / NMEA too if the device exposes it.
- Disable auto-pause / sleep.

## Per-walk procedure

- **Route:** a closed loop returning to a single physical start/end mark, in a well-mapped
  urban area (dense OSM footways), flat and dry, with real street corners. Prefer multiple
  laps of a ~500 m loop to reach 2-3 km total (so closure error is sampled each lap and a
  drift-vs-distance curve can be fit). One large loop is acceptable.
- **Marks:** chalk/tape the exact start; photograph foot-on-mark at start and final return.
  Survey 4-8 intermediate checkpoint marks (tape/wheel or high-res orthoimagery, not raw OSM
  nodes); tap a logger event marker crossing each and at start/end.
- **Static bookends (mandatory):** stand still >= 60 s on the start mark (phone already in
  pose) before the first step, and again >= 60 s after returning. The opening window seeds
  gyro-bias estimation; the opening-vs-closing bias delta measures gyro-bias drift.
- **Calibration leg:** at the start, pace a tape/wheel-measured straight 60-100 m segment.
  Its length sets a fixed Weinberg k (pass via `--k`); do NOT let k calibrate to GPS distance
  for the headline number (that launders GPS distance into the step model and hides
  along-track error).
- **Pose, two variants in order:** P1 held flat, screen up, pointing forward, steady (matches
  the step-1 Xsens-flat assumption; the primary comparable case). P2 pocket / swinging hand
  (harder; quantifies pose sensitivity). Keep P1 genuinely rigid: a time-varying
  body-to-device offset corrupts heading in a way start-pose alignment cannot absorb.
- **Repeats:** minimum each pose walked clockwise AND counter-clockwise (4 walks; CW/CCW
  brackets residual gyro bias). Preferred 3x per (pose x direction).

## Run and score

```
python -m pdr_bench.run_phone <export_dir> --name <id> --k <cal_k>       # map-matched overlay + metrics
PYTHONPATH=. .venv/bin/python scripts/reanchor_phone.py <export_dir> --name <id> --k <cal_k>
```

Metrics: M1 loop closure (GPS-free, per-lap growth), M2 held-out radial + P95 + cross-track
P95 (map-matched), M3 re-anchor cadence curve, M4 checkpoint absolute error (GPS-free), M5
gyro-bias drift (opening vs closing static), M6 k-sensitivity (calibration-leg k vs a fixed
literature k). Report P95, not just RMSE.

## PASS / KILL

- **PASS (phone-only viable):** with map-matching and re-anchoring at cadence <= the mandated
  ~30 s / ~35 m, held-out P95 radial <= 20-30 m AND cross-track P95 < ~10-15 m, across both
  directions on the 2-3 km loop in pose P1, corroborated by the checkpoint P95.
- **KILL (pivot to a foot-mounted ZUPT accessory):** map-matched, re-anchored P95 (M2) or
  checkpoint P95 (M4) exceeds ~30 m at the mandated cadence over 2-3 km in P1; or no cadence
  down to ~15 s holds street width (would need continuous GPS, defeating the degraded-GPS
  premise).
- Guard: M2/M4 ride a ~5 m GPS floor, so only differences > ~10 m from it are real; the
  20-30 m threshold clears this. M1 (GPS-free) and open-loop-vs-GPS-track must agree in
  magnitude, else distrust the run.

Record the verdict in `../../STATUS.md`.

## Honest limits

Intact-city clean pavement is the favorable case: falsification-only (fail here means fail in
disaster; pass is necessary, not sufficient). The trusted-fix premise and GNSS spoofing are
assumed, not tested. Fully GPS-denied interiors are out of scope (that is the gated-mag / ZUPT
path). Gyro-only by design (no mag). n = 1 walker, 1 phone. Loop closure under-reports peak
excursion (mitigated by CW/CCW + multi-lap + checkpoints). Without post-processed raw GNSS,
resolves tens-of-metres drift and the 20-30 m threshold but not the ~5 m re-anchor floor.
