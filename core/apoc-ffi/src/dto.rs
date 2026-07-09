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
