use apoc_ffi::capi::{
    apoc_f64_buffer_free, apoc_interp_ne, apoc_trusted_fix_mask, apoc_u8_buffer_free,
    ApocF64Buffer, ApocTrustedFixParams, ApocU8Buffer, APOC_ERR_INVALID_ARGS, APOC_OK,
};
use apoc_positioning::gnss_gate::TrustedFixParams;

fn zeroed_f64() -> ApocF64Buffer {
    ApocF64Buffer {
        ptr: std::ptr::null_mut(),
        len: 0,
    }
}

fn zeroed_u8() -> ApocU8Buffer {
    ApocU8Buffer {
        ptr: std::ptr::null_mut(),
        len: 0,
    }
}

fn north_track(n: usize) -> (Vec<f64>, Vec<f64>) {
    let t: Vec<f64> = (0..n).map(|i| i as f64).collect();
    let mut ne = Vec::new();
    for i in 0..n {
        ne.extend_from_slice(&[i as f64, 0.0]);
    }
    (t, ne)
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
    let (gnss_t, mut gnss_ne) = north_track(10);
    gnss_ne[10] = 800.0;
    let mut acc = [14.0; 10];
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
    let mut params = ApocTrustedFixParams::from(&TrustedFixParams::default());
    params.acc_backstop_m = f64::NAN;
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
    let rc =
        unsafe { apoc_interp_ne(std::ptr::null(), 0, std::ptr::null(), t.as_ptr(), 2, &mut out) };
    assert_eq!(rc, APOC_ERR_INVALID_ARGS);
    assert!(out.ptr.is_null());
    assert_eq!(out.len, 0);

    // a null required pointer with a non-zero length is rejected
    let mut out = zeroed_f64();
    let rc = unsafe { apoc_interp_ne(std::ptr::null(), 2, ne.as_ptr(), t.as_ptr(), 2, &mut out) };
    assert_eq!(rc, APOC_ERR_INVALID_ARGS);

    // a null out pointer is rejected without touching the inputs
    let rc = unsafe {
        apoc_interp_ne(
            t.as_ptr(),
            2,
            ne.as_ptr(),
            t.as_ptr(),
            2,
            std::ptr::null_mut(),
        )
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

#[test]
fn boundary_rejects_data_that_would_panic_or_corrupt_the_core() {
    let (gnss_t, gnss_ne) = north_track(10);

    // a zero-initialized params struct (the common C memset init) must be INVALID_ARGS,
    // not a caught panic: lock_window == 0 would index-wrap inside core lock_time
    let zeroed_params = ApocTrustedFixParams {
        max_speed_mps: 0.0,
        lock_window: 0,
        lock_disp_m: 0.0,
        max_gap_s: 0.0,
        max_cold_s: 0.0,
        acc_backstop_m: 0.0,
        use_innovation: 0,
        innovation_sigma: 0.0,
        innovation_floor_m: 0.0,
        min_fixes: 0,
    };
    let mut out = zeroed_u8();
    let rc = unsafe {
        apoc_trusted_fix_mask(
            gnss_t.as_ptr(),
            gnss_t.len(),
            gnss_ne.as_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            0,
            std::ptr::null(),
            &zeroed_params,
            &mut out,
        )
    };
    assert_eq!(rc, APOC_ERR_INVALID_ARGS);
    assert!(out.ptr.is_null());

    // a NaN coordinate with the innovation gate on would panic core median();
    // without it a NaN silently passes the gates. Both are rejected at the edge.
    let mut params = ApocTrustedFixParams::from(&TrustedFixParams::default());
    params.use_innovation = 1;
    let mut nan_ne = gnss_ne.clone();
    nan_ne[12] = f64::NAN;
    let mut out = zeroed_u8();
    let rc = unsafe {
        apoc_trusted_fix_mask(
            gnss_t.as_ptr(),
            gnss_t.len(),
            nan_ne.as_ptr(),
            std::ptr::null(),
            gnss_t.as_ptr(),
            gnss_t.len(),
            gnss_ne.as_ptr(),
            &params,
            &mut out,
        )
    };
    assert_eq!(rc, APOC_ERR_INVALID_ARGS);

    // non-monotonic t_src must be INVALID_ARGS, never APOC_OK with garbage positions
    let t_bad = [0.0, 1.0, 1.0, 2.0];
    let (_, ne4) = north_track(4);
    let q = [0.5];
    let mut out = zeroed_f64();
    let rc = unsafe {
        apoc_interp_ne(t_bad.as_ptr(), 4, ne4.as_ptr(), q.as_ptr(), 1, &mut out)
    };
    assert_eq!(rc, APOC_ERR_INVALID_ARGS);
    assert!(out.ptr.is_null());
}
