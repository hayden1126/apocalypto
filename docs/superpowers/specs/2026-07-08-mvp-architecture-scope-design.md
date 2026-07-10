# MVP architecture and scope design (the skeleton spec)

Date: 2026-07-08
Status: approved (2026-07-08); shipped with slice-0 on PR #4; amended 2026-07-10 (Android-first build order, see section 2a)
Scope: this is the *skeleton* spec. It fixes the platform and stack, draws module
boundaries across the MVP subsystems, defines the shared data model and transport, and
sets build order. It does NOT design any subsystem's internals. Each subsystem gets its
own brainstorm, spec, plan, and build cycle after this.

## 1. Context

The apocalypto project (an offline apocalypse-navigation app) finished its two-step
positioning validation. The core thesis PASSES on a real ~2 km out-and-back walk: phone
pedestrian dead reckoning (PDR) plus trusted GNSS re-anchoring at a 15 to 20 s cadence
holds street level (held-out radial P95 6.7 m at 15 s), validated on an iPhone 14 Pro.
That result was the blocker gating any commitment to an app stack. It is resolved, so the
MVP is unblocked, and the chosen next step is this architecture and scope design.

The validation code lives in `prototypes/pdr-benchmark/` as a Python (numpy/scipy) research
harness. Nothing there runs on a phone as-is: it is a validated algorithm and parameter
reference, and a numerical oracle to test a native port against. The two heaviest-to-port
pieces (AHRS heading, HMM map-matching) are exactly the two the product brief already says
to replace with native platform APIs and an on-device Viterbi.

The MVP as scoped in the brief (section 03) is roughly eight subsystems. That is far too
much for one spec, so this document draws boundaries for all of them but sequences the
build behind a tight core milestone.

## 2. Decisions locked with the user

- **Stack:** Flutter (Dart) for the app shell and UI, a shared **Rust core** for the
  positioning, trust, and mesh logic, and thin per-platform native capability adapters
  (Kotlin/Swift). Recorded dissent: native Android was the recommendation, because
  cross-platform does not shrink the native radio, sensor, and power work and iOS caps
  several features. The device reality below makes the cross-platform choice pay off. The
  2026-07-10 pivot (section 2a) vindicates the build-order half of this dissent; the
  cross-platform stack choice stands.
- **Positioning core language:** the shared Rust core (not framework-native Dart, not a
  per-platform native port), exposed to Flutter via FFI (flutter_rust_bridge).
- **v1 breadth:** a "core milestone first" cut. The core milestone is slices 0 to 3
  (positioning spine, offline map, trust backbone, BLE hazard mesh). This spec still draws
  boundaries for all subsystems; capture, power, and the LoRa companion are designed-in and
  fast-follow.
- **Build and test platform: Android-first (amended 2026-07-10; originally iOS-first, see
  section 2a).** The developer's daily device is now a Huawei P30 (Android); the 2 km PASS
  device (iPhone 14 Pro) remains the positioning reference, with iOS built periodically on a
  2020 Intel MacBook Air. Building slice 1 on Android puts the full-radio target first, and
  the iPhone re-walk keeps the validated sensor platform in the loop. This remains a
  build-order decision, not an architecture decision: the native trait boundary is unchanged,
  and iOS is the capped-subset tier behind the same ports.

## 2a. Amendment (2026-07-10): Android-first build order

Decision, approved by the user: the MVP build order flips from iOS-first to Android-first.
This amends the build-order decision in section 2 and the touchpoints in sections 3, 9, 12,
and 14. It changes no architecture: the trait boundary, the crate workspace, the FFI lanes,
and the "core never assumes Android capabilities" rule are all unchanged.

