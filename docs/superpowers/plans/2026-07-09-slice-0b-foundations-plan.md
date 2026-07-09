# Slice 0b (foundations): apoc-ffi crossing + region-baker dark PMTiles package

> **STATUS: EXECUTED 2026-07-09.** Both groups are built, review-hardened, pushed, and open as PRs: Group A on `slice-0b-apoc-ffi` (PR #5), Group B on `slice-0b-region-baker` (PR #6). Read the two per-group plan docs (`2026-07-09-slice-0b-apoc-ffi.md`, `2026-07-09-slice-0b-region-baker.md`), their reconciliation notes, and the code for current truth; this file is the as-approved planning artifact, and its task summaries and counts predate the build (it carries no reconciliation note of its own). Machine-local original: `~/.claude/plans/what-is-the-status-enumerated-shore.md`.
>
> Two independent foundations for slice 0b, both fully verifiable on this WSL2 box (no Flutter, no Mac). Recommend shipping as **two separate PRs** (Rust FFI; map package) since they touch unrelated subsystems. Full house-style plan docs with complete code are authored into `docs/superpowers/plans/` as the first execution step of each (see Execution).

## Context

The session opened with "what is the status?". Status: the core positioning thesis PASSES (phone PDR + trusted GNSS re-anchoring holds street level over a real ~2 km walk), and slice-0 of the Rust core shipped and **merged as PR #4** (`cc1d867`; STATUS.md still said "OPEN" -- corrected this session). With slice-0 merged, the chosen next increment is **slice 0b**, the Flutter dark-map half of spec Slice 0.

**The constraint that reshaped scope.** The dev box is WSL2 Linux: Rust 1.96.1, Go 1.26.4, node 22, Java 21 present; **no Flutter, Dart, Xcode, or CocoaPods**, and iOS cannot build on Linux at all. Research into professional practice confirmed nobody develops iOS-first without a Mac (no iOS Simulator off macOS; iOS binaries only sign on macOS). The pro pattern: develop cross-platform locally, ship iOS via cloud-Mac CI + TestFlight ($99/yr Apple), with a used Mac mini (~$300-600) the consensus for serious iOS debugging.

**Decision (Hayden, this session): foundations now, decide the iOS/Mac path later.** Slice 0b's own build order forces the same split: you can't render a dark offline map without a baked package to render, and the Flutter shell needs a crossing to bind to. So this increment builds the two prerequisites that verify on this box with no Flutter and no Mac, and defers the Flutter render + the Mac-vs-CI decision to the next increment. This front-loads spec **Risk 3** (two-reader map-package drift) and the **FFI seam**.

**Intended outcome.** After this increment: (1) `core/apoc-ffi`, the single FFI crossing, exposing the two existing core calls over the direct C-ABI sensor lane, proven with Rust tests + an exported-symbol check; (2) a `region-baker` tool + the first baked dark offline PMTiles package for the walk area (Ma Ling Path, HK), proven with offline integrity/reference/checksum checks.

## Parent spec

`docs/superpowers/specs/2026-07-08-mvp-architecture-scope-design.md` (approved). Like the slice-0 Rust plan, this increment is a PLAN under the parent spec, not a new spec. Load-bearing decisions:
- §4.1 / DTO rule (~line 149): `apoc-ffi` is the single crossing; **two FFI lanes not to be merged** -- the low-rate control/UI lane (flutter_rust_bridge) and the 100 Hz sensor lane (direct C-ABI, bypassing Dart); it exposes flat owned DTOs (no lifetimes, no crypto).
- §10 (region-baker, ~lines 231-238): one off-phone baker takes OSM extract + bbox → one versioned package = vector tiles (pmtiles/mbtiles) + baked graph + spatial index + manifest. "May stay Python."
- §13 Risk 3 (~lines 306-310): one baker, one versioned manifest, both readers assert the same `PackageVersion`, graph + tiles from the same source. **The spec risk directly load-bearing on this increment.**

## Environment reality (verified read-only on this box)

| Tool | State |
|---|---|
| rustc/cargo 1.96.1 | present, **off default PATH** → prefix `export PATH="$HOME/.cargo/bin:$PATH"` |
| Go 1.26.4 | present at `~/.local/bin/go`; installs to `~/go/bin` (off PATH) |
| node 22 / npm 11 | present at `/usr/bin` |
| Java 21 | present (region-baker fallback runtime) |
| cc/gcc, nm, objdump | present (C-ABI proof + symbol check) |
| Docker | **unusable** (WSL integration off) -- no Docker recipes |
| Dart, Flutter, flutter_rust_bridge_codegen | **absent** -- determines "C-ABI now, frb later" |
| pmtiles, tippecanoe, gdal | **absent** -- installed one-time in Task A/B as needed |

Bake-time endpoints confirmed reachable: `build.protomaps.com` (planet, HTTP range OK), `codeload.github.com` (basemaps-assets tarball), `registry.npmjs.org` (`@protomaps/basemaps@5.7.2`, zero deps).

## Scope

**In scope:** the `apoc-ffi` C-ABI crossing over `interp_ne` + `trusted_fix_mask`; the `region-baker` + first dark PMTiles package (tiles + local style + local glyphs + local sprites + manifest) for the Ma Ling bbox; land two STATUS follow-ups now that a binary artifact ships (commit `core/Cargo.lock`; `#![forbid(unsafe_code)]` in the pure crates).

**Out of scope (deferred):** the Flutter app shell, `maplibre_gl` render, and the frb Dart↔Rust round-trip (need Flutter); the frb view types / async runtime / session / capability ports; the baked pedestrian/routing graph (no `apoc-map` reader exists yet -- reserved manifest slot); iOS build/sign/TestFlight and the Mac-vs-CI decision; revising the spec's "iOS-first" line (flagged, not acted on).

## Global constraints

- `export PATH="$HOME/.cargo/bin:$PATH"` before cargo; `export PATH="$HOME/go/bin:$PATH"` (or `~/go/bin/pmtiles`) for the pmtiles CLI.
- Everything a map style references (tile source, glyphs, sprites) must resolve to a LOCAL file -- no `http(s)://` -- or the offline render silently loses labels/icons. The verifier greps for this.
- Commit after every task (conventional commits: `feat(ffi):`, `feat(region-baker):`, `build(ffi):`). Do NOT push. Do NOT merge without approval.
- Match the house style of `docs/superpowers/plans/2026-07-09-rust-core-oracle-l0-gate.md` (Goal / Architecture / Global Constraints / `### Task N` with Files/Interfaces/`- [ ]` RED-GREEN steps/Commit / Self-Review).

---

## Group A -- `apoc-ffi` crossing (Rust, no network; recommend PR first)

**Key decision: build the direct C-ABI sensor lane now; defer flutter_rust_bridge.** frb v2 `generate` is driven by a Dart package config and shells to the Dart SDK (evidenced by its `--no-dart-format`/`--no-dart-fix` opt-outs); with no Dart and no Flutter project, it can't run or be verified. The C-ABI lane (spec §4.1) needs no Dart by design, is on the critical path regardless, and is fully verifiable here. Layer split: `dto` (flat owned DTOs + safe wiring, `#[forbid(unsafe_code)]`) and `capi` (`extern "C"` exports, all `unsafe` confined + `// SAFETY:` + `catch_unwind` panic guards, since `interp_ne` panics on empty input and a panic across `extern "C"` is UB). crate-type `["rlib","cdylib","staticlib"]`.

**Task A1 -- workspace member + flat owned DTO layer.** Add `apoc-ffi` to `core/Cargo.toml` members; create the crate depending on `apoc-geo` + `apoc-positioning`; build `dto.rs` with `InterpNeView { ne: Vec<f64> }` (row-major `[n,e,...]`), `TrustedFixView { keep: Vec<bool> }`, `TrustedFixParamsDto` (flat mirror; `acc_backstop_m` NaN==None) and the safe wiring `interp_ne_view(...)` / `trusted_fix_view(...)`. Deliverable: `cargo build -p apoc-ffi` emits `libapoc_ffi.{so,a}`; `cargo test -p apoc-ffi` passes 2 DTO-wiring tests. _Files: `core/Cargo.toml`, `core/apoc-ffi/{Cargo.toml,src/lib.rs,src/dto.rs}`, `core/apoc-ffi/tests/dto_wiring.rs`._

**Task A2 -- the C-ABI sensor lane + round-trip and symbol proof.** Replace the `capi` stub with `#[repr(C)]` owned buffers (`ApocF64Buffer`, `ApocU8Buffer`), `#[repr(C)] ApocTrustedFixParams`, and the four `#[no_mangle] pub unsafe extern "C"` fns (`apoc_interp_ne` + `apoc_f64_buffer_free`, `apoc_trusted_fix_mask` + `apoc_u8_buffer_free`), each `catch_unwind`-guarded. Verify in-process (Rust integration test calls the symbols and frees), by `nm -D … | grep ' T apoc_'` (four symbols), and optionally by a `cc`-compiled C harness in scratchpad that links the cdylib and frees a Rust-owned buffer (strongest Dart-less ABI proof). Deliverable: `cargo test -p apoc-ffi` passes 5 tests (2 DTO + 3 C-ABI incl. panic-safety); the four symbols export. _Files: `core/apoc-ffi/src/capi.rs`, `core/apoc-ffi/tests/capi_roundtrip.rs`._

**Task A3 -- lock down + close STATUS follow-ups.** Add `#![forbid(unsafe_code)]` to `apoc-geo` + `apoc-positioning` (already unsafe-free → a lock, not a change); un-ignore `/Cargo.lock` in `core/.gitignore` and commit `core/Cargo.lock` (a cdylib/staticlib now ships). Close with `cargo clippy --workspace --all-targets -- -D warnings` clean and `cargo test` all green. _Files: `core/apoc-geo/src/lib.rs`, `core/apoc-positioning/src/lib.rs`, `core/.gitignore`, `core/Cargo.lock`._ Reconciliation: `apoc-ffi` can't take crate-level forbid (`extern "C"` needs raw-pointer `unsafe`); it uses crate-level `#![deny(unsafe_op_in_unsafe_fn)]` + module `#[forbid(unsafe_code)]` on `dto`, confining unsafe to `capi`.

---

## Group B -- `region-baker` + first dark PMTiles package (Python/JS/Go; needs network at bake time)

**Tool choice: `pmtiles extract` from the Protomaps daily planet** (range-extracts only the bbox's tiles from the 136 GB planet → sub-MB/few-MB `region.pmtiles`), because it yields the Protomaps basemaps tile schema the `@protomaps/basemaps@5.7.2` `dark` flavor style is written against -- zero schema translation. Fallback (documented, not plan-of-record): planetiler (Java) from a Geofabrik HK extract + an OpenMapTiles dark style. **Graph deferred** (no `apoc-map` reader exists → unverifiable surface; reserved `graph: null` manifest slot + `graph_crs: EPSG:32650`; osmnx/UTM machinery already in `prototypes/pdr-benchmark/pdr_bench/mapmatch/graph.py`+`georef.py` for later). Package lives under `region-baker/out/<id>/<ver>/` (binaries gitignored; baker source + region config + pinned `package.json`/lock + a small text `manifest.json` copy under `manifests/` committed -- matches the repo's "protocol committed, data gitignored" pattern).

**Risk 3 contract:** manifest schema `apoc.region-package/1` carries `package_version` (e.g. `"ma-ling@1"`) asserted in BOTH the manifest and `style.dark.json.metadata["apoc:package_version"]`; every reader fails loud on mismatch. This increment establishes and verifies manifest==style now, before the graph and renderer exist.

**Task B1 -- scaffold + region config + toolchain bootstrap.** Create `region-baker/` (`bake.py` with `check|tiles|assets|style|manifest|all`, `regions/ma-ling.region.json`, pinned `package.json`, `.gitignore` for `out/`+`node_modules/`, README); `go install github.com/protomaps/go-pmtiles@latest` + `npm install`; `bake.py check` asserts pmtiles/node/`@protomaps/basemaps@5.7.2` present. Deliverable: `python3 region-baker/bake.py check` all-green. (bbox `[114.18764,22.39089,114.22764,22.42089]` is a generous editable guess around the surveyed far-end `22.40589,114.20764`; confirm against the private walk extent.)

**Task B2 -- extract the dark PMTiles for the bbox.** `bake.py tiles` runs `pmtiles extract <planet> region.pmtiles --bbox=… --maxzoom=15`. Verify: `pmtiles verify` clean; `pmtiles show` bounds ⊇ bbox at z15, nonzero tiles; the centroid tile decodes to nonzero bytes (catches an empty/mistargeted extract). Deliverable: `out/ma-ling/1/region.pmtiles` passes all three.

**Task B3 -- local glyphs + sprites + generated dark style.** `bake.py assets` one-shot-fetches the basemaps-assets tarball → copies referenced font stacks (`Noto Sans Regular/Medium/Italic`, full 256-range incl. CJK for Traditional-Chinese labels) into `glyphs/<stack>/` and `sprites/v4/dark.*` → `sprite.dark.*`. `bake.py style` runs `gen_style.mjs` (`layers(namedFlavor("dark"))`) emitting `style.dark.json` with `glyphs:"glyphs/{fontstack}/{range}.pbf"`, `sprite:"sprite.dark"`, `sources.protomaps.url:"pmtiles://region.pmtiles"`, `metadata["apoc:package_version"]`. Verify: `grep -c http style.dark.json` → `0`. _Files add `region-baker/gen_style.mjs`._

**Task B4 -- manifest (PackageVersion + checksums) + offline verifier + one-pass bake.** `bake.py manifest` enumerates files (bytes+sha256), writes the `apoc.region-package/1` manifest (+ committed copy under `manifests/`); `bake.py all` chains tiles→assets→style→manifest under one `package_version` (the one-baker/one-pass Risk-3 property). `verify_package.py` (stdlib) is the increment's gate: `pmtiles verify`; every sprite/glyph(sampled incl. a CJK range)/source reference resolves to a local file; no `http` in the style; `style.metadata package_version == manifest package_version`; all checksums match; file count matches. Deliverable: `python3 region-baker/verify_package.py out/ma-ling/1` all-PASS. _Files add `region-baker/verify_package.py`, `region-baker/manifests/ma-ling-1.manifest.json`._

---

## Verification

**Verifiable on THIS box:**
- **apoc-ffi:** `export PATH="$HOME/.cargo/bin:$PATH"; cd core && cargo test` all green (apoc-ffi adds 5); `cargo build -p apoc-ffi` emits `libapoc_ffi.{so,a}`; `nm -D target/debug/libapoc_ffi.so | grep ' T apoc_'` → 4 symbols; `cargo clippy --workspace --all-targets -- -D warnings` clean; `core/Cargo.lock` tracked; optional `cc` C-harness prints `len=2 ne=[1.0, 2.0]`.
- **region-baker:** `python3 region-baker/bake.py check`; `python3 region-baker/bake.py all`; `python3 region-baker/verify_package.py out/ma-ling/1` all-PASS (integrity, reference resolution, no-network, checksums, package_version match).

**NOT verifiable here (honest limits, deferred):** the Dart↔Rust frb round-trip and `flutter_rust_bridge_codegen` output (no Dart); the iOS `staticlib` link into Xcode (no macOS); the 100 Hz native-thread sensor push (no device/adapters); a MapLibre **pixel** render of the package (no reliable GL on WSL2 + no renderer yet). First visual proof waits for the Flutter increment.

## Execution

1. For each group, **first author and commit the full house-style plan doc** into `docs/superpowers/plans/2026-07-09-slice-0b-apoc-ffi.md` and `…-region-baker.md` (complete file contents + RED/GREEN steps, drawn from the two design passes in the 2026-07-09 session), matching the slice-0 plan doc -- then execute it.
2. Suggested order: Group A first (self-contained, no network, closes the Cargo.lock + forbid-unsafe follow-ups, fast green), then Group B. They are independent -- either order works, and they should be **separate PRs**.
3. Execute with `superpowers:subagent-driven-development` or `superpowers:executing-plans`; commit per task; do not push/merge without approval.

## Notes for the next increment

- The Flutter shell render (`maplibre_gl` on the baked package + the frb Dart round-trip) + the **Mac-vs-cloud-CI iOS decision** are the gate to the following increment.
- Revisit the spec's "iOS-first" line in light of the professional-workflow finding (cross-platform dev, CI-ship iOS).
- STATUS.md corrected this session: PR #4 is MERGED (`cc1d867`), not open.
