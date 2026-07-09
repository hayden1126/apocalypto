//! Safe wiring over the core calls on flat owned buffers (the "flat owned data,
//! no lifetimes, no crypto" rule from spec section 4.1). No raw pointers in this
//! module; the C-ABI edge lives in `capi`. This layer owns DATA validation
//! (shapes, finiteness, monotonicity, degenerate params): the core crates trust
//! their preconditions, untrusted callers do not get to violate them.
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

fn strictly_increasing(t: &[f64]) -> bool {
    t.windows(2).all(|w| w[0] < w[1])
}

fn all_finite(values: &[f64]) -> bool {
    values.iter().all(|v| v.is_finite())
}

/// Safe wiring over [`apoc_geo::interp_ne`] on flat row-major buffers.
/// Returns `None` on invalid data: empty or non-strictly-increasing `t_src`
/// (the core call panics on empty and silently mis-interpolates on unsorted;
/// the check also rejects NaN times), `ne_src_flat.len() != 2 * t_src.len()`,
/// or any non-finite coordinate or query time.
pub fn interp_ne_view(t_src: &[f64], ne_src_flat: &[f64], t_query: &[f64]) -> Option<InterpNeView> {
    if t_src.is_empty()
        || ne_src_flat.len() != 2 * t_src.len()
        || !strictly_increasing(t_src)
        || !all_finite(ne_src_flat)
        || !all_finite(t_query)
    {
        return None;
    }
    let (ne_src, _) = ne_src_flat.as_chunks::<2>();
    Some(InterpNeView {
        ne: apoc_geo::interp_ne(t_src, ne_src, t_query).into_flattened(),
    })
}

/// Safe wiring over [`trusted_fix_mask`] on flat buffers. Optional inputs follow one
/// rule: present means non-empty and shape-consistent. Returns `None` when
/// `params.lock_window == 0` (the core indexes `gnss_t[i + lock_window - 1]`),
/// `gnss_ne_flat.len() != 2 * gnss_t.len()`, any time or coordinate is non-finite
/// (a NaN position would silently PASS the core's comparison-based gates), or the
/// PDR pair is half-present, empty, inconsistent, or non-strictly-increasing in
/// time (it feeds `interp_ne`). A NaN in `reported_acc_m` is allowed: the core's
/// backstop comparison rejects that fix, which is the safe direction. An empty
/// GNSS track is valid and yields an empty mask, as in the core call.
pub fn trusted_fix_view(
    gnss_t: &[f64],
    gnss_ne_flat: &[f64],
    reported_acc_m: Option<&[f64]>,
    pdr_t: Option<&[f64]>,
    pdr_ne_flat: Option<&[f64]>,
    params: &TrustedFixParams,
) -> Option<TrustedFixView> {
    if params.lock_window == 0 {
        return None;
    }
    if gnss_ne_flat.len() != 2 * gnss_t.len() || !all_finite(gnss_t) || !all_finite(gnss_ne_flat) {
        return None;
    }
    if let Some(acc) = reported_acc_m {
        if acc.len() != gnss_t.len() {
            return None;
        }
    }
    let pdr = match (pdr_t, pdr_ne_flat) {
        (None, None) => None,
        (Some(t), Some(ne_flat))
            if !t.is_empty()
                && ne_flat.len() == 2 * t.len()
                && strictly_increasing(t)
                && all_finite(ne_flat) =>
        {
            Some((t, ne_flat.as_chunks::<2>().0))
        }
        _ => return None,
    };
    let (gnss_ne, _) = gnss_ne_flat.as_chunks::<2>();
    let keep = trusted_fix_mask(gnss_t, gnss_ne, reported_acc_m, pdr, params);
    Some(TrustedFixView { keep })
}
