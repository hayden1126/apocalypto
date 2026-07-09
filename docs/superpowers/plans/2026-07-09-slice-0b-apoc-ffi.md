# Slice 0b Group A: `apoc-ffi` C-ABI Crossing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up `core/apoc-ffi`, the single FFI crossing of the MVP architecture (spec section 4.1), exposing the two existing core calls (`apoc_geo::interp_ne`, `apoc_positioning::gnss_gate::trusted_fix_mask`) over the direct C-ABI sensor lane, with Rust tests proving the round-trip and an exported-symbol check. Close the two slice-0 follow-ups that a shipping binary artifact triggers: `#![forbid(unsafe_code)]` in the pure crates and a committed `core/Cargo.lock`.

**Architecture:** Two layers inside one crate. `dto` holds flat owned DTOs and safe wiring: no raw pointers, no lifetimes, no crypto types, `#![forbid(unsafe_code)]` at module level. It validates shapes (the core `interp_ne` panics on an empty source track, so the edge must reject it), converts flat row-major buffers to the core's `[[f64; 2]]` form, and maps `acc_backstop_m` NaN to `None` (an `Option` cannot cross the C ABI). `capi` holds the `extern "C"` exports: `#[repr(C)]` owned buffers, a `#[repr(C)]` params mirror, and four `#[no_mangle]` functions, each wrapped in `catch_unwind` (a panic unwinding across `extern "C"` must never escape). All `unsafe` in the crate is confined to `capi` under `#![deny(unsafe_op_in_unsafe_fn)]` with a `// SAFETY:` comment per block. The crate builds as `["rlib", "cdylib", "staticlib"]`: rlib for the Rust tests, cdylib for the symbol check and any dynamic host, staticlib for the eventual iOS link. flutter_rust_bridge (the low-rate control/UI lane) is deferred: no Dart toolchain exists on this box, and the two lanes are separate by design.

**Tech Stack:** Rust (stable, edition 2021), Cargo workspace at `core/`. No new dependencies: the crate depends only on `apoc-geo` and `apoc-positioning`. `nm` (binutils) for the exported-symbol check; `cc` for an optional C harness in scratchpad.

## Global Constraints

- `export PATH="$HOME/.cargo/bin:$PATH"` before any cargo command (cargo is off the default shell PATH on this box).
- The C error convention is uniform: `0` OK, `1` invalid arguments, `2` panic caught. On any non-zero return the out-buffer is zeroed and there is nothing to free.
- Owned buffers cross the boundary as `(ptr, len)` from `Vec::into_boxed_slice` (so `len == cap` and the free side can reconstruct the `Box<[T]>` exactly). `ptr` is null iff `len == 0`. Frees are null-safe and re-zero the struct so an accidental double free is inert.
- Nullable inputs follow one rule: a null data pointer is valid only for a stated length of 0 (required inputs) or means "absent" (optional inputs: `reported_acc_m`, the PDR pair, `params`).
- The DTO wiring validates shape only. `t_src` strictly increasing stays the caller's contract, exactly as in the core call; the edge does not invent semantics the core does not have.
- Ported semantics stay byte-identical: the wiring calls the existing core functions and never reimplements them.
- `cargo clippy --workspace --all-targets -- -D warnings` must stay clean (the one deliberate allow: `clippy::too_many_arguments` on `apoc_trusted_fix_mask`, which is a flat C edge by design).
- Commit after every task (conventional commits). Do not push; the human pushes explicitly.

### Out of scope for this plan (later increments)

The flutter_rust_bridge lane and its Dart round-trip (needs a Flutter project and the Dart SDK), the 100 Hz native-thread adapters, any streaming/session API (this crossing is batch-call over slices), cbindgen header generation, and the iOS staticlib link (needs macOS). Group B (`region-baker`) is a separate plan and a separate PR.

---

### Task 1: Workspace member + flat DTO layer (`dto.rs`)

Creates the `apoc-ffi` crate, wires it into the workspace, and builds the safe DTO layer with its wiring tests. Deliverable: `cargo test -p apoc-ffi` passes 2 DTO-wiring tests; `cargo build -p apoc-ffi` emits `libapoc_ffi.so` and `libapoc_ffi.a`.

**Files:**
- Modify: `core/Cargo.toml` (add `apoc-ffi` to members)
- Create: `core/apoc-ffi/Cargo.toml`
- Create: `core/apoc-ffi/src/lib.rs`
- Create: `core/apoc-ffi/src/dto.rs`
- Create: `core/apoc-ffi/src/capi.rs` (empty-module stub; Task 2 fills it)
- Test: `core/apoc-ffi/tests/dto_wiring.rs`

**Interfaces:**
- Produces:
  - `apoc_ffi::dto::InterpNeView { pub ne: Vec<f64> }` (row-major `[n0, e0, n1, e1, ...]`)
  - `apoc_ffi::dto::TrustedFixView { pub keep: Vec<bool> }`
  - `apoc_ffi::dto::TrustedFixParamsDto` (flat mirror of `TrustedFixParams`; `acc_backstop_m: f64` with NaN meaning no backstop; `Default` carries the core defaults)
  - `apoc_ffi::dto::interp_ne_view(t_src: &[f64], ne_src_flat: &[f64], t_query: &[f64]) -> Option<InterpNeView>`
  - `apoc_ffi::dto::trusted_fix_view(gnss_t: &[f64], gnss_ne_flat: &[f64], reported_acc_m: Option<&[f64]>, pdr_t: Option<&[f64]>, pdr_ne_flat: Option<&[f64]>, params: &TrustedFixParamsDto) -> Option<TrustedFixView>`
