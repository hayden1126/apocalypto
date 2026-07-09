use apoc_positioning::gnss_gate::{trusted_fix_mask, TrustedFixParams};
use serde::Deserialize;

#[derive(Deserialize)]
struct Params {
    max_speed_mps: f64,
    lock_window: usize,
    lock_disp_m: f64,
    acc_backstop_m: f64,
}

#[derive(Deserialize)]
struct MaskFixture {
    gnss_t: Vec<f64>,
    gnss_ne: Vec<[f64; 2]>,
    reported_acc_m: Vec<f64>,
    params: Params,
    expected_mask: Vec<bool>,
}

#[test]
fn trusted_fix_mask_matches_python_oracle() {
    let raw = std::fs::read_to_string(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../oracle/fixtures/trusted_fix_mask.json"
    ))
    .expect("fixture present; run core/oracle/dump_fixtures.py");
    let f: MaskFixture = serde_json::from_str(&raw).unwrap();

    let p = TrustedFixParams {
        max_speed_mps: f.params.max_speed_mps,
        lock_window: f.params.lock_window,
        lock_disp_m: f.params.lock_disp_m,
        acc_backstop_m: Some(f.params.acc_backstop_m),
        ..Default::default()
    };
    let got = trusted_fix_mask(&f.gnss_t, &f.gnss_ne, Some(&f.reported_acc_m), None, &p);
    assert_eq!(got, f.expected_mask);
}