Why the premise changed. The section 2 decision rested on "the developer has only an
iPhone". That is no longer true. The developer now has a Huawei P30 (EMUI 12, Android 10,
Google services present, dual-frequency L1+L5 GNSS, a different IMU vendor than the iPhone
14 Pro) as a daily Android device, plus a 2020 Intel MacBook Air that can build and sign iOS
via Xcode 26.3 on macOS Sequoia. The Air is a periodic iOS station, not a primary machine:
macOS Tahoe dropped every Intel MacBook Air, the App Store minimum-SDK requirement passes
the machine around April 2027, Flutter has announced Intel-Mac host deprecation, and
sustained builds thermally throttle. So Android is the daily build-and-test target and iOS
becomes a periodic verify-and-deploy target at Air sessions.

What changes. Android ships first and is the full-radio-capability tier from the start
(section 2 already anticipated this: "Android becomes the full-radio-capability target when
a device is available", and a device is now available). iOS is the capped-subset tier behind
identical traits, built and verified periodically on the Air, viable to about April 2027.
Slice 1 on-device validation names two walks: a P30 walk on the ma-ling routes first, then
an iPhone 14 Pro re-walk built via the Air. The iPhone 14 Pro remains the validated
positioning reference device. The Mac-mini-versus-cloud-CI question from STATUS is closed
for now: the Air covers periodic iOS verification, revisit when iOS work becomes sustained
or the Air ages out.

The recorded dissent in section 2 (native Android was the recommendation) is vindicated on
the build-order half: Android-first was the right first target. The cross-platform stack
half of that decision stands, and now pays off in the other direction: the iOS tier stays
reachable from the same codebase at periodic Air sessions instead of needing a parallel
native build.

Cross-device positioning risk is being retired ahead of slice 1. The P30 is validated
through the existing Python pipeline (`prototypes/pdr-benchmark/`, `PHONE_WALK_PROTOCOL.md`)
on the same ma-ling routes, so sensor semantics and frame conventions are proven before any
Rust port runs on the device.

## 3. Architecture: three tiers

1. **Rust core.** A Cargo workspace of small, pure, deterministic crates that own all data,
   trust, positioning, and mesh logic. No crate below the FFI facade touches the OS or does
   I/O except through injected ports. Everything here is testable off-device against the
   Python prototype as a numerical oracle.
2. **Flutter (Dart).** The shell, state management, UI, and an offline vector-map renderer
   (MapLibre GL Native, via `maplibre_gl`). It talks to Rust only through one generated FFI
   boundary and never parses wire bytes.
3. **Native capability adapters (Kotlin/Swift).** Thin, decision-free translators that
   implement Rust-defined traits for sensors, GNSS, BLE, LoRa, camera, and power. Android
   ships first (the dev device) and is the full-capability tier behind these traits; iOS
   impls are a capped subset of the same ports, verified periodically on the Intel MacBook
   Air (amended 2026-07-10, section 2a).

Two orthogonal layerings discipline the design and must not be conflated:

- **Deployment layering (hexagonal core and adapters):** native adapters implement Rust
  ports, the pure Rust core holds all decisions, the `apoc-ffi` facade is the single
  crossing, and Flutter sits on top.
- **Positioning-ladder layering (L0 to L3 plus a fallback cone):** each ladder rung is a
  strategy that produces a correction to one shared position belief, a fusion policy
  arbitrates them, and "degrade" means drop a rung and widen the cone. This layering lives
  entirely inside one crate (`apoc-positioning`).

## 4. The Rust crate workspace

Names are the deliverable. Dependency direction has no cycles.

| Crate | Tier | Role | Depends on |
|---|---|---|---|
| `apoc-geo` | rust | Leaf. Coordinate frames (NE to lat/lon to UTM), geometry helpers, and the spatial keyspace (`SegmentId`, `VantageId`, tiling). The shared spatial contract. | none |
| `apoc-types` | rust | The data model: `SignedSpatialRecord`, `BulkManifestEntry`, `PositionBelief` and `UncertaintyCone`, `CrdtOp`, `TrustEnvelope`, `ChangeClass`. | geo |
| `apoc-map` | rust | Read-only region-package reader: walking graph, vector-tile accessor, spatial index, manifest. Runtime READ side only. | types, geo |
| `apoc-routing` | rust | Offline route computation over the baked graph. | map, geo |
| `apoc-positioning` | rust | The L0 to L2 ladder plus the fusion-policy seam. Port target for the whole prototype `pdr/`, `trusted_fix`, `reanchor`, and a native Viterbi map-matcher. | types, geo, map |
| `apoc-trust` | rust | The single gate: signature verify, N>=3 corroboration, TTL expiry, spatial CRDT merge. Pure logic, no transport. | types, geo |
| `apoc-mesh` | rust | The <=237 B pointer codec plus gossip / anti-entropy logic. Transport-agnostic, touches no radios. | types, trust |
| `apoc-capture` | rust | F3 change-detection orchestration and F1 dumb-capture / dedup / bulk-manifest bookkeeping. | types, trust, geo |
| `apoc-power` | rust | Duty-cycle policy (a pure state machine) and the dark-map default. | types |
| `apoc-ffi` | rust | The single flutter_rust_bridge boundary. Owns the async runtime, wires the pure crates into a session, and DEFINES the capability ports (traits the native adapters implement). | all |

Dependency direction: `apoc-geo` is the leaf; `apoc-types` depends on it; `apoc-map` and
`apoc-positioning` depend on `types` and `geo`; `apoc-trust`, `apoc-mesh`, and
`apoc-capture` depend on `types` and `trust`; `apoc-ffi` depends on everything and is the
only crate Dart sees.

### 4.1 The FFI boundary (two lanes, do not merge)

- **Sensor lane (native to Rust, direct C-ABI, native thread):** 100 Hz IMU, fused
  orientation, and GNSS fixes are pushed straight into `apoc-positioning` via `apoc-ffi` C
  exports, bypassing Dart. Routing 100 Hz through Dart would marshal-and-GC-jank the very
  timing the PDR pipeline depends on.
- **Control and UI lane (Dart to and from Rust, flutter_rust_bridge):** low-rate belief,
  hazard, and review streams go out; commands come in. frb generates Dart view types; the
  compact wire structs and the byte-budget codec stay entirely in Rust.
- **Mesh payloads (native radio to and from Rust):** native hands Rust opaque received
  bytes and takes back the payload to advertise. Flutter sees only decoded views.

## 5. The shared data model

Single source of truth: `apoc-types`. One type is the backbone.

`SignedSpatialRecord` is what BOTH a hazard report and a capture pointer are, differing
only by a `kind` discriminant and per-kind payload. Envelope fields (identity and trust,
identical across kinds):

- `record_id`: content hash of the canonical body, and the dedup key.
- `kind`: enum `{ Hazard, CapturePointer }` (extensible).
- `spatial_ref`: enum from `apoc-geo`, `Point(lat,lon) | Segment(SegmentId) |
  Vantage(VantageId) | Floating(LocalAnchor)`. Carries the "stored floating, snapped to
  global later" rule structurally.
- `timestamp`, `class` (per-kind: hazard class, or F3 change-class), `confidence`.
- `ttl`: `issued_at + lifetime` (hard expiry; bounds the stale "all-clear" problem).
- `author`: a compact key id (truncated Ed25519 pubkey or key-registry index).
- `signature`: Ed25519 over the canonical body (64 B).

Per-kind pointer body rides the mesh: a hazard carries a coded class or short note; a
capture pointer carries `phash` (8 B), `descriptor_hash`, `thumbnail_hash`, `revisit_index`,
and a `human_confirmed` flag. A `bulk_manifest_hash: Option<Hash>` points to the MB to GB
content (panoramas, 4K video, meshes/submaps, model weights). The wire record never carries
pixels; this hash is the join key the transport router uses to move bulk on physical contact
or at a hub.

Two non-obvious rulings, reached independently by both design passes:

- **Corroboration count is derived locally, never on the wire.** An authored count would be
  forgeable. The wire record is trust-neutral bytes; the validated view the UI sees carries
  a `TrustState` of `{ Unverified, Verified, Corroborated(u8), Expired, Conflicted }`,
  computed by `apoc-trust` from the N distinct-author copies a node has seen.
- **The spatial keyspace is a hidden second backbone.** `apoc-positioning` (map-match node
  ids), `apoc-map` (segment / vantage ids), and `apoc-trust` (CRDT merge keys and
  corroboration buckets) all need stable spatial keys. If `apoc-map` alone owned them, the
  keys would drift across map-package versions and corroboration would silently fail to
  cluster two reports of the same collapsed corner (counting them as two places, never
  reaching N>=3). So `apoc-geo` is the sole owner of `SegmentId`, `VantageId`, tiling, and
  the coordinate transforms.

**Codec:** a deterministic canonical encoding with a hand-rolled bit budget (not
bincode/protobuf; every byte counts). A hard `MAX_MESH_FRAME` const is co-defined with the
tightest transport (see risk 1) and the codec is frozen only after that byte-budget check.

**Crossing the FFI:** `apoc-ffi` exposes flat, owned DTOs (`RecordView`, `PositionBelief`,
`HazardView`, `CaptureReview`) with no lifetimes or crypto types, plus stream sinks for live
updates. Flutter receives validated projections only.

## 6. The trust gate as one shared policy

Module: `apoc-trust`. One store, a small public surface (`validate`, `merge`,
`corroboration`, `visible_hazards`, `sign`), four stages in order:

1. **Signature verify** (Ed25519 against `author`; reject on fail).
2. **TTL expiry** (drop or flag past `issued_at + lifetime`; enforced on read too, so a
   stale all-clear cannot linger).
3. **Corroboration accounting** (count distinct authors on the same spatial / class / epoch
   bucket; reach `Corroborated` at N>=3). This is corroboration, not attack-proofing: no
   serverless mesh is Sybil-proof, and the brief markets it honestly as such.
4. **Spatial-CRDT merge** (delta-state CRDT keyed on `spatial_ref`; concurrent edits to the
   same place merge deterministically; output `admitted | duplicate | conflicted`).

The integrating invariant: nothing writes to the record store except through
`apoc-trust::merge`, and every ingress path calls `apoc-trust::validate` first. The hazard
layer, the capture layer, and the transport receive path all depend on `apoc-trust` and none
can admit a record on its own. That single choke point is why "one record type plus one
gate" is the backbone: hazard and capture are two `kind` values flowing through the identical
policy.

## 7. Positioning: the ladder and the fusion seam

`apoc-positioning` holds sibling modules mirroring the ladder rungs, ported from the
prototype:

- `pdr` (L1 backbone): step detection, Weinberg step length and k calibration, dead
  reckoning, start-pose alignment. Heading is injected, not computed here (see risk 2).
- `gnss_gate` (L0): `trusted_fix_mask` (the causal max-walking-speed outlier gate, the
  stationary dispersion lock-detector for cold-start trim, a loose reported-accuracy
  backstop, and an opt-in IMU-vs-GNSS innovation gate). The most directly translatable novel
  code; port and oracle it first.
- `mapmatch` (L2): a native HMM/Viterbi matcher with an explicit off-graph state, plus
  matched-edge bearings. Replaces the prototype's `leuvenmapmatching`.
- `reanchor`: BOTH `reanchored_track` (GNSS-primary, proven) and `map_reanchored_track`
  (map-heading, the failed B1). Port both, wire only the first.
- `belief`: the `PositionBelief` and cone integrator (the cone widens with time since the
  last trusted fix and collapses on one).
- `fusion`: the `FusionPolicy` trait and cadence policy, the arbitration seam.

**The spine tension, resolved.** The contested product decision (GNSS-primary versus
map-primary) collapses to one swappable `FusionPolicy` object over the same rungs:

- Default `SpineUnInverted`: L1 PDR backbone, L0 trusted GNSS re-anchor at 15 to 20 s as the
  primary position and heading corrector, L2 map-matching as a secondary which-street
  candidate the policy may apply but never depends on. This is the ONLY demonstrated-PASS
  configuration and ships as the MVP default.
- `SpineInverted` (map-as-heading, GNSS demoted to an along-track hint): designed-in but
  feature-gated OFF. It FAILED on both real walks, because single-pass matching snaps a
  ~25%-drifted PDR track to the wrong edges. It is a research bet, not on the critical path.
  Because the prototype already ships both `reanchored_track` and `map_reanchored_track`, the
  seam is pre-prototyped: port both, wire one.

## 8. Transport

`apoc-mesh` owns the pointer-lane codec and the gossip / anti-entropy decisions for the
<=237 B lane; it touches no radios and does not own the bulk lane. Bulk transport execution
(SoftAP plus mDNS plus HTTPS, LocalSend-style; USB-C; AirDrop / Quick Share) lives in a
**Dart/native** package driven by a `BulkManifest`. Forcing an HTTP server and file I/O into
the pure Rust core would poison the "no I/O below `apoc-ffi`" invariant, and LocalSend itself
is Dart, so this split is deliberate.

Routing is keyed on the pointer-vs-bulk split in the record. If there is no bulk manifest and
the encoded record fits `MAX_MESH_FRAME`, it takes the mesh path (choose among BLE and LoRa
by reach and power cost, duty-cycle-aware). If there is a bulk manifest, it takes the bulk
path (prefer SoftAP, then USB-C, then AirDrop / Quick Share), and if the two peers are
cross-OS it returns "requires physical contact": the iOS-to-Android bulk wall is modeled
explicitly, and only the pixels are walled, the tiny pointer still crosses the mesh.

## 9. Native capability adapters

Each implements an `apoc-ffi` port and makes zero decisions: `SensorSource` (accel, gyro,
gravity, plus fused orientation), `GnssSource`, `RadioLink` (BLE, LoRa), `CameraSource`,
`PowerControl`. Android ships first as the dev device and the full-capability tier; the iOS
caps (`CLLocation`-only GNSS, no BLE extended-advertising mesh, weaker power control, the
iOS-to-Android bulk wall) are the degraded impls behind identical traits, exercised at
periodic Air sessions (amended 2026-07-10, section 2a). The core must never assume Android
capabilities.

## 10. Build-time region-package pipeline (off-phone)

A desktop/CI `region-baker` takes an OSM extract plus a region bounding box and emits one
versioned region package: vector tiles (pmtiles/mbtiles) for the renderer, a baked
pedestrian/routing graph plus spatial index for `apoc-map`, and a manifest (region id,
version, bbox, CRS, checksums). This is where osmnx `graph_from_bbox` and projection live
(porting the prototype `mapmatch/graph.py`), and it may stay Python. Only the serialization
format is a stable contract that Rust `apoc-map` reads.

## 11. Flutter layer

Packages under `app/`: `app` (shell, lifecycle, DI, native-adapter startup), `state` (view
models subscribing to frb streams; pick Riverpod or Bloc), `ui` (map screen, the uncertainty-
cone overlay, hazard layer, F3 blink/slider review, companion pairing, power HUD),
`map_renderer` (MapLibre GL Native rendering the region package's offline vector tiles, with
cone/route/hazards/captures as overlay layers), and `bridge` (generated frb bindings).

## 12. Build order (thin vertical slices, Android-first; amended 2026-07-10)

Ordering is justified by dependency (types and geo, then positioning, then belief, then
hazards need belief, then capture needs trust and mesh, then power duty-cycles the rest) and
by retiring the make-or-break port and spine on the real platform before anything else.

- **Slice 0, foundations.** Cargo workspace, `apoc-geo` and `apoc-types` skeletons, the
  region-package format plus the first baked package for the walk area, the numerical-oracle
  harness (run the Python prototype on `ma_ling_2km` and `ma_ling_walk`, dump intermediate
  and final arrays, assert the Rust port matches within tolerance), and a Flutter app
  rendering a dark vector map. De-risks the toolchain and the data contract before any logic.
- **Slice 1, the proven positioning spine end-to-end on Android (the first real slice).** Port
  `pdr`, `gnss_gate`, `reanchor` (GNSS-primary), the native Viterbi `mapmatch`,
  `fusion::SpineUnInverted`, and `belief` into `apoc-positioning`; wire `apoc-map` and
  `apoc-routing`; expose the belief stream via `apoc-ffi`; feed it from Android sensor and
  location adapters (the mag-free heading path per risk 2: `GAME_ROTATION_VECTOR` or raw
  gyro); render the moving cone. Validate against the oracle, a P30 walk on the ma-ling
  routes, and a later iPhone 14 Pro re-walk built via the Air. Retires port correctness and
  the primary target platform at once; the iPhone re-walk keeps continuity with the platform
  the PASS was validated on.
- **Slice 2, the data backbone.** Complete `apoc-types` (final layout, codec) and
  `apoc-trust` (verify, TTL, corroboration, CRDT merge, store), exercised over an in-process
  fake transport with no radios. The record layout is frozen here, so the risk-1 byte-budget
  check must land first.
- **Slice 3, the BLE hazard vertical.** `apoc-mesh` plus a native BLE adapter. The
  correctness-critical mesh codec, gossip, and trust logic are all in Rust and tested
  off-device. On Android the adapter targets the full 237 B extended-advertising form (verify
  the P30 chipset supports it at slice start; fall back to legacy advertising if absent). The
  degraded iOS form (GATT or legacy advertising, foreground-limited) is built at an Air
  session for cross-OS end-to-end validation. Records flow device-to-device, through the gate,
  onto the map with trust badges.

**Fast-follow (boundaries drawn here, built after the core milestone):** slice 4, the capture
vertical (F3 plus F1-dumb plus the SoftAP/USB bulk path, proving a capture pointer is the same
gated record as a hazard); slice 5, power and duty-cycle plus the dark-map default; slice 6,
the LoRa companion (an additive transport backend). The iOS capped tier and iOS hardening run
as a periodic parallel track at Air sessions once the ports stabilize; Android full-radio
refinements continue on the dev device.

## 13. Load-bearing risks

These can invalidate the design if ignored.

1. **The mesh frame budget versus the signed envelope.** A 64 B Ed25519 signature is about
   27% of a 237 B BLE extended-advertising frame; the iOS legacy-advertising payload (about
   31 B) and LoRa frames are smaller still. Add author id, `record_id`, `spatial_ref`,
   timestamp, class, confidence, TTL, and a capture pointer's hashes, and it is not obvious
   the whole signed record fits one frame. If it does not, you inherit fragmentation and
   reassembly over a connectionless, unreliable, adversarial broadcast medium, reopening the
   Sybil and poisoning surface the trust gate is meant to close. Rule: freeze `MAX_MESH_FRAME`
   against the tightest backend FIRST, then design the codec to fit, before slice 2 freezes
   the record layout. Candidate resolutions: aggregate or truncated signatures, carrying
   corroboration as separate attestation frames, or demoting descriptors to bulk.
2. **The heading source quietly reintroduces the magnetometer.** Native fused orientation
   (Android `ROTATION_VECTOR`, iOS CoreMotion attitude) fuses the magnetometer back in, the
   exact signal the project killed across three experiments in disturbed fields, and every
   drift and cadence threshold was tuned on gyro-only heading. So the shipped heading would be
   a different signal than the validated one. Mitigation: make heading a swappable port with
   two impls, default to the mag-free path (gyro-integrated with static-bias removal, matching
   the prototype; Android `GAME_ROTATION_VECTOR`, iOS `CMGyroData`), and make the oracle
   contract feed recorded orientation into both the prototype and the Rust port so the gate,
   re-anchor, and map-match stay validated independent of heading source.
3. **Two-reader map-package drift.** The Rust core reads the graph for map-matching; MapLibre
   reads the tiles for display. If the two drift, the user sees a street the matcher does not
   have, and matching correctness silently degrades. Mitigation: one `region-baker`, one
   versioned manifest, both readers assert the same `PackageVersion`, and graph and tiles are
   derived from the same source in one pass.

Standing rules that guard the design: keep the 100 Hz sensor lane native-to-Rust C-ABI,
bypassing Dart; and keep every GNSS-primary assumption inside `fusion::SpineUnInverted` (the
cadence, the cone-collapse-on-fix, the "GNSS is the trusted anchor") so the estimators,
power, and UI stay policy-agnostic and the inversion stays a contained swap. Guard the latter
with a test that runs both policies over the same recorded rungs.

## 14. MVP-critical versus deferred seams

**MVP-critical (the core milestone, slices 0 to 3):** `apoc-geo`, `apoc-types`, `apoc-map`
(read), `apoc-routing`, `apoc-positioning` (pdr plus gnss_gate plus mapmatch-as-secondary
plus reanchor-GNSS-primary plus `SpineUnInverted` plus belief/cone), `apoc-trust`,
`apoc-mesh`, `apoc-ffi`, the Flutter app/state/ui/map_renderer/bridge, the Android
sensor/gnss/ble/power adapters, and the `region-baker`. Capture (F3 and F1-dumb) has its
boundaries drawn here and is built in the fast-follow.

**Designed-in but deferred or feature-gated off:** `SpineInverted` (map-heading, failed,
gated), the map-conflict monitor (B2), adaptive trust-driven cadence (B3), pose robustness
(B4), L3 vision-plus-peer re-anchor, F1 reconstruction (a future consumer of the bulk store,
gated behind the `bulk_manifest_hash` field), the iOS capped adapter tier (periodic verify
and deploy via the Intel MacBook Air, viable to about April 2027), and the LoRa companion
node.

## 15. Non-goals

Explicitly out of scope for the MVP, per the brief's "drop from v1" and the research
dead-ends: CV auto-recognition of streets as a positioning oracle; any cloud or VPS; UWB and
Wi-Fi RTT; sub-meter RTK/PPP; magnetic or radio fingerprinting for position; the magnetometer
as an offline heading source; and any "Sybil-proof" or "spoof-proof" claim (keep the
mitigations, drop the promise).

## 16. Open questions to resolve during implementation

- The exact resolution of risk 1 (the frame budget), decided before slice 2 freezes the
  record layout.
- Flutter state-management choice (Riverpod versus Bloc), decidable at slice 0.
- Where the F3 feature matching runs (Rust `imageproc`/`opencv` versus native delegation),
  decidable at the capture slice.

## 17. References

- Prototype (algorithm and parameter reference, numerical oracle):
  `prototypes/pdr-benchmark/pdr_bench/pdr/trusted_fix.py` (L0 gate, port first),
  `.../pdr/reanchor.py` (both spine and inversion; the fusion seam is here),
  `.../pdr/pipeline.py` (L0 to L2 wiring order; heading-injection point),
  `.../mapmatch/match.py` (L2 matcher to reimplement as a native Viterbi),
  `.../mapmatch/graph.py` (osmnx build-time step, belongs in `region-baker`).
- Product scope and findings: `docs/brief.html` (section 02 positioning stack, section 03
  MVP, section 04 capture layer and data model), `PLAN.md`, `STATUS.md`.