- Consumes: `apoc_geo::interp_ne`, `apoc_positioning::gnss_gate::{trusted_fix_mask, TrustedFixParams}`.

- [ ] **Step 1: Create the crate scaffolding**

Set `core/Cargo.toml`:

```toml
[workspace]
resolver = "2"
members = ["apoc-geo", "apoc-positioning", "apoc-ffi"]
```

`core/apoc-ffi/Cargo.toml`:

```toml
[package]
name = "apoc-ffi"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["rlib", "cdylib", "staticlib"]

[dependencies]
apoc-geo = { path = "../apoc-geo" }
apoc-positioning = { path = "../apoc-positioning" }
```

`core/apoc-ffi/src/lib.rs`:

```rust
//! The single FFI crossing for the apocalypto core (spec section 4.1).
//! Two lanes by design, never merged: the low-rate control/UI lane
//! (flutter_rust_bridge, deferred until a Dart toolchain exists) and the
//! 100 Hz sensor lane (`capi`, a direct C ABI that bypasses Dart).
//! Everything crossing here is flat owned data: no lifetimes, no crypto types.
#![deny(unsafe_op_in_unsafe_fn)]

pub mod capi;
pub mod dto;
```

`core/apoc-ffi/src/capi.rs` (stub; Task 2 fills it):

```rust
//! The 100 Hz sensor lane: a direct C ABI over the `dto` wiring.
```

- [ ] **Step 2: Write the failing DTO-wiring tests**

`core/apoc-ffi/tests/dto_wiring.rs`:

```rust
use apoc_ffi::dto::{interp_ne_view, trusted_fix_view, TrustedFixParamsDto};

#[test]
fn interp_ne_view_matches_core_and_validates_shape() {
    let t_src = [0.0, 1.0, 2.0];
    let ne_src_flat = [0.0, 0.0, 1.0, 2.0, 4.0, 1.0];
    let t_query = [-1.0, 0.5, 2.0, 9.0];
    let view = interp_ne_view(&t_src, &ne_src_flat, &t_query).unwrap();
    // clamped at both ends; interior exactly linear
    assert_eq!(view.ne, vec![0.0, 0.0, 0.5, 1.0, 4.0, 1.0, 4.0, 1.0]);
    // parity with the core call, row-major flattened
    let core = apoc_geo::interp_ne(&t_src, &[[0.0, 0.0], [1.0, 2.0], [4.0, 1.0]], &t_query);
    let flat: Vec<f64> = core.into_iter().flatten().collect();
    assert_eq!(view.ne, flat);
    // shape violations return None instead of panicking
    assert!(interp_ne_view(&[], &[], &t_query).is_none()); // empty t_src: the core call panics on this
    assert!(interp_ne_view(&t_src, &ne_src_flat[..4], &t_query).is_none()); // ne/t length mismatch
}

#[test]
fn trusted_fix_view_maps_nan_backstop_and_validates() {
    // 10 fixes north at 1 m/s, an 800 m teleport at index 5, absurd reported acc at 3.
    let gnss_t: Vec<f64> = (0..10).map(|i| i as f64).collect();
    let mut ne_flat = Vec::new();
    for i in 0..10 {
        ne_flat.extend_from_slice(&[i as f64, 0.0]);
    }
    ne_flat[10] = 800.0; // north component of fix 5
    let mut acc = vec![14.0; 10];
    acc[3] = 807.0;

    // NaN backstop must behave as "no backstop": index 3 survives, the teleport falls.
    let mut p = TrustedFixParamsDto {
        acc_backstop_m: f64::NAN,
        lock_disp_m: 1e9,
        ..Default::default()
    };
    let view = trusted_fix_view(&gnss_t, &ne_flat, Some(&acc), None, None, &p).unwrap();
    let expect: Vec<bool> = (0..10).map(|i| i != 5).collect();
    assert_eq!(view.keep, expect);

    // a finite backstop rejects index 3 as well; parity with the core call
    p.acc_backstop_m = 50.0;
    let view = trusted_fix_view(&gnss_t, &ne_flat, Some(&acc), None, None, &p).unwrap();
    let gnss_pairs: Vec<[f64; 2]> = ne_flat.chunks_exact(2).map(|c| [c[0], c[1]]).collect();
    let core = apoc_positioning::gnss_gate::trusted_fix_mask(
        &gnss_t,
        &gnss_pairs,
        Some(&acc),
        None,
        &apoc_positioning::gnss_gate::TrustedFixParams {
            lock_disp_m: 1e9,
            ..Default::default()
        },
    );
    assert_eq!(view.keep, core);
    assert!(!view.keep[3] && !view.keep[5]);

    // wrong-length acc and a half-present PDR pair are rejected
    assert!(trusted_fix_view(&gnss_t, &ne_flat, Some(&acc[..5]), None, None, &p).is_none());
    assert!(trusted_fix_view(&gnss_t, &ne_flat, None, Some(&gnss_t), None, &p).is_none());
    // empty GNSS is a valid degenerate input: empty mask, as in the core call
    let empty = trusted_fix_view(&[], &[], None, None, None, &p).unwrap();
    assert!(empty.keep.is_empty());
}
```

- [ ] **Step 3: Run to verify the tests fail**

Run: `export PATH="$HOME/.cargo/bin:$PATH"; cd core && cargo test -p apoc-ffi`
Expected: FAIL to compile with `unresolved import` / `cannot find function` for the `dto` items (the module does not exist yet).

