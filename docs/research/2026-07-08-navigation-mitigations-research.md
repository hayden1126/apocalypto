# Navigation problems and mitigations: what our runs exposed, what the literature offers

Date: 2026-07-08. Scope: our offline, GPS-degraded, phone-first pedestrian navigation stack for urban disaster and civil-unrest zones.

Method: an 11-problem triage from our own step-1/step-2 runs, then a 15-subtopic literature sweep across three deep-dive clusters (60 research + adversarial-verification agents, ~2.7M tokens, 120 unique real sources spanning 2002-2026). Every load-bearing claim was handed to a skeptic agent instructed to check whether the lab or foot-mounted number transfers to a phone-grade sensor, offline, outdoor-urban. Numbers below are tagged by envelope tier: **offline** (zero infrastructure), **peers** (opportunistic phone-to-phone only), **infra** (needs some surviving WiFi/cell/GNSS), **hardware** (needs a companion device).

## The verdict in one paragraph

Heading drift is the root problem, and no phone sensor can fix it. Yaw is provably unobservable from accelerometer plus gyro (gravity fixes only roll and pitch), so ZUPT, ZARU, magnetometer fusion, and learned inertial odometry all fail to bound it. The one offline thing that can bound heading on a real phone is the **map**: a street or footway graph that kills through-a-wall trajectory hypotheses at every turn. That points to an inversion of our current spine. Today GNSS re-anchoring is the heading fixer (every 15-20 s) and map-matching is a secondary "which-street" aid. The evidence says flip it: let the map bound heading continuously where geometry exists, and demote GNSS to a scarce along-track correction that must pass a consistency gate. On the trust side the split is clean: gross faults (our 808 m outlier, cold-start garbage) are cheaply killed by an IMU-vs-GNSS gate, jamming onset is detectable only on Android and only transiently, and a competent slow spoofer is undetectable phone-only. So the honest design stance is to gate the easy faults and **degrade to dead reckoning on trust loss** rather than pretend to out-detect a spoofer. Pose is the sleeper risk: our 6.5% baseline was one favorable hold, and an unconstrained phone roughly doubles it.

## The 11 problems (triage)

Four layers, ranked by leverage. P5 (heading) and P4 (spoofing) are the two that break the thesis.

