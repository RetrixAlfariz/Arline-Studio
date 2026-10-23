use arline_runtime::analysis::{compose_input, quality_report};

#[test]
fn all_writer_modes_have_distinct_contracts() {
    let modes = ["raw", "wcf", "wcf_raw", "smart_hybrid", "aif_core"];
    for mode in modes {
        let rendered = compose_input(
            "Write Mira",
            "FACT: Mira is here",
            mode,
            "C mira",
            "Scene goal",
            &["uncertain detail".into()],
            None,
        );
        assert!(rendered.contains("<REQUEST>"));
        if mode == "raw" {
            assert!(!rendered.contains("<ARLINE_CONTEXT>"));
        }
        if mode == "wcf" {
            assert!(rendered.contains("<ARLINE_CONTEXT>"));
        }
        if mode == "wcf_raw" {
            assert!(rendered.contains("<RAW_SOURCE>"));
        }
        if mode == "smart_hybrid" {
            assert!(rendered.contains("<UNRESOLVED_SOURCE_CONTEXT>"));
        }
        if mode == "aif_core" {
            assert!(rendered.contains("<AIF_CORE>"));
        }
    }
}

#[test]
fn quality_report_flags_adjacent_repetition() {
    let report = quality_report("Mira Mira turns");
    assert_eq!(report["valid"], false);
    assert_eq!(report["metrics"]["repetition_pairs"], 1);
}

#[test]
fn smart_hybrid_keeps_unresolved_intent_visible() {
    let rendered = compose_input(
        "question",
        "WCF",
        "smart_hybrid",
        "",
        "",
        &["what happens next".into()],
        None,
    );
    assert!(rendered.contains("what happens next"));
}
