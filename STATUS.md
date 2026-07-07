# STATUS: Apocalypto — offline apocalypse navigation app

> Living state. Update at the end of every working block so a fresh session can resume from here after `/clear`.

Last updated: 2026-07-07
Branch / worktree: `main` — public repo at https://github.com/hayden1126/apocalypto

## Done
- **Git initialized and published.** Public GitHub repo `hayden1126/apocalypto`; initial commit `c2aeedd` (5 files, research phase). Commits use `haydenleung1126@gmail.com` (already public across Hayden's other repos, so no noreply switch).
- **Research/concept phase complete.** Three adversarial multi-agent research runs (105 agents, 56 load-bearing claims verified, ~4.2M tokens, all 2026-07-07). Full sourced reports in `docs/research/`:
  - `2026-07-07-offline-apocalypse-nav-research.md` — core 4 tracks (GPS-denied positioning, CV localization, mesh+trust, hardware/power/EMP).
  - `2026-07-07-capture-features-exploration.md` — Feature 1 (re-survey/mapping) + Feature 3 (fixed-vantage change detection).
  - `2026-07-07-wilderness-drone-exploration.md` — coast/island graceful-degradation go/no-go + optional drone gear tier.
- **Scannable HTML decision brief** published as a Claude artifact: https://claude.ai/code/artifact/fd2b9daf-8ae3-4b4c-8910-cd6b14551dcf (durable source saved at `docs/brief.html`; sections 01 tracks, 02 positioning stack, 03 MVP, 04 capture layer, 05 wilderness/drone reach, 06 risks, 07 method).
- **Project memory** written: `~/.claude/projects/-home-hayden-apocalypto/memory/apocalypto-nav-project.md` (spine + rulings).
- **Research plan** archived at `~/.claude/plans/goofy-wandering-treehouse.md`.

## In flight
- **PDR + map-matching benchmark (step 1) BUILT and MEASURED.** Harness at `prototypes/pdr-benchmark/` (Python, 9 tests green). Runs a real classical PDR pipeline (step detection, Weinberg step length, AHRS heading) plus GNSS-anchored OSM map-matching (leuven HMM) against the open GEOLOC/ULISS dataset (6 outdoor tracks, 230-565 m, worn low-cost MEMS IMU, foot-mounted + per-stride ground truth). This de-risks the pipeline and gives a first signal; it is not proof (worn IMU not a phone, sub-km, few-metre GT). Findings below.

## Findings (step 1, 2026-07-07)
- **PDR half PASSES the gate.** Gyro-only PDR (with static-phase gyro-bias removal) holds rmse ~3% of distance on every outdoor track: TEST_02 6.7 m / 230 m, TEST_04 13.2 m / 375 m, TEST_05 18.0 m / 565 m, TEST_06 14.0 m / 465 m. Squarely in the 2-5% regime the literature predicts. Phone-only PDR is viable at street scale for hundreds of metres.
- **The magnetometer HURT.** Naive Madgwick MARG fusion degraded heading badly (rmse 28-137 m) across all tracks; gyro + static-bias-removal wins. Naive mag fusion is not a usable absolute-heading reference; it needs hard gating or a different mechanism.
- **Heading drift is UNBOUNDED without an absolute reference,** so the longest track is the worst. This is the real limiter for the multi-km claim: over km, heading error will exceed street spacing.
- **Map-matching corrects "which street", not "where along it".** Graph/matcher floor is ~5 m (OSM footway-centerline offset from the actual walked path, the pedestrian-graph pitfall quantified). On dense urban (TEST_05) map-matching recovered ~90% of the correct route and cut cross-track error 10.3 -> 7.2 m, but overall rmse only 18 -> 16.5 m because along-track (step-length) error dominates and matching cannot fix it. On open/parking (TEST_06) it was near-neutral. It is NOT a drift-correction oracle: it only disambiguates while drift stays below street spacing.
- **Periodic GNSS re-anchoring BOUNDS the drift, and the required frequency is quantified.** Simulated on the GEOLOC GNSS (`scripts/reanchor_experiment.py`, `out/reanchor_curve.png`): PDR fills the gaps between occasional trusted fixes; a fix every ~30 s (~35 m at walking pace) holds residual RMSE <=5-6 m on every track including urban; every ~15 s reaches ~3-4 m (the raw GNSS noise floor). So the "degraded GPS" premise is workable: continuous GPS is not required, only occasional trusted fixes. Two caveats: a single early anchor is useless (value is in REPEATED anchoring); and each fix must be TRUSTED, so GNSS spoofing (the brief's structural risk) attacks this loop directly.

## Blocked / decisions needed
- **Load-bearing unknown, largely answered on this data.** Phone-scale PDR works for hundreds of metres (2-5%), heading drift is unbounded on its own, and periodic GNSS re-anchoring bounds it to street level. Remaining before the multi-km architecture is committed: (1) does it survive PHONE-grade IMU noise (worse than this worn Xsens)? (2) does the picture hold at true multi-km length? Both need a phone.
- **Next-step decision (Hayden chose the re-anchor experiment first; now done).** Natural next: **self-collect one multi-km phone walk** with logged GPS, plugged into the now-validated harness, to confirm phone-grade noise + multi-km length + the re-anchor frequency in real conditions. Alternative still on the table: SHL dataset (phone IMU at scale, no legwork, but coarse GPS truth and short everyday-life segments).

## Notes for next session
- **Design center is locked: urban/populated disaster + civil unrest.** Phone-first + optional companion hardware (LoRa/solar). Wilderness and drone are gated optional tiers, never core.
- **Key rulings (don't relitigate):** automatic camera self-localization is REJECTED (perceptual aliasing); camera is a mapping tool only. F3 change-detection = near-shippable classical core; F1 re-survey = "dumb" capture/dedup/bulk-sync layer, reconstruction deferred. Coast/island = GO as solo survival mode, NO-GO as a disaster app. Drone = optional, owner-gated, aerial re-survey is the strongest role.
- **MVP definition (buildable, from the brief §03–04):** offline vector maps + routing; positioning L0–L2 (gated GNSS → IMU PDR → OSM map-matching) with an honest uncertainty cone; BLE hazard mesh + optional LoRa; signed + N≥3-corroborated + TTL trust gate; duty-cycled power + dark map; companion LoRa/solar; F3 change-detection core; F1 capture layer; one shared pointer-vs-bulk data model + LocalSend-style transport.
- **Biggest cross-cutting risk beyond PDR:** adversarial — GNSS spoofing is undetectable offline, and no serverless mesh is Sybil-proof. Handled structurally (dead reckoning as trusted backbone; gate every hazard report), not with better sensors.
- To iterate on the brief without rebuilding: edit `docs/brief.html`, re-publish via Artifact (pass the artifact URL above) to the same URL. To re-run/extend a research workflow: scripts are under `~/.claude/projects/-home-hayden-apocalypto/.../workflows/scripts/`.
- **Verification target now exists:** `cd prototypes/pdr-benchmark && .venv/bin/python -m pytest -q` (9 tests) and `.venv/bin/python -m pdr_bench.run --track TEST_05` (writes `out/<track>_metrics.json` + `_overlay.png`). Dataset (DOI 10.57745/ZCBIIB) is gitignored under `data/geoloc/`; re-download if absent. The one non-obvious bug fixed: the AHRS reports ENU yaw (CCW from East) and must be negated to a compass heading, else the whole trajectory mirrors and rmse explodes (guarded by `tests/test_pipeline.py`).
