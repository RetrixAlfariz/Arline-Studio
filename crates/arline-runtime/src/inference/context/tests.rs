use super::*;
use axum::{routing::get, Router};
use std::sync::{Arc, Mutex};
async fn fixture(
    window: u64,
) -> (
    tempfile::TempDir,
    AppState,
    Arc<Mutex<Value>>,
    tokio::task::JoinHandle<()>,
) {
    let loaded = Arc::new(Mutex::new(
        json!({"models":[{"type":"llm","key":"writer","max_context_length":1000000,"loaded_instances":[{"id":"instance","config":{"context_length":window}}]}]}),
    ));
    let copy = loaded.clone();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        axum::serve(
            listener,
            Router::new().route(
                "/api/v1/models",
                get(move || {
                    let data = copy.clone();
                    async move { axum::Json(data.lock().unwrap().clone()) }
                }),
            ),
        )
        .await
        .unwrap();
    });
    let dir = tempfile::tempdir().unwrap();
    let mut cfg =
        RuntimeConfig::create_default(dir.path().join("config.toml"), dir.path()).unwrap();
    cfg.set("lmstudio.base_url", toml::Value::String(base))
        .unwrap();
    cfg.set("lmstudio.model", toml::Value::String("writer".into()))
        .unwrap();
    (dir, AppState::open(cfg).unwrap(), loaded, task)
}
fn selection() -> ContextSelection {
    let body = json!({"prompt":"Continue without changing Canon","project_id":"p"});
    ContextSelection::from_analysis(
        &body,
        &json!({"wcf":"MANDATORY_CANON","memory":[],"deliberation":{"status":"disabled"}}),
        vec![],
    )
}
fn payload(text: &str) -> Value {
    json!({"model":"writer","system_prompt":"Authoritative system.","input":text,"reasoning":"off","max_output_tokens":64})
}