- [ ] **Step 4: Implement `dto.rs`**

`core/apoc-ffi/src/dto.rs`:

```rust
//! Flat owned DTOs and safe wiring over the core calls (the "flat owned data,
//! no lifetimes, no crypto" rule from spec section 4.1). No raw pointers in this
//! module; the C-ABI edge lives in `capi`.
#![forbid(unsafe_code)]

use apoc_positioning::gnss_gate::{trusted_fix_mask, TrustedFixParams};

/// Interpolated NE track, row-major `[n0, e0, n1, e1, ...]`.
#[derive(Clone, Debug, PartialEq)]
pub struct InterpNeView {
    pub ne: Vec<f64>,
}

/// Keep-mask over the input GNSS fixes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TrustedFixView {
    pub keep: Vec<bool>,
}

/// Flat mirror of [`TrustedFixParams`]: `acc_backstop_m` is NaN for "no backstop"
/// (an `Option` cannot cross the C ABI). `Default` carries the core defaults.
#[derive(Clone, Copy, Debug)]
pub struct TrustedFixParamsDto {
    pub max_speed_mps: f64,
    pub lock_window: usize,
    pub lock_disp_m: f64,
    pub max_gap_s: f64,
    pub max_cold_s: f64,
    pub acc_backstop_m: f64,
    pub use_innovation: bool,
    pub innovation_sigma: f64,
    pub innovation_floor_m: f64,
    pub min_fixes: usize,
}

impl Default for TrustedFixParamsDto {
    fn default() -> Self {
        Self::from(&TrustedFixParams::default())
    }
}

impl From<&TrustedFixParams> for TrustedFixParamsDto {
    fn from(p: &TrustedFixParams) -> Self {
        Self {
            max_speed_mps: p.max_speed_mps,
            lock_window: p.lock_window,
            lock_disp_m: p.lock_disp_m,
            max_gap_s: p.max_gap_s,
            max_cold_s: p.max_cold_s,
            acc_backstop_m: p.acc_backstop_m.unwrap_or(f64::NAN),
            use_innovation: p.use_innovation,
            innovation_sigma: p.innovation_sigma,
            innovation_floor_m: p.innovation_floor_m,
            min_fixes: p.min_fixes,
        }
    }
}

impl TrustedFixParamsDto {
    fn to_params(self) -> TrustedFixParams {
        TrustedFixParams {
            max_speed_mps: self.max_speed_mps,
            lock_window: self.lock_window,
            lock_disp_m: self.lock_disp_m,
            max_gap_s: self.max_gap_s,
            max_cold_s: self.max_cold_s,
            acc_backstop_m: (!self.acc_backstop_m.is_nan()).then_some(self.acc_backstop_m),
            use_innovation: self.use_innovation,
            innovation_sigma: self.innovation_sigma,
            innovation_floor_m: self.innovation_floor_m,
            min_fixes: self.min_fixes,
        }
    }
}

fn pairs(flat: &[f64]) -> Vec<[f64; 2]> {
    flat.chunks_exact(2).map(|c| [c[0], c[1]]).collect()
}

/// Safe wiring over [`apoc_geo::interp_ne`] on flat row-major buffers.
/// Returns `None` on a shape violation: empty `t_src` (the core call panics on it)
/// or `ne_src_flat.len() != 2 * t_src.len()`. `t_src` strictly increasing remains
/// the caller's contract, exactly as in the core call.
pub fn interp_ne_view(t_src: &[f64], ne_src_flat: &[f64], t_query: &[f64]) -> Option<InterpNeView> {
    if t_src.is_empty() || ne_src_flat.len() != 2 * t_src.len() {
        return None;
    }
    let ne_src = pairs(ne_src_flat);
    let ne = apoc_geo::interp_ne(t_src, &ne_src, t_query)
        .into_iter()
        .flatten()
        .collect();
    Some(InterpNeView { ne })
}

/// Safe wiring over [`trusted_fix_mask`] on flat buffers. Optional inputs follow one
/// rule: present means non-empty and shape-consistent. Returns `None` when
/// `gnss_ne_flat.len() != 2 * gnss_t.len()`, `reported_acc_m` is present with a length
/// other than `gnss_t.len()`, or the PDR pair is half-present, empty, or inconsistent.
/// An empty GNSS track is valid and yields an empty mask, as in the core call.
pub fn trusted_fix_view(
    gnss_t: &[f64],
    gnss_ne_flat: &[f64],
    reported_acc_m: Option<&[f64]>,
    pdr_t: Option<&[f64]>,
    pdr_ne_flat: Option<&[f64]>,
    params: &TrustedFixParamsDto,
) -> Option<TrustedFixView> {
    if gnss_ne_flat.len() != 2 * gnss_t.len() {
        return None;
    }
    if let Some(acc) = reported_acc_m {
        if acc.len() != gnss_t.len() {
            return None;
        }
    }
    let pdr_pairs = match (pdr_t, pdr_ne_flat) {
        (None, None) => None,
        (Some(t), Some(ne_flat)) if !t.is_empty() && ne_flat.len() == 2 * t.len() => {
            Some((t, pairs(ne_flat)))
        }
        _ => return None,
    };
    let gnss_ne = pairs(gnss_ne_flat);
    let keep = trusted_fix_mask(
        gnss_t,
        &gnss_ne,
        reported_acc_m,
        pdr_pairs.as_ref().map(|(t, ne)| (*t, ne.as_slice())),
        &params.to_params(),
    );
    Some(TrustedFixView { keep })
}
```

