# PLAN: navigation next steps (post-research, post-shakedown)

Last updated: 2026-07-08. This doc merges two inputs into one sequenced roadmap with the findings attached to each step:
- The deep-research report `docs/research/2026-07-08-navigation-mitigations-research.md` (3 clusters, 120 sources, adversarially verified).
- Another session's keyboard-work sequencing plan `~/.claude/plans/for-these-next-steps-staged-liskov.md` (grounded in the code; absorbed here with corrections it could not have known).

Read `STATUS.md` for project state and `docs/research/2026-07-08-navigation-mitigations-research.md` for the full evidence and dead-ends.

## 1. The reframe (read this first)

Three findings from the research change how everything below is prioritized:

1. **Heading drift is the root, and no phone sensor can fix it.** Yaw is provably unobservable from accel + gyro. ZUPT, ZARU, magnetometer fusion, and learned inertial odometry all fail to bound it (verified). The only offline thing that bounds heading on a real phone is the **map** (killing through-a-wall hypotheses at turns).
2. **Invert the spine.** Today GNSS re-anchoring is the heading fixer (every 15-20 s) and map-matching is a secondary "which-street" aid. Flip it: the map bounds heading continuously where geometry exists, and GNSS becomes a scarce along-track correction that must pass a consistency gate. This attacks heading (P5), relaxes cadence (P11), and shrinks the spoof surface (P4).
3. **On spoofing, degrade, do not detect.** Gross faults (the 808 m outlier, cold-start) die to a cheap IMU-vs-GNSS gate. Jamming onset is Android-only and transient. A competent slow spoofer is undetectable phone-only. So gate the easy faults and fall back to dead reckoning on trust loss.

## 2. The blocker: the 2-3 km PASS/KILL walk (field legwork)

This is the only thing standing between us and a verdict on the core thesis (phone PDR + periodic trusted re-anchoring holds ~20-30 m over 2-3 km). It cannot be done at the keyboard. Setup rules, refined by the shakedown and the research:
- Warm GPS to a **full lock** before recording (the shakedown started cold: 4 scattered fixes, 35 m spread, first ~90 s garbage). Converged phone GPS is ~1-2 m; the iOS-reported 14 m is ~7x pessimistic, so do not trust the reported number.
- Verify dense OSM footway coverage before walking (shakedown map-matching recovered only 44% of edges). The venue's GPS itself was fine; no better venue needed for GPS, only for map coverage.
- Plan ~15-20 s trusted-fix cadence, surveyed checkpoints, and CW/CCW repeats. Pass the walk's own calibration-leg `k` via `--k`.
- **New (from research):** log a scripted **hold to pocket to swing to call** pose sequence. Pose is the sleeper risk: our 6.5% baseline is one favorable hold, and an unconstrained phone roughly doubles error. Measure per-pose and transition error.

Everything in Workstreams A and B is designed so that when this walk lands, the analysis is one command and the verdict is crisp.

## 3. Workstream A: no-regret keyboard work (do now, does not wait for the walk)

These touch scoring and hygiene, not algorithms. They are no-regret. Build in this order.

