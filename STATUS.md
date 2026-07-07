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
- **Decision pending: what to build/measure first.** No implementation started. The recommended next concrete step (my strong lean, not yet chosen by Hayden) is to **prototype the PDR + map-matching benchmark**: a minimal harness walked around a real neighborhood to measure whether map-matched, phone-only pedestrian dead reckoning holds street-level accuracy over a real multi-km walk. Alternatives on the table: (2) start a formal design/spec cycle for the MVP, (3) more feature exploration (I pushed back on this).

## Blocked / decisions needed
- **THE load-bearing unknown:** no validated multi-km, phone-only PDR benchmark exists anywhere. It gates the entire positioning backbone, which gates every capture feature (they all consume position). Must be measured before the architecture is committed. If it fails, the product needs a foot-mounted ZUPT sensor accessory — cheaper to learn from a weekend prototype than a built app.

## Notes for next session
- **Design center is locked: urban/populated disaster + civil unrest.** Phone-first + optional companion hardware (LoRa/solar). Wilderness and drone are gated optional tiers, never core.
- **Key rulings (don't relitigate):** automatic camera self-localization is REJECTED (perceptual aliasing); camera is a mapping tool only. F3 change-detection = near-shippable classical core; F1 re-survey = "dumb" capture/dedup/bulk-sync layer, reconstruction deferred. Coast/island = GO as solo survival mode, NO-GO as a disaster app. Drone = optional, owner-gated, aerial re-survey is the strongest role.
- **MVP definition (buildable, from the brief §03–04):** offline vector maps + routing; positioning L0–L2 (gated GNSS → IMU PDR → OSM map-matching) with an honest uncertainty cone; BLE hazard mesh + optional LoRa; signed + N≥3-corroborated + TTL trust gate; duty-cycled power + dark map; companion LoRa/solar; F3 change-detection core; F1 capture layer; one shared pointer-vs-bulk data model + LocalSend-style transport.
- **Biggest cross-cutting risk beyond PDR:** adversarial — GNSS spoofing is undetectable offline, and no serverless mesh is Sybil-proof. Handled structurally (dead reckoning as trusted backbone; gate every hazard report), not with better sensors.
- To iterate on the brief without rebuilding: edit `docs/brief.html`, re-publish via Artifact (pass the artifact URL above) to the same URL. To re-run/extend a research workflow: scripts are under `~/.claude/projects/-home-hayden-apocalypto/.../workflows/scripts/`.
- No verification target exists yet (no code). First code milestone should be the PDR benchmark harness above.
