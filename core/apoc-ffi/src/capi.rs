//! The 100 Hz sensor lane: a direct C ABI over the `dto` wiring (the second lane of
//! spec section 4.1, bypassing Dart). All `unsafe` in the crate is confined to this
//! module. Every export is panic-guarded as a backstop; the guard assumes the crate
//! is built with `panic = "unwind"` (the default). Do not set `panic = "abort"` on a
//! profile that ships this crate without revisiting the guard: under abort a caught
//! panic becomes a process abort. Known panic triggers are rejected as invalid
//! arguments in `dto` before they can reach the core.

use std::panic::{catch_unwind, AssertUnwindSafe};

use apoc_positioning::gnss_gate::TrustedFixParams;

use crate::dto;

/// Call succeeded; the caller owns the out-buffer until the matching free.
pub const APOC_OK: i32 = 0;
/// Null pointer, empty required input, inconsistent lengths, non-finite or
/// non-monotonic data, or degenerate params. Out-buffer is zeroed.
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

/// Flat `#[repr(C)]` mirror of the core [`TrustedFixParams`]: `use_innovation` is 0/1,
/// `acc_backstop_m` NaN means no backstop (an `Option` cannot cross the C ABI).
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

impl From<&TrustedFixParams> for ApocTrustedFixParams {
    fn from(p: &TrustedFixParams) -> Self {
        Self {
            max_speed_mps: p.max_speed_mps,
            lock_window: p.lock_window,
            lock_disp_m: p.lock_disp_m,
            max_gap_s: p.max_gap_s,
            max_cold_s: p.max_cold_s,
            acc_backstop_m: p.acc_backstop_m.unwrap_or(f64::NAN),
            use_innovation: u8::from(p.use_innovation),
            innovation_sigma: p.innovation_sigma,
            innovation_floor_m: p.innovation_floor_m,
            min_fixes: p.min_fixes,
        }
    }
}

impl From<ApocTrustedFixParams> for TrustedFixParams {
    fn from(p: ApocTrustedFixParams) -> Self {
        Self {
            max_speed_mps: p.max_speed_mps,
            lock_window: p.lock_window,
            lock_disp_m: p.lock_disp_m,
            max_gap_s: p.max_gap_s,
            max_cold_s: p.max_cold_s,
            acc_backstop_m: (!p.acc_backstop_m.is_nan()).then_some(p.acc_backstop_m),
            use_innovation: p.use_innovation != 0,
            innovation_sigma: p.innovation_sigma,
            innovation_floor_m: p.innovation_floor_m,
            min_fixes: p.min_fixes,
        }
    }
}

/// Hand a Vec to C as `(ptr, len)`. `into_boxed_slice` guarantees `len == cap`,
/// so [`free_raw_parts`] can reconstruct the exact `Box<[T]>`. Null iff empty.
fn into_raw_parts<T>(v: Vec<T>) -> (*mut T, usize) {
    let boxed = v.into_boxed_slice();
    let len = boxed.len();
    if len == 0 {
        return (std::ptr::null_mut(), 0);
    }
    (Box::into_raw(boxed) as *mut T, len)
}

/// Release a `(ptr, len)` pair produced by [`into_raw_parts`]. Null is a no-op.
///
/// # Safety
/// A non-null `(ptr, len)` must be exactly a pair produced by `into_raw_parts`,
/// unmodified and not yet freed.
unsafe fn free_raw_parts<T>(ptr: *mut T, len: usize) {
    if !ptr.is_null() {
        // SAFETY: per the fn contract this reconstructs the original Box<[T]>.
        unsafe { drop(Box::from_raw(std::ptr::slice_from_raw_parts_mut(ptr, len))) };
    }
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
/// `t_src`: `t_src_len` strictly increasing finite times. `ne_src`: `2 * t_src_len`
/// row-major finite NE values. `t_query`: `t_query_len` finite times. On `APOC_OK`,
/// `*out` owns `2 * t_query_len` row-major NE values; release with
/// [`apoc_f64_buffer_free`]. On any error `*out` is zeroed and there is nothing to
/// free. Non-finite or non-monotonic data returns `APOC_ERR_INVALID_ARGS`.
///
/// # Safety
/// Every non-null data pointer must be valid for the stated number of reads. `out`
/// must be non-null, valid for a write, and must not overlap any input buffer.
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
    unsafe {
        out.write(ApocF64Buffer {
            ptr: std::ptr::null_mut(),
            len: 0,
        })
    };
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
            let (ptr, len) = into_raw_parts(view.ne);
            // SAFETY: out is non-null and valid for a write per the fn contract.
            unsafe { out.write(ApocF64Buffer { ptr, len }) };
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
    // SAFETY: buf is valid for read/write and holds a library-produced pair per the
    // fn contract, which is exactly free_raw_parts' contract.
    unsafe {
        let b = buf.read();
        free_raw_parts(b.ptr, b.len);
        buf.write(ApocF64Buffer {
            ptr: std::ptr::null_mut(),
            len: 0,
        });
    }
}

/// Trusted-fix keep-mask over the C ABI (the L0 gate).
///
/// `gnss_t`: `gnss_len` finite times. `gnss_ne`: `2 * gnss_len` row-major finite NE
/// values. `reported_acc_m`: null for absent, else `gnss_len` values. The PDR pair is
/// absent when `pdr_t` and `pdr_ne` are null and `pdr_len == 0`; when present, `pdr_t`
/// holds `pdr_len > 0` strictly increasing finite times and `pdr_ne` holds
/// `2 * pdr_len` finite values. `params`: null for the core defaults; `lock_window`
/// must be at least 1. On `APOC_OK`, `*out` owns `gnss_len` mask bytes (0/1); release
/// with [`apoc_u8_buffer_free`]. On any error `*out` is zeroed and there is nothing
/// to free. Non-finite data and degenerate params return `APOC_ERR_INVALID_ARGS`.
///
/// # Safety
/// Every non-null pointer must be valid for the stated number of reads (`params` for
/// one read). `out` must be non-null, valid for a write, and must not overlap any
/// input buffer.
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
    unsafe {
        out.write(ApocU8Buffer {
            ptr: std::ptr::null_mut(),
            len: 0,
        })
    };
    let (Some(gnss_ne_len), Some(pdr_ne_len)) = (gnss_len.checked_mul(2), pdr_len.checked_mul(2))
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
    let core_params = if params.is_null() {
        TrustedFixParams::default()
    } else {
        // SAFETY: params is non-null and valid for one read per the fn contract.
        TrustedFixParams::from(unsafe { params.read() })
    };
    match guarded(|| {
        dto::trusted_fix_view(gnss_t_s, gnss_ne_s, acc_s, pdr_t_s, pdr_ne_s, &core_params)
    }) {
        Ok(view) => {
            let mask: Vec<u8> = view.keep.iter().map(|&b| u8::from(b)).collect();
            let (ptr, len) = into_raw_parts(mask);
            // SAFETY: out is non-null and valid for a write per the fn contract.
            unsafe { out.write(ApocU8Buffer { ptr, len }) };
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
    // SAFETY: buf is valid for read/write and holds a library-produced pair per the
    // fn contract, which is exactly free_raw_parts' contract.
    unsafe {
        let b = buf.read();
        free_raw_parts(b.ptr, b.len);
        buf.write(ApocU8Buffer {
            ptr: std::ptr::null_mut(),
            len: 0,
        });
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