- [ ] **Step 5: Run to verify the tests pass**

Run: `cd core && cargo test -p apoc-ffi`
Expected: PASS, 2 tests (`interp_ne_view_matches_core_and_validates_shape`, `trusted_fix_view_maps_nan_backstop_and_validates`).

- [ ] **Step 6: Verify the binary artifacts build**

Run: `cd core && cargo build -p apoc-ffi && ls target/debug/libapoc_ffi.so target/debug/libapoc_ffi.a`
Expected: both files listed.

- [ ] **Step 7: Commit**

```bash
git add core/Cargo.toml core/apoc-ffi
git commit -m "feat(ffi): apoc-ffi crate with flat DTO wiring over the core calls"
```

---

### Task 2: The C-ABI sensor lane (`capi.rs`) + round-trip and symbol proof

Fills `capi.rs` with the `#[repr(C)]` types and the four exports, each panic-guarded. Proves the ABI three ways: an in-process Rust integration test that calls the exported functions with raw pointers and frees the returned buffers; an `nm -D` check that exactly the four `apoc_` symbols export from the cdylib; and an optional C harness compiled with `cc` in scratchpad that links the cdylib and frees a Rust-owned buffer (the strongest Dart-less proof; not committed). Deliverable: `cargo test -p apoc-ffi` passes 6 tests; the symbol check shows 4 symbols.

**Files:**
- Modify: `core/apoc-ffi/src/capi.rs`
- Test: `core/apoc-ffi/tests/capi_roundtrip.rs`

**Interfaces:**
- Produces (all `#[repr(C)]` / `#[no_mangle] extern "C"`):
  - `ApocF64Buffer { ptr: *mut f64, len: usize }`, `ApocU8Buffer { ptr: *mut u8, len: usize }` (Rust-owned; `ptr` null iff `len == 0`)
  - `ApocTrustedFixParams` (flat `#[repr(C)]` mirror; `use_innovation: u8` 0/1; `acc_backstop_m` NaN means no backstop)
  - `apoc_interp_ne(t_src, t_src_len, ne_src, t_query, t_query_len, out: *mut ApocF64Buffer) -> i32`
  - `apoc_f64_buffer_free(buf: *mut ApocF64Buffer)`
  - `apoc_trusted_fix_mask(gnss_t, gnss_len, gnss_ne, reported_acc_m, pdr_t, pdr_len, pdr_ne, params: *const ApocTrustedFixParams, out: *mut ApocU8Buffer) -> i32`
  - `apoc_u8_buffer_free(buf: *mut ApocU8Buffer)`
  - Error codes `APOC_OK = 0`, `APOC_ERR_INVALID_ARGS = 1`, `APOC_ERR_PANIC = 2`
- Consumes: `apoc_ffi::dto` (Task 1).

- [ ] **Step 1: Write the failing C-ABI tests**

`core/apoc-ffi/tests/capi_roundtrip.rs`:

