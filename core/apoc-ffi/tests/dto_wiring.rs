use apoc_ffi::dto::{interp_ne_view, trusted_fix_view};
use apoc_positioning::gnss_gate::{trusted_fix_mask, TrustedFixParams};

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
fn interp_ne_view_rejects_invalid_data() {
    let ne = [0.0, 0.0, 1.0, 0.0, 2.0, 0.0];
    let q = [0.5];
    // non-monotonic and duplicate timestamps: the core would silently mis-interpolate
    assert!(interp_ne_view(&[0.0, 2.0, 1.0], &ne, &q).is_none());
    assert!(interp_ne_view(&[0.0, 1.0, 1.0], &ne, &q).is_none());
    // NaN in times (caught by the monotonicity check), coordinates, and query times
    assert!(interp_ne_view(&[0.0, f64::NAN, 2.0], &ne, &q).is_none());
    let mut bad_ne = ne;
    bad_ne[3] = f64::INFINITY;
    assert!(interp_ne_view(&[0.0, 1.0, 2.0], &bad_ne, &q).is_none());
    assert!(interp_ne_view(&[0.0, 1.0, 2.0], &ne, &[f64::NAN]).is_none());
}

#[test]
fn trusted_fix_view_matches_core_and_validates() {
    // 10 fixes north at 1 m/s, an 800 m teleport at index 5, absurd reported acc at 3.
    let gnss_t: Vec<f64> = (0..10).map(|i| i as f64).collect();
    let mut ne_flat = Vec::new();
    for i in 0..10 {
        ne_flat.extend_from_slice(&[i as f64, 0.0]);
    }
    ne_flat[10] = 800.0; // north component of fix 5
    let mut acc = [14.0; 10];
    acc[3] = 807.0;

    // no backstop: index 3 survives, the teleport falls.
    let mut p = TrustedFixParams {
        acc_backstop_m: None,
        lock_disp_m: 1e9,
        ..Default::default()
    };
    let view = trusted_fix_view(&gnss_t, &ne_flat, Some(&acc), None, None, &p).unwrap();
    let expect: Vec<bool> = (0..10).map(|i| i != 5).collect();
    assert_eq!(view.keep, expect);

    // a finite backstop rejects index 3 as well; parity with the core call
    p.acc_backstop_m = Some(50.0);
    let view = trusted_fix_view(&gnss_t, &ne_flat, Some(&acc), None, None, &p).unwrap();
    let gnss_pairs: Vec<[f64; 2]> = ne_flat.chunks_exact(2).map(|c| [c[0], c[1]]).collect();
    let core = trusted_fix_mask(&gnss_t, &gnss_pairs, Some(&acc), None, &p);
    assert_eq!(view.keep, core);
    assert!(!view.keep[3] && !view.keep[5]);

    // wrong-length acc and a half-present PDR pair are rejected
    assert!(trusted_fix_view(&gnss_t, &ne_flat, Some(&acc[..5]), None, None, &p).is_none());
    assert!(trusted_fix_view(&gnss_t, &ne_flat, None, Some(&gnss_t), None, &p).is_none());
    // empty GNSS is a valid degenerate input: empty mask, as in the core call
    let empty = trusted_fix_view(&[], &[], None, None, None, &p).unwrap();
    assert!(empty.keep.is_empty());
}

#[test]
fn trusted_fix_view_rejects_degenerate_params_and_nonfinite_data() {
    let gnss_t: Vec<f64> = (0..10).map(|i| i as f64).collect();
    let mut ne_flat = Vec::new();
    for i in 0..10 {
        ne_flat.extend_from_slice(&[i as f64, 0.0]);
    }

    // lock_window == 0 (e.g. a zero-initialized C struct) would panic in core lock_time
    let zeroed = TrustedFixParams {
        lock_window: 0,
        ..Default::default()
    };
    assert!(trusted_fix_view(&gnss_t, &ne_flat, None, None, None, &zeroed).is_none());

    // a NaN coordinate would silently PASS the comparison-based gates (and panics the
    // innovation path in core median); the edge rejects it outright
    let p = TrustedFixParams {
        lock_disp_m: 1e9,
        ..Default::default()
    };
    let mut nan_ne = ne_flat.clone();
    nan_ne[12] = f64::NAN;
    assert!(trusted_fix_view(&gnss_t, &nan_ne, None, None, None, &p).is_none());
    let innov = TrustedFixParams {
        use_innovation: true,
        lock_disp_m: 1e9,
        ..Default::default()
    };
    assert!(
        trusted_fix_view(&gnss_t, &nan_ne, None, Some(&gnss_t), Some(&ne_flat), &innov).is_none()
    );

    // a non-monotonic PDR time base feeds interp_ne: rejected
    let mut bad_pdr_t = gnss_t.clone();
    bad_pdr_t[4] = 2.0;
    assert!(
        trusted_fix_view(&gnss_t, &ne_flat, None, Some(&bad_pdr_t), Some(&ne_flat), &innov)
            .is_none()
    );
}