> **STATUS: A1, A2, A3 all SHIPPED 2026-07-08 (PR #1, branch `workstream-a-trusted-fix-checkpoints`), 44 tests green.** The `acc<8` gate was actively starving the loop (8/524 fixes trusted, all before the first step); `trusted_fix_mask` trusts 515/524 and moves held-out re-anchor RMSE 30 s 22.2 -> 14.9 m, 15 s 11.4 -> 4.0 m. Blast radius verified contained (run_phone metrics byte-identical, loop closure steady 39.0 m). A2 is two mechanisms + a backstop per the fold below; the innovation gate is built but opt-in/off (pure position-domain). Honest limit: gross faults only, slow bias/spoof passes to the degrade-to-DR path.

### A1. Checkpoint wiring (independent of everything)
- **Why:** the protocol mandates surveyed checkpoints and M4 (checkpoint P95) is a PASS/KILL criterion, but `checkpoint_errors` in `pdr_bench/eval/phone_metrics.py` exists and is only called by a unit test. No CSV ingestion exists; the shakedown `Annotation.csv` is 0 bytes.
- **Build:** a small surveyed-checkpoint CSV loader (schema `label, lat, lon` or `label, n, e`), converted to `marker_ne` in the session frame, plus event-marker times from Sensor Logger `Annotation.csv`. Wire the existing `checkpoint_errors` into `run_phone.py` / `reanchor_phone.py` and print per-checkpoint error against the M4 bound.
- **Test:** a synthetic checkpoint CSV fixture (the shakedown has none) asserting known offsets.

### A2. Trusted-fix mask: outlier reject + cold-start trim + accuracy-gate fix (build as ONE change)
This is the seam the research trusted-anchoring policy plugs into. Build a pure function `trusted_fix_mask(gnss_t, gnss_ne, acc, ...)` in a new `pdr_bench/pdr/trusted_fix.py`, and call it in `reanchor_phone.py` where it currently does the bare `acc < TRUSTED_ACC_M` gate. Keeping the change on the `gnss_*` stream keeps the blast radius to `heldout_reanchor_rmse` only; `loop_closure_error` (GPS-free, selection-invariant with fixed `--k`) and every `*_vs_gps` metric stay stable. Do NOT push it into `load_phone`'s `gt_ne` origin (widens the radius to all metrics).

Three concerns, but only **two mechanisms plus a backstop** (a review correction): a motion-time IMU-vs-GNSS innovation gate, a stationary dispersion lock-detector, and a loose reported-accuracy floor. Why not three: "dispersion-based quality" is only definable at rest. While walking, fix scatter is dominated by real displacement (~12 m per 8 s), so you cannot separate GPS noise from motion without a motion model, and that model is PDR. So the motion-time quality estimate *is* the innovation gate, not a separate part. All three concerns are exercisable on `ma_ling_walk` (it has the 808 m outlier AND the cold-start scatter):
- **Outlier reject + motion-time quality (mechanism 1, the innovation gate).** Reject fixes whose displacement vs the PDR-predicted position exceeds a gate (a MAD residual gate, or a max-plausible-walking-speed jump). An 808 m jump is non-physical regardless of research. **Finding:** this MAD/innovation residual gate is exactly the research's Cluster B rank-1 deployable win (the IMU/PDR-vs-GNSS consistency gate), and it works on iOS because it is position-domain (no raw GNSS needed). Build it as the real mechanism, not a placeholder floor. It catches only gross faults, which is the honest limit: a slow spoof under ~0.3-0.5 m/s stays inside the gate, and that is the degrade-to-dead-reckoning case, not a detector to build. This same gate is the walking-time quality estimate: there is no separate dispersion-quality while moving.
- **Cold-start trim (mechanism 2, stationary lock-detection).** Detect receiver lock `t_lock` from fix **dispersion** (not reported accuracy) and drop pre-lock fixes. **Finding:** reported accuracy is unreliable in both directions (iOS said 8.9 m at the closing static when actual scatter was std 1.2 m), so lock detection must key off dispersion.
- **Accuracy-gate fix (drop the gate to a loose backstop, NOT a third mechanism).** `TRUSTED_ACC_M = 8.0` in `reanchor_phone.py` gates on iOS's *reported* accuracy, which our GPS correction showed is ~7x pessimistic (14 m reported = ~1-2 m actual). So `acc < 8.0` rejects ~90% of usable fixes on the shakedown and starves the loop. Drop it as the primary gate and keep only a loose reported-accuracy floor (reject absurd reports, e.g. > ~50 m); real quality comes from mechanism 1 in motion and mechanism 2 at rest. Do not build the outlier/cold-start hygiene on top of a broken base gate.
- **Named residual (review): loosening the gate is not free.** The innovation gate is a high-pass filter on GNSS error: it catches fast jumps (the 808 m spike), passes any slowly-correlated bias. Urban multipath is exactly that, a non-adversarial slow bias that re-anchors accumulate into the track, indistinguishable from the slow spoof the gate already cannot catch. So neither the innovation gate nor the backstop bounds slow GNSS bias. That is the degrade-to-dead-reckoning case, not a detector to build, but the uncertainty cone (B3) must own it.
- **Test:** unit tests on `trusted_fix_mask` (synthetic 808 m spike + pre-lock scatter rejected; good fixes with pessimistic reported accuracy kept).

### A3. Real-phone regression test (harness with A2, baseline after)
- **Build:** `tests/test_phone_regression.py` with `skipif(not (data/phone/ma_ling_walk).exists())` (the project skip idiom; no `conftest.py`). Load the walk, run `run_phone` + the held-out re-anchor metric, assert the shakedown numbers within tolerance.
- **Finding / gotcha:** the report's cadence numbers (15 s -> 4.0 m, 30 s -> 14.7 m) were computed with ALL fixes passed straight to `heldout_reanchor_rmse`, bypassing `reanchor_phone.py`'s `acc < 8.0` gate. The script gates; the analysis did not. So re-derive the regression baseline from exactly how the script gates, and expect the numbers to shift once A2 fixes the gate. Harness first (capture current numbers), re-baseline after A2 lands.

## 4. Workstream B: research-informed builds (unblocked with direction; validate on the walk)

These are the algorithm changes the research now points to. B1 can prototype on the existing 595 m walk today; the rest want the multi-km walk to validate.

### B1. Spine inversion: map-matched heading on our own data (highest future value)
- **Why:** this is finding 1+2 made concrete. The map is the only offline heading bound.
- **Finding:** street-graph map-matching (particle filter or CRF) with turn/wall heading resets is the one offline method that bounds heading AND is measured on a real phone: 45-64% median PDR-error cut (Sensors 2015, PMC4435204; MapCraft CRF runs sub-10 ms on Android, no training). **But every published phone number is an indoor corridor.** The deepest risk is map staleness: a disaster zone violates the stored map and the filter confidently snaps onto a wrong street, undetectable offline. It gives nothing in open plazas or on long junction-free straights.
- **First prototype:** run PF and CRF map-matching against a cached OSM footway/street graph on our own 595 m `ma_ling_walk` and measure the real outdoor heading/position bound, plus the degradation on open segments. No new data needed.
- **Measured (2026-07-08, PRELIMINARY / venue-caveated):** built the machinery (matched-edge bearing extraction in `mapmatch/match.py`; a `map_reanchored_track` heading corrector via a behavior-preserving `reanchored_track` refactor; `scripts/map_heading_experiment.py`; 4 tests) and ran it on `ma_ling_walk`. **Map-heading correction does NOT bound drift here:** naive is ~2.5x worse than pure gyro (loop closure 39 -> 99 m, cross-track 45 -> 99 m); a confidence-gated (<8 m snap) variant trades a cross-track gain (45 -> 38 m) for a worse loop closure (39 -> 136 m); neither approaches the GNSS-15 s reference (3.5 m loop closure). Root cause: 18 m median matched-edge snap distance, i.e. wrong-edge snapping of the drifted PDR track in a cramped 23-node / ~50 m-edge / 3-identical-loop block (`out/map_heading.png` shows the corrected track diverging ~150 m). Consistent with pushback #2 but confounded by (a) cramped venue and (b) single-pass matching on drifted input (circular; a real corrector iterates match<->correct and gates on match confidence). NOT a clean KILL: the decisive test is this same machinery on the 2-3 km walk (distinct streets, longer edges), now ready. Used the existing Leuven HMM matcher, not new PF/CRF (cheaper; answers the KILL question first).

### B2. Map-conflict monitor (the unified detector; strongest new idea)
- **Finding:** the deepest map-matching failure (a stale map) and the one spoof class the A2 gate cannot catch (a slow self-consistent drag) produce the **same** offline signal: sustained particle-weight collapse, a three-way disagreement between PDR, map, and GNSS. A spoofer keeping GNSS self-consistent still has to walk you through a wall or onto a wrong street. Same signal, same response (fall back to raw PDR, widen the cone). This is the "non-inertial cross-check" the spoofing literature keeps naming as the only offline defense, and nobody has built it for pedestrians.
- **Build:** a map-conflict score off the B1 map-matcher (particle-weight collapse / map-vs-PDR-vs-GNSS residual) that triggers the degrade-to-dead-reckoning fallback. Highest-value, least-explored.

### B3. Adaptive trust-driven cadence and cone
- **Finding:** the 15-20 s cadence and the uncertainty cone are currently constants. They should be functions of the trust state. When the map is bounding heading well (dense geometry, low map-conflict, clean fixes) AND junctions are frequent, relax GNSS cadence and shrink the cone. When map-conflict rises, a jamming flag fires, or geometry goes open, tighten cadence, widen the cone, lean on dead reckoning.
- **Correction (review): "geometry-poor" is two axes, not one, and cadence keys on the along-track axis.** Map-matching bounds *heading* (cross-track) but never *along-track*: that is step-1's own TEST_05 result (cross-track 10.3 -> 7.2 m yet overall RMSE stuck 18 -> 16.5 m). So relaxing GNSS cadence moves the error budget onto along-track, which only a junction or a GNSS fix resets. Along-track is bounded by `min(junction spacing, GNSS cadence)`. A long walled arterial is geometry-*rich* for heading (street bearing bounds it continuously) and geometry-*poor* for along-track (no junction to reset distance), so heading-geometry alone is the wrong trigger. Keep GNSS tight on junction-sparse arterials even when the map is bounding heading perfectly. This is the reframe's own "GNSS = scarce along-track hint" made concrete: the hint must stay frequent exactly where junctions are sparse.
- **Build:** wire the A2 trust signals and the B2 map-conflict score into the re-anchor loop cadence and the cone width, keyed on junction spacing (along-track exposure) as well as heading-geometry. Cheap to add to the existing loop.

### B4. Pose robustness (protects the number we already have)
- **Finding:** our 6.5% is one favorable hold. Carrying-mode classification (Guo et al., Sensors 2018, 92.4% over 16 modes) then a pose-specific PDR model prevents a ~2x blowup in pocket/swing. This is a precondition, not polish: the map-matcher's turn detection (which the whole heading bound depends on) degrades first in a pocket.
- **Build:** carrying-mode classifier switching step-length gain + heading-offset per carry. Validate against the walk's scripted pose sequence (see Section 2).

## 5. Workstream C: deferred / hardware tier / lower priority

- **Adaptive stride model + calibration leg** (research Cluster C rank 2). Along-track is a real floor, not a rounding error: step-1 data showed it dominating once map-matching corrected cross-track (cross-track 10.3 -> 7.2 m yet overall RMSE stuck 18 -> 16.5 m). Realistic ~4-5% with a per-user calibrated gain. **Promoted (review): this is a co-requisite of the inversion on junction-sparse segments, not deferred polish.** Inverting the spine (relaxing GNSS to lean on the map) exposes along-track exactly where the map cannot help, on long arterials, so C1 must be in scope for those segments and sequenced with B3's junction-spacing cadence. It stays lower priority on turn-rich routes, where junctions reset along-track for free.
- **Free-space building-footprint matching** (Cluster C rank 3). Kills the ~5 m centerline offset where footprints are dense (1.47-2.43 m indoor), near-zero on our set-back residential blocks. Benchmark on the shakedown block before trusting it.
- **Hardware tier: foot-mounted ZUPT pod.** The only thing that fills the irreducible gap (heading is unbounded phone-only in geometry-poor space: open ground, plazas, long arterials, rubble-forced detours). Achieves 0.57-1.25% of distance over km. **Trigger:** promote it exactly when the route is geometry-poor or GNSS is denied/spoofed for long stretches. Same accessory that answers the fully-GPS-denied case.

## 6. Dead ends (verified; do NOT build)

From the research, do not spend time on these (full reasoning in the research doc):
- Magnetometer / MARG as an offline heading or cross-check source (our own data killed it; the field disturbance that could aid position fingerprinting corrupts heading).
- ZARU on a hand/pocket phone (genuine zero-rate windows never occur).
- Magnetic-field fingerprinting for position (needs a pre-surveyed map; outdoor field sits below consumer-magnetometer resolution).
- Learned inertial odometry as a heading fix (no IMU-only method makes yaw observable).
- RTK / carrier-phase spoof detection (needs a base station + Android raw carrier phase; collapses in urban multipath).
- Clock-state (SCV) spoof detection (SDR-validated, ~60 s latency exceeds our cadence).
- GNSS-vs-network and GNSS-time cross-checks (need surviving infra we assume is gone).
- Trace-to-routable-graph map building from a single offline user (needs GPS + redundant passes). Pre-load and verify the map; do not field-build it. Map structure survives offline, geometry does not.
- Camera-VIO stride personalization (fails in night, smoke, crowds, pocket).

## 7. Dependencies and sequencing

- **A1** is independent of everything (research and A2/A3). Do it anytime.
- **A2** is one change (outlier + cold-start + accuracy-gate share the same mask). **A3** depends on A2 for its final numeric baseline (harness first, re-baseline after).
- **B1** can start on the existing 595 m walk now. **B2** builds on B1's map-matcher. **B3** wires A2 + B2 signals into the loop. **B4** validates on the multi-km walk.
- The **2-3 km walk** gates the PASS/KILL verdict for the whole thesis and the real validation of B1-B4.
- Everything in Workstream A is no-regret and does not wait for the walk or the research.

## 8. Verification

- Unit + regression: `cd prototypes/pdr-benchmark && .venv/bin/python -m pytest -q` (48 tests: the 28 originals + Workstream A `trusted_fix`/checkpoint/phone-regression + B1 map-heading, all green).
- End-to-end on the real shakedown, before/after A2, to see held-out RMSE change as the 808 m outlier is rejected and the accuracy gate is fixed:
  `.venv/bin/python -m pdr_bench.run_phone data/phone/ma_ling_walk --k 0.537` and
  `PYTHONPATH=. .venv/bin/python scripts/reanchor_phone.py data/phone/ma_ling_walk --k 0.537`.
- Guardrail: A2 must change only `heldout_reanchor_rmse`, leaving `loop_closure_error` and `*_vs_gps` stable (confirms the blast radius stayed contained).

## 9. Pointers

- Research report (findings, ranked mitigations per cluster, dead-ends, 120 sources): `docs/research/2026-07-08-navigation-mitigations-research.md`.
- Other session's keyboard plan (superseded by Section 3 here, with the accuracy-gate correction): `~/.claude/plans/for-these-next-steps-staged-liskov.md`.
- Project state, findings, and the walk protocol: `STATUS.md` and `prototypes/pdr-benchmark/PHONE_WALK_PROTOCOL.md`.