```rust
use apoc_ffi::capi::{
    apoc_f64_buffer_free, apoc_interp_ne, apoc_trusted_fix_mask, apoc_u8_buffer_free,
    ApocF64Buffer, ApocTrustedFixParams, ApocU8Buffer, APOC_ERR_INVALID_ARGS, APOC_OK,
};
use apoc_ffi::dto::TrustedFixParamsDto;

fn zeroed_f64() -> ApocF64Buffer {
    ApocF64Buffer { ptr: std::ptr::null_mut(), len: 0 }
}

fn zeroed_u8() -> ApocU8Buffer {
    ApocU8Buffer { ptr: std::ptr::null_mut(), len: 0 }
}

#[test]
fn interp_ne_roundtrip_owns_and_frees() {
    let t_src = [0.0, 1.0, 2.0];
    let ne_src = [0.0, 0.0, 1.0, 2.0, 4.0, 1.0]; // row-major (n, e)
    let t_query = [-1.0, 0.5, 2.0, 9.0];
    let mut out = zeroed_f64();
    let rc = unsafe {
        apoc_interp_ne(
            t_src.as_ptr(),
            t_src.len(),
            ne_src.as_ptr(),
            t_query.as_ptr(),
            t_query.len(),
            &mut out,
        )
    };
    assert_eq!(rc, APOC_OK);
    assert_eq!(out.len, 8);
    let got = unsafe { std::slice::from_raw_parts(out.ptr, out.len) }.to_vec();
    assert_eq!(got, vec![0.0, 0.0, 0.5, 1.0, 4.0, 1.0, 4.0, 1.0]);
    unsafe { apoc_f64_buffer_free(&mut out) };
    assert!(out.ptr.is_null());
    assert_eq!(out.len, 0);
    // the free re-zeroes the struct, so an accidental double free is inert
    unsafe { apoc_f64_buffer_free(&mut out) };
}

#[test]
fn trusted_fix_mask_roundtrip_null_params_and_nan_backstop() {
    // 10 fixes north at 1 m/s with an 800 m teleport at index 5.
    let gnss_t: Vec<f64> = (0..10).map(|i| i as f64).collect();
    let mut gnss_ne = Vec::new();
    for i in 0..10 {
        gnss_ne.extend_from_slice(&[i as f64, 0.0]);
    }
    gnss_ne[10] = 800.0;
    let mut acc = vec![14.0; 10];
    acc[3] = 807.0;

    // params = null means core defaults (backstop 50): rejects both 3 and 5.
    let mut out = zeroed_u8();
    let rc = unsafe {
        apoc_trusted_fix_mask(
            gnss_t.as_ptr(),
            gnss_t.len(),
            gnss_ne.as_ptr(),
            acc.as_ptr(),
            std::ptr::null(),
            0,
            std::ptr::null(),
            std::ptr::null(),
            &mut out,
        )
    };
    assert_eq!(rc, APOC_OK);
    assert_eq!(out.len, 10);
    let got = unsafe { std::slice::from_raw_parts(out.ptr, out.len) }.to_vec();
    let expect: Vec<u8> = (0..10).map(|i| u8::from(i != 3 && i != 5)).collect();
    assert_eq!(got, expect);
    unsafe { apoc_u8_buffer_free(&mut out) };
    assert!(out.ptr.is_null());

    // explicit params with a NaN backstop: "no backstop", so index 3 survives.
    let params = ApocTrustedFixParams::from(TrustedFixParamsDto {
        acc_backstop_m: f64::NAN,
        ..Default::default()
    });
    let mut out = zeroed_u8();
    let rc = unsafe {
        apoc_trusted_fix_mask(
            gnss_t.as_ptr(),
            gnss_t.len(),
            gnss_ne.as_ptr(),
            acc.as_ptr(),
            std::ptr::null(),
            0,
            std::ptr::null(),
            &params,
            &mut out,
        )
    };
    assert_eq!(rc, APOC_OK);
    let got = unsafe { std::slice::from_raw_parts(out.ptr, out.len) }.to_vec();
    let expect: Vec<u8> = (0..10).map(|i| u8::from(i != 5)).collect();
    assert_eq!(got, expect);
    unsafe { apoc_u8_buffer_free(&mut out) };
}

#[test]
fn invalid_args_error_and_zero_the_out_buffer() {
    let t = [0.0, 1.0];
    let ne = [0.0, 0.0, 1.0, 0.0];

    // empty t_src is rejected at the edge (the core call would panic on it);
    // the out-buffer starts poisoned to prove the edge zeroes it on error
    let mut out = ApocF64Buffer {
        ptr: std::ptr::NonNull::<f64>::dangling().as_ptr(),
        len: 99,
    };
    let rc = unsafe {
        apoc_interp_ne(std::ptr::null(), 0, std::ptr::null(), t.as_ptr(), 2, &mut out)
    };
    assert_eq!(rc, APOC_ERR_INVALID_ARGS);
    assert!(out.ptr.is_null());
    assert_eq!(out.len, 0);

    // a null required pointer with a non-zero length is rejected
    let mut out = zeroed_f64();
    let rc = unsafe {
        apoc_interp_ne(std::ptr::null(), 2, ne.as_ptr(), t.as_ptr(), 2, &mut out)
    };
    assert_eq!(rc, APOC_ERR_INVALID_ARGS);

    // a null out pointer is rejected without touching the inputs
    let rc = unsafe {
        apoc_interp_ne(t.as_ptr(), 2, ne.as_ptr(), t.as_ptr(), 2, std::ptr::null_mut())
    };
    assert_eq!(rc, APOC_ERR_INVALID_ARGS);

    // a half-present PDR pair is rejected by the mask edge
    let mut out = zeroed_u8();
    let rc = unsafe {
        apoc_trusted_fix_mask(
            t.as_ptr(),
            2,
            ne.as_ptr(),
            std::ptr::null(),
            t.as_ptr(),
            2,
            std::ptr::null(),
            std::ptr::null(),
            &mut out,
        )
    };
    assert_eq!(rc, APOC_ERR_INVALID_ARGS);
    assert!(out.ptr.is_null());
}
```

- [ ] **Step 2: Run to verify the tests fail**

Run: `cd core && cargo test -p apoc-ffi`
Expected: FAIL to compile with unresolved imports from `apoc_ffi::capi` (the stub module is empty).

- [ ] **Step 3: Implement `capi.rs`**

Replace `core/apoc-ffi/src/capi.rs` with:

```rust
//! The 100 Hz sensor lane: a direct C ABI over the `dto` wiring (the second lane of
//! spec section 4.1, bypassing Dart). All `unsafe` in the crate is confined to this
//! module. Every export is panic-guarded: a panic must never unwind across `extern "C"`.

use std::panic::{catch_unwind, AssertUnwindSafe};

use crate::dto::{self, TrustedFixParamsDto};

/// Call succeeded; the caller owns the out-buffer until the matching free.
pub const APOC_OK: i32 = 0;
/// Null pointer, empty required input, or inconsistent lengths. Out-buffer is zeroed.
pub const APOC_ERR_INVALID_ARGS: i32 = 1;
/// A panic was caught at the boundary. Out-buffer is zeroed.
pub const APOC_ERR_PANIC: i32 = 2;

/// Rust-owned f64 buffer handed across the C ABI. `ptr` is null iff `len == 0`.
/// Release exactly once with [`apoc_f64_buffer_free`]; never free from C.
#[repr(C)]
#[derive(Debug)]
pub struct ApocF64Buffer {
    pub ptr: *mut f64,
    pub len: usize,
}

/// Rust-owned u8 buffer (0/1 mask) handed across the C ABI. `ptr` is null iff `len == 0`.
/// Release exactly once with [`apoc_u8_buffer_free`]; never free from C.
#[repr(C)]
#[derive(Debug)]
pub struct ApocU8Buffer {
    pub ptr: *mut u8,
    pub len: usize,
}

/// Flat `#[repr(C)]` mirror of [`TrustedFixParamsDto`]: `use_innovation` is 0/1,
/// `acc_backstop_m` NaN means no backstop.
#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct ApocTrustedFixParams {
    pub max_speed_mps: f64,
    pub lock_window: usize,
    pub lock_disp_m: f64,
    pub max_gap_s: f64,
    pub max_cold_s: f64,
    pub acc_backstop_m: f64,
    pub use_innovation: u8,
    pub innovation_sigma: f64,
    pub innovation_floor_m: f64,
    pub min_fixes: usize,
}

