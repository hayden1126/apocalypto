//! Offline, position-domain gate selecting trustworthy GNSS fixes for re-anchoring.
//! Ported from prototypes/pdr-benchmark/pdr_bench/pdr/trusted_fix.py (the numerical oracle).

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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn speed_keep_rejects_teleport() {
        // 10 fixes north at 1 m/s; fix 5 teleports 800 m (the ma_ling 808 m spike analogue).
        let t: Vec<f64> = (0..10).map(|i| i as f64).collect();
        let mut ne: Vec<[f64; 2]> = (0..10).map(|i| [i as f64, 0.0]).collect();
        ne[5] = [800.0, 0.0];
        let keep = speed_keep(&t, &ne, 5.0, 0);
        assert!(!keep[5]);
        for i in [0, 1, 2, 3, 4, 6, 7, 8, 9] {
            assert!(keep[i], "neighbour {i} should survive vs last accepted");
        }
    }

    #[test]
    fn lock_time_latches_after_scatter() {
        // 5 scattered fixes (radius ~30 m) then 10 tight ones (radius ~0.2 m):
        // the first tight 5-window starts at index 5, so lock latches at t = 5.
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
        let tl = lock_time(&t, &ne, 5, 5.0, 6.0, 120.0);
        assert_eq!(tl, 5.0);
    }
}