#[tokio::test]
async fn loaded_capacity_is_authoritative_and_resize_reload_ambiguity_fail_closed() {
    let (_dir, state, info, task) = fixture(2048).await;
    let cfg = state.runtime_config().unwrap();
    let body = json!({"model":"writer","context_length":1000000});
    let counter = WriterTokenCounter::resolve(&state, &cfg, &body)
        .await
        .unwrap();
    assert_eq!(counter.model.context_length, 2048);
    info.lock().unwrap()["models"][0]["loaded_instances"][0]["remaining_ttl_seconds"] = json!(99);
    assert!(
        counter.confirm(&state, &cfg, &body).await.is_ok(),
        "TTL countdown is not model identity"
    );
    info.lock().unwrap()["models"][0]["loaded_instances"][0]["config"]["context_length"] =
        json!(1024);
    assert!(counter.confirm(&state, &cfg, &body).await.is_err());
    let counter = WriterTokenCounter::resolve(&state, &cfg, &json!({"context_length":512}))
        .await
        .unwrap();
    assert_eq!(counter.model.context_length, 512);
    info.lock().unwrap()["models"][0]["loaded_instances"][0]["id"] = json!("reloaded-instance");
    assert!(counter
        .confirm(&state, &cfg, &json!({"context_length":512}))
        .await
        .is_err());
    info.lock().unwrap()["models"][0]["loaded_instances"]
        .as_array_mut()
        .unwrap()
        .push(json!({"id":"duplicate","config":{"context_length":1024}}));
    assert!(WriterTokenCounter::resolve(&state, &cfg, &body)
        .await
        .is_err());
    info.lock().unwrap()["models"][0]["loaded_instances"] = json!([]);
    assert!(WriterTokenCounter::resolve(&state, &cfg, &body)
        .await
        .is_err());
    task.abort();
}
#[tokio::test]
async fn utf8_estimates_and_unknown_images_are_explicit() {
    let (_dir, state, _info, task) = fixture(32768).await;
    let cfg = state.runtime_config().unwrap();
    let mut counter = WriterTokenCounter::resolve(&state, &cfg, &json!({}))
        .await
        .unwrap();
    let corpus: Value =
        serde_json::from_str(include_str!("../../../tests/fixtures/context_r4.json")).unwrap();
    for case in corpus["cases"].as_array().unwrap() {
        let p = payload(case["input"].as_str().unwrap());
        let count = counter.count(&p).await.unwrap();
        assert_eq!(count.state, AccountingState::ConservativeEstimated);
        assert!(count.tokens >= p.to_string().len() as u64);
    }
    let error = counter
        .count(&json!({"input":[{"type":"image","data_url":"data:image/png;base64,abc"}]}))
        .await
        .unwrap_err();
    assert_eq!(error.status, StatusCode::UNPROCESSABLE_ENTITY);
    task.abort();
}
#[tokio::test]
async fn mandatory_overflow_preserves_authority_and_diagnostics_hide_text() {
    let (_dir, state, _info, task) = fixture(1024).await;
    let cfg = state.runtime_config().unwrap();
    let mut selection = selection();
    selection.wcf = "PRIVATE_CANON ".repeat(200);
    let error = compile(&state, &cfg, &json!({}), &selection, 64, payload)
        .await
        .unwrap_err();
    assert_eq!(error.status, StatusCode::PAYLOAD_TOO_LARGE);
    assert!(!error.message.contains("PRIVATE_CANON"));
    let diagnostic = error.diagnostic.as_ref().unwrap();
    assert_eq!(diagnostic["context_window"], 1024);
    assert!(diagnostic["overflow_reason"].is_string());
    assert!(!diagnostic.to_string().contains("PRIVATE_CANON"));
    let locked = json!({"locked":[{"label":"required","value":"LOCKED_RULE ".repeat(5000)}]});
    let full = crate::analysis::wcf::render_for_writer(&locked);
    assert_eq!(full["metadata"]["pruned"], false);
    assert_eq!(
        full["text"]
            .as_str()
            .unwrap()
            .matches("LOCKED_RULE")
            .count(),
        5000
    );
    assert_eq!(
        crate::analysis::wcf::render(&locked)["metadata"]["pruned"],
        true,
        "preview policy remains bounded"
    );
    task.abort();
}
#[tokio::test]
async fn allocator_keeps_selected_order_and_whole_history_turns_and_accumulates_decisions() {
    let (_dir, state, info, task) = fixture(3500).await;
    let cfg = state.runtime_config().unwrap();
    let mut selection = selection();
    selection.evidence=(0..6).map(|i|json!({"id":format!("e{i}"),"source_id":format!("doc{i}"),"source_type":"document","source_revision":"rev1","authority":"project_manuscript","trust_level":"trusted_local","text":format!("EVIDENCE_{i} {}", "x".repeat(700))})).collect();
    selection.history = vec![
        HistoryTurn {
            id: "old".into(),
            user: "old question".into(),
            assistant: "OLD_COMPLETE_TURN".into(),
        },
        HistoryTurn {
            id: "recent".into(),
            user: "new question".into(),
            assistant: "RECENT_COMPLETE_TURN".into(),
        },
    ];
    let compiled = compile(&state, &cfg, &json!({}), &selection, 64, payload)
        .await
        .unwrap();
    let kept = compiled.evidence.len();
    assert!(kept < 6 && kept > 0);
    assert!(compiled.context.contains("RECENT_COMPLETE_TURN"));
    assert_eq!(compiled.report["history_turns_dropped"], 0);
    assert_eq!(compiled.evidence[0]["id"], "e0");
    assert_eq!(compiled.evidence[0]["source_revision"], "rev1");
    assert!(!compiled.report.to_string().contains("EVIDENCE_5"));
    assert!(compiled.report["items"][0]["token_cost"].is_object());
    info.lock().unwrap()["models"][0]["loaded_instances"][0]["config"]["context_length"] =
        json!(1500);
    let smaller = compile(&state, &cfg, &json!({}), &compiled.selection, 64, payload)
        .await
        .unwrap();
    assert!(
        smaller.report["memory_items_dropped"].as_u64().unwrap()
            >= compiled.report["memory_items_dropped"].as_u64().unwrap()
    );
    assert!(
        smaller.report["final_input_tokens_or_bound"]
            .as_u64()
            .unwrap()
            + 64
            + smaller.report["safety_margin_tokens"].as_u64().unwrap()
            <= 1500
    );
    // History, when removed, is removed as a turn rather than a string suffix.
    let mut long = selection.clone();
    long.evidence.clear();
    long.history[0].assistant = "OLD_LONG ".repeat(300);
    let trimmed = compile(&state, &cfg, &json!({}), &long, 64, payload)
        .await
        .unwrap();
    assert!(!trimmed.context.contains("OLD_LONG"));
    assert!(trimmed.context.contains("RECENT_COMPLETE_TURN"));
    assert_eq!(trimmed.report["history_turns_dropped"], 1);
    let mut mixed = selection.clone();
    mixed.history.clear();
    mixed.evidence = vec![
        json!({"id":"oversized","source_id":"big","source_type":"document","text":"x".repeat(10000)}),
        json!({"id":"short","source_id":"small","source_type":"document","text":"KEEP_COMPLETE_SHORT_PASSAGE","source_revision":"rev-small"}),
    ];
    let packed = compile(&state, &cfg, &json!({}), &mixed, 64, payload)
        .await
        .unwrap();
    assert_eq!(packed.evidence.len(), 1);
    assert_eq!(packed.evidence[0]["id"], "short");
    assert_eq!(packed.evidence[0]["source_revision"], "rev-small");
    assert!(packed.context.contains("KEEP_COMPLETE_SHORT_PASSAGE"));
    task.abort();
}
#[tokio::test]
async fn raw_results_exclusions_and_planner_debug_never_enter_writer_input() {
    let (_dir, state, _info, task) = fixture(32768).await;
    let cfg = state.runtime_config().unwrap();
    let body = json!({"prompt":"Continue"});
    let analysis = json!({"wcf":"CANON","memory":[],"results":[{"text":"FORBIDDEN_RAW"}],"excluded":[{"text":"FORBIDDEN_EXCLUDED"}],"deliberation":{"status":"model","authority":"soft_non_canon","result":{"scene_goal":"KEEP_GOAL"},"input_budget":{"private":"BUDGET_DEBUG"},"routing":{"private":"ROUTING_DEBUG"}}});
    let selection = ContextSelection::from_analysis(&body, &analysis, vec![]);
    let compiled = compile(&state, &cfg, &body, &selection, 64, payload)
        .await
        .unwrap();
    assert!(compiled.context.contains("KEEP_GOAL"));
    for forbidden in [
        "FORBIDDEN_RAW",
        "FORBIDDEN_EXCLUDED",
        "BUDGET_DEBUG",
        "ROUTING_DEBUG",
    ] {
        assert!(!compiled.context.contains(forbidden));
    }
    let same = compile(&state, &cfg, &body, &compiled.selection, 64, payload)
        .await
        .unwrap();
    assert_eq!(compiled.payload, same.payload);
    task.abort();
}