impl From<TrustedFixParamsDto> for ApocTrustedFixParams {
    fn from(p: TrustedFixParamsDto) -> Self {
        Self {
            max_speed_mps: p.max_speed_mps,
            lock_window: p.lock_window,
            lock_disp_m: p.lock_disp_m,
            max_gap_s: p.max_gap_s,
            max_cold_s: p.max_cold_s,
            acc_backstop_m: p.acc_backstop_m,
            use_innovation: u8::from(p.use_innovation),
            innovation_sigma: p.innovation_sigma,
            innovation_floor_m: p.innovation_floor_m,
            min_fixes: p.min_fixes,
        }
    }
}

impl From<ApocTrustedFixParams> for TrustedFixParamsDto {
    fn from(p: ApocTrustedFixParams) -> Self {
        Self {
            max_speed_mps: p.max_speed_mps,
            lock_window: p.lock_window,
            lock_disp_m: p.lock_disp_m,
            max_gap_s: p.max_gap_s,
            max_cold_s: p.max_cold_s,
            acc_backstop_m: p.acc_backstop_m,
            use_innovation: p.use_innovation != 0,
            innovation_sigma: p.innovation_sigma,
            innovation_floor_m: p.innovation_floor_m,
            min_fixes: p.min_fixes,
        }
    }
}

fn f64_buffer(v: Vec<f64>) -> ApocF64Buffer {
    let boxed = v.into_boxed_slice();
    let len = boxed.len();
    if len == 0 {
        return ApocF64Buffer { ptr: std::ptr::null_mut(), len: 0 };
    }
    ApocF64Buffer { ptr: Box::into_raw(boxed) as *mut f64, len }
}

fn u8_buffer(v: Vec<u8>) -> ApocU8Buffer {
    let boxed = v.into_boxed_slice();
    let len = boxed.len();
    if len == 0 {
        return ApocU8Buffer { ptr: std::ptr::null_mut(), len: 0 };
    }
    ApocU8Buffer { ptr: Box::into_raw(boxed) as *mut u8, len }
}

/// Maps the panic-guarded wiring result onto the C error convention.
fn guarded<T, F: FnOnce() -> Option<T>>(f: F) -> Result<T, i32> {
    match catch_unwind(AssertUnwindSafe(f)) {
        Ok(Some(v)) => Ok(v),
        Ok(None) => Err(APOC_ERR_INVALID_ARGS),
        Err(_) => Err(APOC_ERR_PANIC),
    }
}

/// Required-input slice: a null `ptr` is accepted only for `len == 0`.
///
/// # Safety
/// A non-null `ptr` must be valid for `len` reads of `T` for the duration of the call.
unsafe fn slice_or_empty<'a, T>(ptr: *const T, len: usize) -> Option<&'a [T]> {
    if ptr.is_null() {
        return (len == 0).then(|| &[][..]);
    }
    // SAFETY: non-null; the caller guarantees validity for `len` reads per the contract.
    Some(unsafe { std::slice::from_raw_parts(ptr, len) })
}

/// Interpolate an NE track onto query times over the C ABI.
///
/// `t_src`: `t_src_len` times, strictly increasing (caller contract). `ne_src`:
/// `2 * t_src_len` row-major NE values. `t_query`: `t_query_len` times. On `APOC_OK`,
/// `*out` owns `2 * t_query_len` row-major NE values; release with
/// [`apoc_f64_buffer_free`]. On any error `*out` is zeroed and there is nothing to free.
///
/// # Safety
/// Every non-null data pointer must be valid for the stated number of reads. `out`
/// must be non-null and valid for a write.
#[no_mangle]
pub unsafe extern "C" fn apoc_interp_ne(
    t_src: *const f64,
    t_src_len: usize,
    ne_src: *const f64,
    t_query: *const f64,
    t_query_len: usize,
    out: *mut ApocF64Buffer,
) -> i32 {
    if out.is_null() {
        return APOC_ERR_INVALID_ARGS;
    }
    // SAFETY: out is non-null and valid for a write per the fn contract.
    unsafe { out.write(ApocF64Buffer { ptr: std::ptr::null_mut(), len: 0 }) };
    let Some(ne_len) = t_src_len.checked_mul(2) else {
        return APOC_ERR_INVALID_ARGS;
    };
    // SAFETY: pointer/length validity per the fn contract.
    let slices = unsafe {
        match (
            slice_or_empty(t_src, t_src_len),
            slice_or_empty(ne_src, ne_len),
            slice_or_empty(t_query, t_query_len),
        ) {
            (Some(a), Some(b), Some(c)) => Some((a, b, c)),
            _ => None,
        }
    };
    let Some((t_src_s, ne_src_s, t_query_s)) = slices else {
        return APOC_ERR_INVALID_ARGS;
    };
    match guarded(|| dto::interp_ne_view(t_src_s, ne_src_s, t_query_s)) {
        Ok(view) => {
            // SAFETY: out is non-null and valid for a write per the fn contract.
            unsafe { out.write(f64_buffer(view.ne)) };
            APOC_OK
        }
        Err(code) => code,
    }
}

