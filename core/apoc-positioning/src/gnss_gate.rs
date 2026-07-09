//! Offline, position-domain gate selecting trustworthy GNSS fixes for re-anchoring.
//! Ported from prototypes/pdr-benchmark/pdr_bench/pdr/trusted_fix.py (the numerical oracle).

use apoc_geo::interp_ne;

fn dist(a: [f64; 2], b: [f64; 2]) -> f64 {
    ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2)).sqrt()
}

/// First fix time whose forward window is tight (radius < `lock_disp_m`) AND contiguous.
/// Falls back to `gnss_t[0]` (trim nothing) if no such window exists in the opening.
fn lock_time(
    gnss_t: &[f64],
    gnss_ne: &[[f64; 2]],
    lock_window: usize,
    lock_disp_m: f64,
    max_gap_s: f64,
    max_cold_s: f64,
) -> f64 {
    let n = gnss_t.len();
    if n <= lock_window {
        return gnss_t[0];
    }
    for i in 0..=(n - lock_window) {
        if gnss_t[i] - gnss_t[0] > max_cold_s {
            break;
        }
        let win = &gnss_ne[i..i + lock_window];
        let mut c = [0.0_f64, 0.0_f64];
        for p in win {
            c[0] += p[0];
            c[1] += p[1];
        }
        c[0] /= lock_window as f64;
        c[1] /= lock_window as f64;
        let mut radius = 0.0_f64;
        for p in win {
            radius = radius.max(dist(*p, c));
        }
        let span = gnss_t[i + lock_window - 1] - gnss_t[i];
        if radius < lock_disp_m && span < lock_window as f64 * max_gap_s {
            return gnss_t[i];
        }
    }
    gnss_t[0]
}

/// Causal jump gate: reject a fix implying more than `max_speed_mps` vs the last ACCEPTED fix.
fn speed_keep(gnss_t: &[f64], gnss_ne: &[[f64; 2]], max_speed_mps: f64, start: usize) -> Vec<bool> {
    let n = gnss_t.len();
    let mut keep = vec![true; n];
    let mut j = start;
    for i in (start + 1)..n {
        let dt = gnss_t[i] - gnss_t[j];
        if dt > 0.0 && dist(gnss_ne[i], gnss_ne[j]) / dt > max_speed_mps {
            keep[i] = false; // reject; do not advance the reference
        } else {
            j = i;
        }
    }
    keep
}

/// Tunable thresholds for [`trusted_fix_mask`]. `Default` carries the prototype's values.
#[derive(Clone, Debug)]
pub struct TrustedFixParams {
    pub max_speed_mps: f64,
    pub lock_window: usize,
    pub lock_disp_m: f64,
    pub max_gap_s: f64,
    pub max_cold_s: f64,
    pub acc_backstop_m: Option<f64>,
    pub use_innovation: bool,
    pub innovation_sigma: f64,
    pub innovation_floor_m: f64,
    pub min_fixes: usize,
}

impl Default for TrustedFixParams {
    fn default() -> Self {
        Self {
            max_speed_mps: 5.0,
            lock_window: 8,
            lock_disp_m: 5.0,
            max_gap_s: 6.0,
            max_cold_s: 120.0,
            acc_backstop_m: Some(50.0),
            use_innovation: false,
            innovation_sigma: 5.0,
            innovation_floor_m: 15.0,
            min_fixes: 2,
        }
    }
}

fn median(values: &[f64]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let mut v = values.to_vec();
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = v.len();
    if n % 2 == 1 {
        v[n / 2]
    } else {
        0.5 * (v[n / 2 - 1] + v[n / 2])
    }
}

fn first_true(mask: &[bool]) -> usize {
    mask.iter().position(|&b| b).unwrap_or(0)
}

