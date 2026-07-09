use apoc_geo::interp_ne;
use serde::Deserialize;

#[derive(Deserialize)]
struct InterpFixture {
    t_src: Vec<f64>,
    ne_src: Vec<[f64; 2]>,
    t_query: Vec<f64>,
    expected: Vec<[f64; 2]>,
}

#[test]
fn interp_ne_matches_python_oracle() {
    let raw = std::fs::read_to_string(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../oracle/fixtures/interp_ne.json"
    ))
    .expect("fixture present; run core/oracle/dump_fixtures.py");
    let f: InterpFixture = serde_json::from_str(&raw).unwrap();

    let got = interp_ne(&f.t_src, &f.ne_src, &f.t_query);
    assert_eq!(got.len(), f.expected.len());
    for (g, e) in got.iter().zip(&f.expected) {
        assert!(
            (g[0] - e[0]).abs() < 1e-9 && (g[1] - e[1]).abs() < 1e-9,
            "interp mismatch: got {:?} expected {:?}",
            g,
            e
        );
    }
}