/// Release a buffer returned by [`apoc_interp_ne`]. A null `buf` or an already-zeroed
/// buffer is a no-op. Re-zeroes the struct so an accidental double free is inert.
///
/// # Safety
/// A non-null `buf` must point to a writable `ApocF64Buffer` holding either the zeroed
/// state or exactly the `(ptr, len)` pair produced by this library, unmodified.
#[no_mangle]
pub unsafe extern "C" fn apoc_f64_buffer_free(buf: *mut ApocF64Buffer) {
    if buf.is_null() {
        return;
    }
    // SAFETY: buf is valid for read/write per the fn contract; a non-null (ptr, len)
    // came unmodified from f64_buffer, so it reconstructs the original Box<[f64]>.
    unsafe {
        let b = buf.read();
        if !b.ptr.is_null() {
            drop(Box::from_raw(std::ptr::slice_from_raw_parts_mut(b.ptr, b.len)));
        }
        buf.write(ApocF64Buffer { ptr: std::ptr::null_mut(), len: 0 });
    }
}

/// Trusted-fix keep-mask over the C ABI (the L0 gate).
///
/// `gnss_t`: `gnss_len` times. `gnss_ne`: `2 * gnss_len` row-major NE values.
/// `reported_acc_m`: null for absent, else `gnss_len` values. The PDR pair is absent
/// when `pdr_t` and `pdr_ne` are null and `pdr_len == 0`; when present, `pdr_t` holds
/// `pdr_len > 0` times and `pdr_ne` holds `2 * pdr_len` values. `params`: null for the
/// core defaults. On `APOC_OK`, `*out` owns `gnss_len` mask bytes (0/1); release with
/// [`apoc_u8_buffer_free`]. On any error `*out` is zeroed and there is nothing to free.
///
/// # Safety
/// Every non-null pointer must be valid for the stated number of reads (`params` for
/// one read). `out` must be non-null and valid for a write.
#[no_mangle]
#[allow(clippy::too_many_arguments)] // a flat C edge is flat by design
pub unsafe extern "C" fn apoc_trusted_fix_mask(
    gnss_t: *const f64,
    gnss_len: usize,
    gnss_ne: *const f64,
    reported_acc_m: *const f64,
    pdr_t: *const f64,
    pdr_len: usize,
    pdr_ne: *const f64,
    params: *const ApocTrustedFixParams,
    out: *mut ApocU8Buffer,
) -> i32 {
    if out.is_null() {
        return APOC_ERR_INVALID_ARGS;
    }
    // SAFETY: out is non-null and valid for a write per the fn contract.
    unsafe { out.write(ApocU8Buffer { ptr: std::ptr::null_mut(), len: 0 }) };
    let (Some(gnss_ne_len), Some(pdr_ne_len)) =
        (gnss_len.checked_mul(2), pdr_len.checked_mul(2))
    else {
        return APOC_ERR_INVALID_ARGS;
    };
    // SAFETY: pointer/length validity per the fn contract.
    let parts = unsafe {
        let gnss_t_s = slice_or_empty(gnss_t, gnss_len);
        let gnss_ne_s = slice_or_empty(gnss_ne, gnss_ne_len);
        // acc: null means absent, else gnss_len values
        let acc_s = if reported_acc_m.is_null() {
            Some(None)
        } else {
            Some(Some(std::slice::from_raw_parts(reported_acc_m, gnss_len)))
        };
        // PDR pair: both-null with len 0 means absent; both non-null means present;
        // anything else is malformed (dto also re-rejects half-present pairs).
        let pdr_s = match (pdr_t.is_null(), pdr_ne.is_null()) {
            (true, true) if pdr_len == 0 => Some((None, None)),
            (false, false) => Some((
                Some(std::slice::from_raw_parts(pdr_t, pdr_len)),
                Some(std::slice::from_raw_parts(pdr_ne, pdr_ne_len)),
            )),
            _ => None,
        };
        match (gnss_t_s, gnss_ne_s, acc_s, pdr_s) {
            (Some(a), Some(b), Some(c), Some((d, e))) => Some((a, b, c, d, e)),
            _ => None,
        }
    };
    let Some((gnss_t_s, gnss_ne_s, acc_s, pdr_t_s, pdr_ne_s)) = parts else {
        return APOC_ERR_INVALID_ARGS;
    };
    let dto_params = if params.is_null() {
        TrustedFixParamsDto::default()
    } else {
        // SAFETY: params is non-null and valid for one read per the fn contract.
        TrustedFixParamsDto::from(unsafe { params.read() })
    };
    match guarded(|| {
        dto::trusted_fix_view(gnss_t_s, gnss_ne_s, acc_s, pdr_t_s, pdr_ne_s, &dto_params)
    }) {
        Ok(view) => {
            let mask: Vec<u8> = view.keep.iter().map(|&b| u8::from(b)).collect();
            // SAFETY: out is non-null and valid for a write per the fn contract.
            unsafe { out.write(u8_buffer(mask)) };
            APOC_OK
        }
        Err(code) => code,
    }
}