| # | Problem | Layer | Leverage | Phone-only tractable? |
|---|---------|-------|----------|-----------------------|
| **P5** | Heading drift, unbounded | PDR | Critical (root) | Only via the map |
| **P4** | Jamming / spoofing | GNSS | Critical (unrest) | No (degrade, don't detect) |
| **P11** | Re-anchor cadence penalty (15-20 s) | Loop | High | Yes, by fixing P5 |
| **P2** | Outlier fixes (808 m) | GNSS | High | Yes (cheap) |
| **P7** | Magnetometer gives no absolute heading | PDR | High | No (confirmed dead) |
| P8 | Along-track / step-length error | PDR | Medium | Partial (calibration) |
| P10 | Map-matching coverage (44% edges) | Map | Medium | Partial (geometry-bound) |
| P9 | Pose sensitivity | PDR | Medium (sleeper) | Yes (classification) |
| P6 | Gyro bias drift | PDR | Medium | Folds into P5 |
| P1 | Cold start | GNSS | Low-med | Operational (warmup) |
| P3 | OS accuracy over-reporting | GNSS | Low | Yes (self-estimate) |

## Where the problems bite (scenarios)

The problems are not independent. In every design-center scenario, degraded GPS shifts weight onto PDR, and the failure pair is always the same: **heading drift (P5) plus untrustworthy fixes (P4)**.

- **Dense collapsed urban core** (earthquake, highrise canyon): multipath starves the fix (P1, P3), footways are buried (P10), steel and rubble kill the compass (P7). You live on PDR.
- **Civil unrest / conflict**: active jamming and spoofing (P4) make the trusted fix untrustworthy, so the re-anchor loop (P11) is compromised and you fall back to pure PDR (P5). This is the scenario that breaks the thesis hardest.
- **Indoor / underground** (subway, basement, parking): fully GPS-denied. Pure PDR, heading drift, pose, no OSM graph.
- **Multi-km foot evacuation**: heading drift compounds with distance. This is our untested multi-km failure, plus along-track error (P8).
- **Power-constrained multi-day**: duty-cycling GPS re-triggers cold start on every wake and starves the loop.
- **Smoke / night**: rules out the camera re-anchor tier, forcing more onto PDR.

## Cluster A: bounding heading drift offline (P5 / P6 / P7)

The core result: only the map bounds heading offline, and the number that proves it is measured on a real (poor) phone.

| Rank | Approach | Tier | Gain vs our 6.5% baseline | Key risk |
|------|----------|------|---------------------------|----------|
| 1 | **Street-graph map-matching (particle filter or CRF) with turn/wall heading resets** | offline | Bounds heading where streets are walled/gridded/junction-dense; measured 45-64% PDR-error cut on a real phone (indoor corridor) | Map staleness: a disaster zone violates the stored map, and the filter confidently snaps onto a wrong street, undetectable offline. No constraint in open areas. |
| 2 | Learned inertial odometry (RoNIN / CTIN), on-device | offline | Cuts distance error, absorbs carry mode; unseen-user ~5% of distance | Solves the wrong axis. Inherits gyro-only yaw drift; does not bound heading. |
| 3 | Manhattan-world / dominant-direction heading prior (iHDE) | offline | On grid-aligned walking, in principle well below 6.5% between corrections | Catastrophic on non-grid paths (>20%, worse than doing nothing). No phone-grade number exists. |
| 4 | Foot-mounted ZUPT+ZARU with a heading aid | hardware | 0.57-1.25% of distance over km (5-10x better) | Needs a foot IMU, and still needs a separate heading aid (yaw stays unobservable). |
| 5 | Simulated-ZUPT on a handheld phone | offline | Mild position damper, 1.4-2.6% on short held-flat walks | Does not touch heading. Pocket/swing heading is 14-17 deg over 80 m. |

**Dead ends (verified not to transfer):** magnetometer / MARG as an offline heading source (our own walk measured it making heading worse, 28-137 m; the literature agrees the same field disturbance that could aid position fingerprinting corrupts heading); ZARU on a hand or pocket phone (genuine zero-rate windows essentially never occur); magnetic-field fingerprinting for position (needs a pre-surveyed 0.1-0.3 m map that cannot exist for an unknown zone, and outdoor field variation sits below a consumer magnetometer's resolution); treating learned inertial odometry as a heading fix (no IMU-only method makes absolute yaw observable; TLIO's own EKF treats yaw as unobservable); plain non-gated HDE on any non-grid path.

Lead sources: MapCraft CRF (Xiao et al., IPSN 2014, sub-10 ms on Android, no training); vector-graph PDR on an unconstrained smartphone (Sensors 2015, PMC4435204, the 45-64% figure); RoNIN (ICRA 2020); the ZUPT review (Wahlstrom and Skog, IEEE Sensors 2021); iHDE (Sensors 2018, PMC6021924).

## Cluster B: trustworthy anchoring under attack (P4 / P2 / P3 / P11)

The problem splits cleanly, and the phone-only wins are narrow.

| Rank | Approach | Tier | What it buys | Key limit |
|------|----------|------|--------------|-----------|
| 1 | **IMU/PDR-vs-GNSS consistency gate** (chi-square innovation + kinematic plausibility, Huber weight) | offline | Deterministically rejects the 808 m outlier and cold-start garbage. Works on iOS (position domain, no raw GNSS). | Catches only gross faults. A slow spoof under ~0.3-0.5 m/s stays inside the gate forever. |
| 2 | AGC + C/N0 jamming-onset flag | offline (Android only) | Real-time "GNSS is compromised" flag, single antenna | Zero on iOS (no raw signal). Transient only (AGC re-baselines). Urban-canyon multipath triggers false flags. |
| 3 | Robust factor-graph smoothing (switch variables / Huber / GNC) | infra | Retroactively down-weights a wild earlier fix; preserves PDR shape | 1.36 m headline is offline batch, not real-time phone. Degenerates to an unbounded smoother when GNSS is denied. Zero defense against a self-consistent spoof. |
| 4 | Peer cross-consistency over our mesh | peers | Steady-state jam/spoof detection a single phone cannot get; emitter localization at density | Needs phone density and a surviving comms path (the thing that is degraded). A uniform spoof defeats it. |
| 5 | Self-estimated fix quality replacing OS accuracy (P3) | offline | Recovers the ~1-2 m fixes iOS mislabels as 14 m; sizes the cone to the real error | Precision, not integrity. A smooth spoof produces a tight, confident, wrong cluster. |
| 6 | Companion hardware (foot IMU, or multi-antenna / RTK GNSS) | hardware | The only real answer to slow spoof (spatial diversity) and unbounded heading | Out of the phone tier. RTK needs a base station and correction stream a jammed zone lacks. |

**The design stance (this is the load-bearing conclusion):** gate hard against gross faults and jamming onset, treat GNSS as an untrusted, occasionally-poisoned input, and **degrade to dead reckoning on trust loss** rather than expecting to detect a competent spoofer. Do not launder the lab meter-numbers (2 s carrier-phase, 100%-by-60 s clock detection, 1.36 m FGO) into our setting. They are car, SDR, or batch results on hardware we are not shipping.

**Dead ends (verified):** carrier-phase / RTK residual monitors (need a base station and Android raw carrier phase, collapse in deep-urban multipath); the SCV clock-state detector (SDR-validated, needs raw pseudorange, and its ~60 s latency exceeds our 15-20 s cadence so a spoof corrupts several anchors first); GNSS-vs-network cross-check (needs surviving WiFi/cell, gone in our model); GNSS-time consistency (needs a trusted external clock); the mock-location flag (only catches software fake-GPS apps, blind to RF); the accelerometer-vs-Doppler one-time-pad (a pedestrian's steady 1.4 m/s gait is too weak a signature); the magnetometer as an independent heading cross-check (our own experiment killed it).

Lead sources: loosely-coupled INS/GNSS fault detection with Mahalanobis gating (J. Geodesy 2013); Android jam/spoof detection (Spens et al., NAVIGATION 2022, the >5 dB AGC figure); crowdsourced smartphone jamming detection (Strizic et al., ION ITM 2018); anchor-aided GNSS/PDR factor-graph optimization (Sensors 2025, PMC12430939, the 1.36 m and 11.04 to 2.61 m figures); covert-spoof drift budget (Sci. Reports 2025).

## Cluster C: PDR quality, along-track and map coverage (P8 / P10 / P9)

None of these fixes the heading growth rate, but they bound and floor the error around it. The reframe: pose is the biggest unhedged risk, and along-track is a real floor, not a rounding error.

| Rank | Approach | Tier | Gain | Key limit |
|------|----------|------|------|-----------|
| 1 | **Carrying-mode classification, then pose-specific PDR** | offline | Prevents a ~2x blowup (pocket/swing 3.0-3.4 m vs hold 1.4 m over 164 m). Protects the 6.5% number we measured. | Pose transitions (pocket to text) are the untested weak point. |
| 2 | Adaptive / learned stride model + a counted calibration leg | offline | Tightens the along-track floor to ~4-5% (our step-1 data: cross-track cut 10.3 to 7.2 m but overall RMSE stuck 18 to 16.5 m, so along-track dominates) | The good end needs a known distance; the calibration goes stale as gait changes. Uncalibrated Weinberg/Kim is 13-22%. |
| 3 | Free-space building-footprint matching (cross-wall particle rejection) | offline | 1.47-2.43 m cross-track where footprints are dense | Constraint strength equals geometry density, which our failing set-back blocks lack. Does nothing for along-track. |
| 4 | Open-space interior graph (visibility / spider-grid) for plazas | offline | Recovers matchability where centerline matching has nothing to snap to (our 44% case) | A representation, not a fix. A denser candidate set may increase mis-association under 6.5% drift. |
| 5 | Map/geometry loop-closure stride personalization | offline | Keeps k calibrated as gait drifts, without GPS or VIO | Weakest exactly on the open blocks where we most need it. |
| 6 | Sidewalk-snap the GNSS re-anchor | infra | 2 m, correct side 97.5% (urban canyon) | Inert during the cold-start / jam / spoof window it appears to help. |

**Dead ends (verified):** uncalibrated generic Weinberg/Kim (13-22%); barometric/DEM elevation matching on flat urban ground (48-72 m, degenerate); building a routable map from a single offline user's traces (needs GPS to georeference and 2-3 redundant passes, and with our jammed GNSS you cannot even build the density image); camera-VIO stride personalization (fails in night, smoke, crowds, pocket); magnetic SLAM at outdoor street scale (non-stationary field around vehicles and rebar). The rule: map **structure** (connectivity) survives offline and should be pre-loaded and verified; map **geometry** does not survive and cannot be field-built.

Lead sources: carrying-mode classification (Guo et al., Sensors 2018, PMC6021937, 92.4% over 16 modes); adaptive step length (Ho et al., Sensors 2016; Vezocnik et al., Sensors 2022); free-space / footprint matching (Sensors 2013 SCIRP; open-spaces routing, Graser 2016); sidewalk matching (Satellite Navigation 2025).

## My synthesis: the architecture the evidence points to

Six ideas emerge when the three clusters are read together, not separately. The first four change our design; the last two set the boundaries.

**1. Invert the spine: the map is the heading corrector, GNSS is the along-track hint.** Our current L0-L3 ladder makes GNSS re-anchoring the heading fixer and map-matching a secondary "which-street" aid. Every result above says flip it. Sensors cannot bound yaw; the street graph can, by killing through-wall hypotheses at turns. So map-matching should be promoted to the **primary offline heading bound** wherever geometry exists, and GNSS demoted to a scarce absolute-position and along-track correction that must clear the consistency gate. This one move attacks P5 (heading), relaxes P11 (cadence, because the map is now doing the between-fix heading work), and shrinks the P4 attack surface (fewer trusted fixes needed means less to spoof). Three problems, one inversion.

**2. Build the map-conflict monitor: one detector for the two failures nobody else catches.** The sweep flagged, independently in Cluster A and Cluster B, that the deepest map-matching failure (a stale map in a changed disaster zone) and the one spoof class the consistency gate cannot catch (a slow, self-consistent drag) produce the **same** offline signal: sustained particle-weight collapse, a high map-conflict score, a three-way disagreement between PDR, the map, and GNSS. A competent spoofer that keeps GNSS internally consistent still has to walk you either through a wall or onto a wrong-but-plausible street, and that shows up as map conflict even when every pairwise check passes. The correct response to both failures is identical: stop trusting the map and GNSS, fall back to raw PDR, widen the cone. This is the "non-inertial cross-check" the spoofing literature keeps naming as the only offline defense, and nobody has built it for pedestrians. I think it is the single highest-value thing we could prototype.

**3. Make cadence and cone width functions of trust, not constants.** Right now the 15-20 s re-anchor cadence and the uncertainty cone are fixed. They should adapt to the trust state. When the map is bounding heading well (dense geometry, low map-conflict, clean fixes), relax GNSS cadence and shrink the cone. When map-conflict rises, a jamming flag fires, or the geometry goes open (plaza, long junction-free arterial), tighten cadence, widen the cone, and lean on dead reckoning. This wires Cluster B's trust signals directly into the positioning loop, and it is cheap to add to the re-anchor code we already have.

**4. Pose classification is a precondition, not a nicety.** Our 6.5% is one favorable hold. Everything above (the map-matcher's turn detection, the stride model, the consistency gate's PDR reference) is tuned for that pose and degrades ~2x in a pocket. The turn detection that the entire map-heading bound depends on gets noisier first. So carrying-mode classification is what keeps the whole loop working in real use, and it belongs early, not as polish.

**5. Along-track is a floor to defend, not a solved problem.** The tempting framing is "heading is everything, spend nothing on distance." Our own step-1 data refutes it: once map-matching corrected cross-track (10.3 to 7.2 m), overall RMSE barely moved (18 to 16.5 m) because along-track step-length error dominated the residual. Heading is the unbounded-growth risk and comes first, but a calibrated adaptive stride model is the floor that map-matching and re-anchoring cannot touch. Keep the counted calibration leg, and let k adapt to speed.

**6. The honest ceiling, and a crisp hardware trigger.** Phone-only, offline, in geometry-poor space (open ground, plazas, long arterials, rubble-forced off-grid detours), nothing bounds heading. That gap is irreducible. The foot-mounted ZUPT pod is the only thing that fills it (0.57-1.25% over km), and it is the same accessory that answers the fully-GPS-denied case. So the hardware tier gets a precise, defensible trigger: promote it exactly when the route is geometry-poor or GNSS is denied or spoofed for long stretches. Not always, not never, but on a condition we can detect.

## What to prototype next (ranked, tied to the pending 2-3 km walk)

1. **Map-matched heading on our own data.** Every published phone map-matching number is an indoor corridor. Run particle-filter and CRF map-matching against a cached OSM footway/street graph on the real 600 m iPhone walk and measure the actual heading and position bound, plus the degradation in open segments. This tests idea 1 directly and costs no new data.
2. **The IMU-vs-GNSS consistency gate.** Build it, then tune the innovation threshold on the multi-km walk's real cold-start and outlier statistics (we have exactly one 808 m outlier, n=1). This is the one deployable trust win and it closes P2 and the cold-start half of P1.
3. **The map-conflict monitor** (idea 2). Prototype particle-weight-collapse detection as the unified staleness-plus-slow-spoof detector. Highest-value, least-explored.
4. **Pose logging on the multi-km walk.** Script a hold to pocket to swing to call sequence and measure per-pose and transition error against the 6.5% held-flat baseline. This sizes the P9 risk before it surprises us.
5. **Adaptive trust-driven cadence** (idea 3) on the existing re-anchor loop.

Lower priority, after the above: adaptive stride model, a free-space footprint-matching benchmark on the shakedown block, and iHDE on the grid segments.

## Method notes and limits

The 120 sources are real and span 2002-2026 (MDPI Sensors, ION NAVIGATION, arXiv, IEEE, ACM). Each cluster's load-bearing claims were adversarially verified for transfer to our context; the verifier repeatedly downgraded lab and foot-mounted numbers that do not survive phone-grade sensors (the RTK 2 s figure, the 1.36 m FGO figure, indoor magnetic fingerprinting). The recurring caveat across all three clusters: almost every strong number is measured indoors, foot-mounted, or on a car, and the honest phone-outdoor-urban number is either worse or unmeasured. That gap is exactly what our own multi-km walk should close. Full per-subtopic findings, per-claim verification verdicts, and the complete 120-source list are in the workflow output (`nav-mitigations-research`, run wf_93e8f13d-dc9).
