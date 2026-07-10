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

### Android device setup (Huawei P30 / EMUI 12, for the cross-device validation)

EMUI aggressively kills backgrounded apps, and its power saver drops GPS on screen-lock, so
a 30-60 min walk needs both of these:
- **Keep the logger foregrounded (developer-endorsed reliable mode):** in Sensor Logger turn
  on Keep Awake (screen stays on; dim is fine) and Proximity Lock (the screen blanks in a
  pocket but the app keeps behaving as foreground). This alone sidesteps EMUI's task killer.
- **Belt and braces:** Settings > Battery > App launch > Sensor Logger > Manage manually, and
  enable all three of Auto-launch, Secondary launch, and Run in background; add Sensor Logger
  to "Ignore battery optimizations"; turn Power Saving OFF; charge the (6-year-old) battery.
- **Enable TotalAcceleration** in the sensor list. The loader cross-checks Accelerometer +
  Gravity against it and rejects an export whose semantics disagree.
- **Leave "Standardise Units & Frames" OFF** (the default). iOS and Android disagree on the
  Accelerometer/Gravity sign; the loader auto-detects the platform (from Metadata.csv, or the
  Android-only TotalAcceleration.csv marker) and normalizes Android into the iOS frame in
  code. It also tolerates a standardised export, but keep exports uniform so comparisons stay
  clean.
- **Pulling exports over USB:** enable Developer options > "Allow ADB debugging in charge only
  mode" (EMUI drops adb on screen-lock otherwise), or just share the zip and skip adb.
- **GPS warm-up to a full lock still applies.** The P30 has a dual-frequency L1+L5 receiver;
  Android `horizontalAccuracy` is generally honest (unlike iOS's ~7x-pessimistic report), but
  the trusted-fix mask never trusts reported accuracy beyond a loose < 50 m backstop, so no
  code changes either way.
- **Smoke clip first (mirrors the iPhone's indoor test clips):** record ~60 s static + ~2 min
  walk and run `run_phone` on it before the real walk. Confirm `platform: android` and
  `imu_rate_hz` >= 100 in the metrics, median |a| ~ 9.8, a plausible step count, and that the
  logger survived a screen-off pocket stretch.

## Per-walk procedure

- **Route:** a closed loop returning to a single physical start/end mark, in a well-mapped
  urban area (dense OSM footways), dry, with real street corners and distinct through-streets.
  - **Elevation:** gentle grades / hill roads are fine and add realism -- the pipeline is 2D and
    compares horizontal projections, so a 10% grade costs < 0.5% along-track (even a steep 20%
    street ~2%), and loop closure is unaffected as long as you physically close the loop.
    **Avoid stairs:** stair gait breaks the flat-calibrated Weinberg step length by ~10%+ (the
    `k` from your flat calibration leg badly over-counts horizontal distance on steps), and
    covered stairwells starve GPS re-anchoring. A few steps are fine; do not route through long
    staircases, and never calibrate `k` on them.
  - **Loop size (corrected by the B1 finding, 2026-07-08):** prefer a LARGER loop (>= ~1 km of
    distinct, long-edged streets) walked as few laps as reach 2-3 km (~2-3 laps), NOT many laps
    of a small block. Map-matching wrong-edge-snaps on a cramped, short-edge, over-repeated
    circuit: the ~595 m shakedown's ~200 m block gave 18 m median snap distance and made
    map-heading correction *worse* than raw gyro. A bigger distinct-street loop with fewer
    repeats keeps snapping honest and limits drift accumulation across laps. Keep >= 2 laps +
    CW/CCW so the per-lap drift-vs-distance curve still fits and heading bias still brackets.
    Best balance: 2 laps of a ~1 km distinct-street loop, one CW and one CCW.
- **Marks:** chalk/tape the exact start; photograph foot-on-mark at start and final return.
  Survey 4-8 intermediate checkpoint marks (tape/wheel or high-res orthoimagery, not raw OSM
  nodes); tap a logger event marker crossing each and at start/end.
- **Static bookends (mandatory):** stand still >= 60 s on the start mark (phone already in
  pose) before the first step, and again >= 60 s after returning. The opening window seeds
  gyro-bias estimation; the opening-vs-closing bias delta measures gyro-bias drift.
- **Calibration leg:** at the start, pace a tape/wheel-measured straight 60-100 m segment
  **on flat ground, at your NATURAL walking pace**. Its length sets a fixed Weinberg k (pass
  via `--k`); do NOT let k calibrate to GPS distance for the headline number (that launders
  GPS distance into the step model and hides along-track error). Do NOT exaggerate stride
  length on the leg: the 2 km walk's calibration leg was paced with deliberate long strides
  and over-estimated total distance ~1.8x, because Weinberg assumes stride length scales with
  the vertical accel bounce, which exaggerated strides break.
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