/// Release a buffer returned by [`apoc_trusted_fix_mask`]. A null `buf` or an
/// already-zeroed buffer is a no-op. Re-zeroes the struct.
///
/// # Safety
/// A non-null `buf` must point to a writable `ApocU8Buffer` holding either the zeroed
/// state or exactly the `(ptr, len)` pair produced by this library, unmodified.
#[no_mangle]
pub unsafe extern "C" fn apoc_u8_buffer_free(buf: *mut ApocU8Buffer) {
    if buf.is_null() {
        return;
    }
    // SAFETY: buf is valid for read/write per the fn contract; a non-null (ptr, len)
    // came unmodified from u8_buffer, so it reconstructs the original Box<[u8]>.
    unsafe {
        let b = buf.read();
        if !b.ptr.is_null() {
            drop(Box::from_raw(std::ptr::slice_from_raw_parts_mut(b.ptr, b.len)));
        }
        buf.write(ApocU8Buffer { ptr: std::ptr::null_mut(), len: 0 });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn guarded_maps_panic_and_none_onto_error_codes() {
        let r: Result<(), i32> = guarded(|| panic!("boom"));
        assert_eq!(r.unwrap_err(), APOC_ERR_PANIC);
        let r: Result<(), i32> = guarded(|| None);
        assert_eq!(r.unwrap_err(), APOC_ERR_INVALID_ARGS);
        assert_eq!(guarded(|| Some(7)).unwrap(), 7);
    }
}
```

- [ ] **Step 4: Run to verify the tests pass**

Run: `cd core && cargo test -p apoc-ffi`
Expected: PASS, 6 tests (2 DTO wiring + 3 C-ABI integration + 1 panic-guard unit).

- [ ] **Step 5: Symbol check on the cdylib**

Run: `cd core && cargo build -p apoc-ffi && nm -D target/debug/libapoc_ffi.so | grep ' T apoc_'`
Expected: exactly four lines: `apoc_f64_buffer_free`, `apoc_interp_ne`, `apoc_trusted_fix_mask`, `apoc_u8_buffer_free`.

- [ ] **Step 6: Optional C harness (scratchpad, not committed)**

Write a minimal C file in the scratchpad declaring the buffer struct and `apoc_interp_ne`/`apoc_f64_buffer_free`, compile with `cc -o harness harness.c -L core/target/debug -lapoc_ffi -Wl,-rpath,core/target/debug`, run it, and confirm it prints the interpolated values and exits 0. This proves a plain-C toolchain can call and free across the boundary with no Rust in sight.

- [ ] **Step 7: Commit**

```bash
git add core/apoc-ffi
git commit -m "feat(ffi): C-ABI sensor lane with owned buffers and panic guards"
```

---

### Task 3: Lock down the pure crates + track `core/Cargo.lock`

Closes the two slice-0 follow-ups now that a binary artifact ships from the workspace. `apoc-geo` and `apoc-positioning` are already unsafe-free, so `#![forbid(unsafe_code)]` is a lock, not a change. `apoc-ffi` cannot take a crate-level forbid (`capi` needs raw-pointer `unsafe`); it already carries `#![deny(unsafe_op_in_unsafe_fn)]` crate-wide and `#![forbid(unsafe_code)]` on the `dto` module. Deliverable: clippy clean workspace-wide, all tests green, `core/Cargo.lock` tracked.

**Files:**
- Modify: `core/apoc-geo/src/lib.rs`
- Modify: `core/apoc-positioning/src/lib.rs`
- Modify: `core/.gitignore`
- Create (track): `core/Cargo.lock`

- [ ] **Step 1: Forbid unsafe in the pure crates**

Add as the first line below the module doc comment in `core/apoc-geo/src/lib.rs` and `core/apoc-positioning/src/lib.rs`:

```rust
#![forbid(unsafe_code)]
```

- [ ] **Step 2: Track the lockfile**

Edit `core/.gitignore` to remove the `/Cargo.lock` line (keep `/target`). Then:

Run: `cd core && cargo build --workspace && git add core/Cargo.lock core/.gitignore`
Expected: `core/Cargo.lock` is staged (a cdylib/staticlib now ships from this workspace, so the lockfile is part of the reproducible build).

- [ ] **Step 3: Full verification sweep**

Run: `cd core && cargo test && cargo clippy --workspace --all-targets -- -D warnings`
Expected: all tests green across the three crates (14 existing + 6 new = 20); clippy reports no warnings.

- [ ] **Step 4: Commit**

```bash
git add core/apoc-geo/src/lib.rs core/apoc-positioning/src/lib.rs core/.gitignore core/Cargo.lock
git commit -m "build(ffi): forbid unsafe in pure crates, track core/Cargo.lock"
```

---

## Self-Review

**1. Spec coverage.** This plan builds exactly the Group A half of the slice-0b foundations plan: the single crossing (spec section 4.1) over the two existing core calls, on the C-ABI sensor lane, plus the two recorded slice-0 follow-ups. The frb lane, view types, session/capability ports, and iOS link are explicitly deferred in "Out of scope" and in the foundations plan itself.

**2. Placeholder scan.** Every code step shows complete code; every run step has an exact command and expected output.

**3. Type consistency.** `TrustedFixParamsDto` mirrors `TrustedFixParams` field-for-field with `acc_backstop_m: f64` (NaN==None) as the only representation change; `ApocTrustedFixParams` mirrors the DTO with `use_innovation: u8` as the only further change; both `From` impls cover both directions used by tests. Buffer `(ptr, len)` pairs come from `into_boxed_slice`, so the free-side `Box` reconstruction is exact. The four exported symbols named in Task 2 Step 5 match the four `#[no_mangle]` functions in the code.

---

## Execution Handoff

Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks (superpowers:subagent-driven-development).
2. **Inline Execution** - execute the tasks in this session with checkpoints for review (superpowers:executing-plans).