/// Boolean keep-mask over `(gnss_t, gnss_ne)` for re-anchoring. `pdr` is `(pdr_t, pdr_ne)`,
/// consulted only when `params.use_innovation` is true. See the module docstring.
pub fn trusted_fix_mask(
    gnss_t: &[f64],
    gnss_ne: &[[f64; 2]],
    reported_acc_m: Option<&[f64]>,
    pdr: Option<(&[f64], &[[f64; 2]])>,
    params: &TrustedFixParams,
) -> Vec<bool> {
    let n = gnss_t.len();
    if n == 0 {
        return Vec::new();
    }

    let t_lock = lock_time(
        gnss_t,
        gnss_ne,
        params.lock_window,
        params.lock_disp_m,
        params.max_gap_s,
        params.max_cold_s,
    );
    let keep_cold: Vec<bool> = gnss_t.iter().map(|&t| t >= t_lock).collect();
    // seed the speed gate at the first post-lock fix so cold-start scatter cannot poison it
    let keep_speed = speed_keep(gnss_t, gnss_ne, params.max_speed_mps, first_true(&keep_cold));

    let keep_acc: Vec<bool> = match (params.acc_backstop_m, reported_acc_m) {
        (Some(backstop), Some(acc)) => acc.iter().map(|&a| a < backstop).collect(),
        _ => vec![true; n],
    };

    let keep_innov: Vec<bool> = match (params.use_innovation, pdr) {
        (true, Some((pdr_t, pdr_ne))) => {
            let pred = interp_ne(pdr_t, pdr_ne, gnss_t);
            let res: Vec<f64> = (0..n).map(|i| dist(gnss_ne[i], pred[i])).collect();
            let med = median(&res);
            let abs_dev: Vec<f64> = res.iter().map(|r| (r - med).abs()).collect();
            let mad = median(&abs_dev);
            let thr = (med + params.innovation_sigma * 1.4826 * mad).max(params.innovation_floor_m);
            res.iter().map(|&r| r <= thr).collect()
        }
        _ => vec![true; n],
    };

    let combine = |masks: &[&[bool]]| -> Vec<bool> {
        (0..n).map(|i| masks.iter().all(|m| m[i])).collect()
    };
    let count = |m: &[bool]| m.iter().filter(|&&b| b).count();

    let keep = combine(&[&keep_cold, &keep_speed, &keep_acc, &keep_innov]);
    if count(&keep) >= params.min_fixes {
        return keep;
    }
    // graceful degradation: never hand the re-anchor loop a starved track. Relax in the
    // prototype's order: past innovation, then speed, then cold-start, then all filters.
    let ladder: [Vec<bool>; 4] = [
        combine(&[&keep_cold, &keep_speed, &keep_acc]),
        combine(&[&keep_cold, &keep_acc]),
        keep_acc.clone(),
        vec![true; n],
    ];
    for relaxed in ladder {
        if count(&relaxed) >= params.min_fixes {
            return relaxed;
        }
    }
    vec![true; n]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn speed_keep_rejects_teleport() {
        let t: Vec<f64> = (0..10).map(|i| i as f64).collect();
        let mut ne: Vec<[f64; 2]> = (0..10).map(|i| [i as f64, 0.0]).collect();
        ne[5] = [800.0, 0.0];
        let keep = speed_keep(&t, &ne, 5.0, 0);
        assert!(!keep[5]);
        for i in [0, 1, 2, 3, 4, 6, 7, 8, 9] {
            assert!(keep[i]);
        }
    }

    #[test]
    fn lock_time_latches_after_scatter() {
        let scatter = [
            [-30.0, 20.0], [25.0, -28.0], [10.0, 30.0], [-22.0, -15.0], [30.0, 5.0],
        ];
        let stable = [
            [0.1, 0.0], [-0.1, 0.2], [0.0, -0.1], [0.2, 0.1], [-0.2, 0.0],
            [0.1, -0.2], [0.0, 0.1], [-0.1, -0.1], [0.2, 0.0], [0.0, 0.2],
        ];
        let mut ne: Vec<[f64; 2]> = Vec::new();
        ne.extend_from_slice(&scatter);
        ne.extend_from_slice(&stable);
        let t: Vec<f64> = (0..15).map(|i| i as f64).collect();
        assert_eq!(lock_time(&t, &ne, 5, 5.0, 6.0, 120.0), 5.0);
    }

    fn line_north(n: usize) -> (Vec<f64>, Vec<[f64; 2]>) {
        let t: Vec<f64> = (0..n).map(|i| i as f64).collect();
        let ne: Vec<[f64; 2]> = (0..n).map(|i| [i as f64, 0.0]).collect();
        (t, ne)
    }

    #[test]
    fn rejects_speed_jump_outlier() {
        let (t, mut ne) = line_north(10);
        ne[5] = [800.0, 0.0];
        let p = TrustedFixParams {
            max_speed_mps: 5.0,
            acc_backstop_m: None,
            lock_disp_m: 1e9,
            ..Default::default()
        };
        let keep = trusted_fix_mask(&t, &ne, None, None, &p);
        assert!(!keep[5]);
        for i in [0, 1, 2, 3, 4, 6, 7, 8, 9] {
            assert!(keep[i]);
        }
    }

    #[test]
    fn trims_cold_start_scatter() {
        let scatter = [
            [-30.0, 20.0], [25.0, -28.0], [10.0, 30.0], [-22.0, -15.0], [30.0, 5.0],
        ];
        let stable = [
            [0.1, 0.0], [-0.1, 0.2], [0.0, -0.1], [0.2, 0.1], [-0.2, 0.0],
            [0.1, -0.2], [0.0, 0.1], [-0.1, -0.1], [0.2, 0.0], [0.0, 0.2],
        ];
        let mut ne: Vec<[f64; 2]> = Vec::new();
        ne.extend_from_slice(&scatter);
        ne.extend_from_slice(&stable);
        let t: Vec<f64> = (0..15).map(|i| i as f64).collect();
        let p = TrustedFixParams {
            max_speed_mps: 1e9,
            acc_backstop_m: None,
            lock_window: 5,
            lock_disp_m: 5.0,
            ..Default::default()
        };
        let keep = trusted_fix_mask(&t, &ne, None, None, &p);
        assert!(keep[..5].iter().all(|&b| !b));
        assert!(keep[5..].iter().all(|&b| b));
    }

    #[test]
    fn keeps_pessimistic_reported_accuracy() {
        let (t, ne) = line_north(10);
        let acc = vec![14.0; 10];
        let p = TrustedFixParams {
            acc_backstop_m: Some(50.0),
            lock_disp_m: 1e9,
            ..Default::default()
        };
        let keep = trusted_fix_mask(&t, &ne, Some(&acc), None, &p);
        assert!(keep.iter().all(|&b| b));
    }

    #[test]
    fn backstop_rejects_absurd_reported() {
        let (t, ne) = line_north(10);
        let mut acc = vec![14.0; 10];
        acc[3] = 807.0;
        let p = TrustedFixParams {
            acc_backstop_m: Some(50.0),
            lock_disp_m: 1e9,
            max_speed_mps: 1e9,
            ..Default::default()
        };
        let keep = trusted_fix_mask(&t, &ne, Some(&acc), None, &p);
        assert!(!keep[3]);
        for i in [0, 1, 2, 4, 5, 6, 7, 8, 9] {
            assert!(keep[i]);
        }
    }

    #[test]
    fn never_starves_below_min_fixes() {
        let t: Vec<f64> = (0..4).map(|i| i as f64).collect();
        let ne: Vec<[f64; 2]> = (0..4).map(|i| [i as f64 * 100.0, 0.0]).collect();
        let p = TrustedFixParams {
            max_speed_mps: 5.0,
            acc_backstop_m: None,
            lock_disp_m: 1e9,
            min_fixes: 2,
            ..Default::default()
        };
        let keep = trusted_fix_mask(&t, &ne, None, None, &p);
        assert!(keep.iter().filter(|&&b| b).count() >= 2);
    }

    #[test]
    fn innovation_gate_rejects_pdr_inconsistent_fix() {
        let (t, mut ne) = line_north(10);
        let pdr_ne = ne.clone();
        ne[6] = [6.0, 40.0]; // 40 m off the PDR track
        let p = TrustedFixParams {
            use_innovation: true,
            max_speed_mps: 1e9,
            acc_backstop_m: None,
            lock_disp_m: 1e9,
            innovation_floor_m: 15.0,
            ..Default::default()
        };
        let keep = trusted_fix_mask(&t, &ne, None, Some((&t, &pdr_ne)), &p);
        assert!(!keep[6]);
    }

    #[test]
    fn lock_time_short_series_returns_first() {
        // n <= lock_window: cannot form a full window, so trim nothing (return gnss_t[0]).
        let t = [0.0, 1.0, 2.0];
        let ne = [[0.0, 0.0], [50.0, 0.0], [100.0, 0.0]];
        assert_eq!(lock_time(&t, &ne, 8, 5.0, 6.0, 120.0), 0.0);
    }

    #[test]
    fn lock_time_no_tight_window_falls_back() {
        // every 3-window stays wide (>5 m radius), so no lock latches: fall back to gnss_t[0].
        let t: Vec<f64> = (0..9).map(|i| i as f64).collect();
        let ne: Vec<[f64; 2]> = (0..9).map(|i| [i as f64 * 20.0, 0.0]).collect();
        assert_eq!(lock_time(&t, &ne, 3, 5.0, 6.0, 120.0), 0.0);
    }

    #[test]
    fn lock_time_aborts_scan_past_max_cold() {
        // a tight window exists only AFTER max_cold_s; the scan breaks first, so fall back to gnss_t[0].
        let t = [0.0, 1.0, 2.0, 200.0, 201.0, 202.0];
        let ne = [[0.0, 0.0], [40.0, 0.0], [80.0, 0.0], [0.1, 0.0], [0.0, 0.1], [0.1, 0.1]];
        assert_eq!(lock_time(&t, &ne, 3, 5.0, 6.0, 120.0), 0.0);
    }

    #[test]
    fn speed_keep_nonincreasing_dt_passes_through() {
        // dt <= 0 must not reject (the guard is dt > 0): a duplicate-timestamp fix is kept.
        let t = [0.0, 1.0, 1.0, 2.0];
        let ne = [[0.0, 0.0], [1.0, 0.0], [500.0, 0.0], [501.0, 0.0]];
        let keep = speed_keep(&t, &ne, 5.0, 0);
        assert!(keep.iter().all(|&b| b));
    }
}
