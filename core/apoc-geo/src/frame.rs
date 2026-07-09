//! Planar geometry in a local North-East metre frame.
//! Ported from prototypes/pdr-benchmark/pdr_bench/eval/geo.py.

/// Linearly interpolate an NE track onto query times, clamped to the source range.
/// `t_src` must be strictly increasing. Mirrors `numpy.interp` per component.
///
/// # Panics
/// Panics if `t_src` (and thus `ne_src`) is empty.
pub fn interp_ne(t_src: &[f64], ne_src: &[[f64; 2]], t_query: &[f64]) -> Vec<[f64; 2]> {
    t_query
        .iter()
        .map(|&tq| [interp1(t_src, ne_src, tq, 0), interp1(t_src, ne_src, tq, 1)])
        .collect()
}

fn interp1(t: &[f64], ne: &[[f64; 2]], tq: f64, c: usize) -> f64 {
    let last = t.len() - 1;
    if tq <= t[0] {
        return ne[0][c];
    }
    if tq >= t[last] {
        return ne[last][c];
    }
    // t is strictly increasing: find lo with t[lo] <= tq < t[lo + 1].
    let (mut lo, mut hi) = (0usize, last);
    while hi - lo > 1 {
        let mid = (lo + hi) / 2;
        if t[mid] <= tq {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    let (t0, t1) = (t[lo], t[hi]);
    let (y0, y1) = (ne[lo][c], ne[hi][c]);
    let slope = (y1 - y0) / (t1 - t0);
    slope * (tq - t0) + y0
}
