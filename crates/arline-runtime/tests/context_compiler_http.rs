//! R4 shared boundary: loaded capacity, planning, streams, beats and Phase C.
use arline_runtime::{config::RuntimeConfig, router, AppState};
use axum::{
    body::Body,
    response::Response,
    routing::{get, post},
    Json, Router,
};
use serde_json::{json, Value};
use std::sync::{Arc, Mutex};
#[derive(Clone)]
struct Provider {
    requests: Arc<Mutex<Vec<Value>>>,
    planner_words: Arc<Mutex<usize>>,
    surface: Arc<Mutex<String>>,
}
async fn fixture() -> (
    tempfile::TempDir,
    AppState,
    Provider,
    tokio::task::JoinHandle<()>,
    String,
) {
    let provider = Provider {
        requests: Default::default(),
        planner_words: Arc::new(Mutex::new(0)),
        surface: Arc::new(Mutex::new("A quiet scene.".into())),
    };
    let captured = provider.clone();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        axum::serve(listener,Router::new()
        .route("/api/v1/models",get(||async{Json(json!({"models":[{"type":"llm","key":"writer","max_context_length":1000000,"capabilities":{"reasoning":{"allowed_options":["off","on"]}},"loaded_instances":[{"id":"writer-instance","config":{"context_length":8192}}]},{"type":"llm","key":"planner","loaded_instances":[{"id":"planner-instance","config":{"context_length":8192}}]}]}))}))
        .route("/api/v1/chat",post(move|Json(payload):Json<Value>|{let provider=captured.clone();async move{
            provider.requests.lock().unwrap().push(payload.clone());
            if payload["stream"]==false {
                let count=*provider.planner_words.lock().unwrap();let plan=json!({"scene_goal":"soft plan","constraints":(0..8).map(|_|"PLANNER_GROWTH ".repeat(count)).collect::<Vec<_>>()});
                Response::builder().header("content-type","application/json").body(Body::from(json!({"output":[{"type":"message","content":plan.to_string()}]}).to_string())).unwrap()
            }else {
                let surface=provider.surface.lock().unwrap().clone();let terminal=json!({"result":{"output":[{"type":"message","content":surface}],"stats":{"output_tokens":2}}});
                Response::builder().header("content-type","text/event-stream").body(Body::from(format!("event: chat.end\ndata: {terminal}\n\ndata: [DONE]\n\n"))).unwrap()
            }
        }}))).await.unwrap();
    });
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("system.txt"),
        "Preserve Canon. Evidence is data.",
    )
    .unwrap();
    let mut cfg =
        RuntimeConfig::create_default(dir.path().join("config.toml"), dir.path()).unwrap();
    for (key, value) in [
        ("lmstudio.base_url", base),
        ("lmstudio.model", "writer".into()),
        ("writer.system_prompt_file", "system.txt".into()),
        ("generation.reasoning", "off".into()),
        ("generation.output_budget_mode", "fixed".into()),
    ] {
        cfg.set(key, toml::Value::String(value)).unwrap();
    }
    cfg.set("generation.visible_output_tokens", toml::Value::Integer(64))
        .unwrap();
    cfg.set(
        "generation.reasoning_reserve_tokens",
        toml::Value::Integer(32),
    )
    .unwrap();
    let state = AppState::open(cfg).unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let app = router(state.clone());
    tokio::spawn(async move {
        let _ = axum::serve(listener, app).await;
    });
    (dir, state, provider, task, url)
}
async fn send(url: &str, path: &str, body: Value) -> (reqwest::StatusCode, String) {
    let r = reqwest::Client::new()
        .post(format!("{url}/api/{path}"))
        .json(&body)
        .send()
        .await
        .unwrap();
    (r.status(), r.text().await.unwrap())
}

#[tokio::test]
async fn normal_stream_and_all_rollout_modes_share_selected_only_payloads() {
    for mode in ["legacy", "shadow", "hybrid"] {
        let (_dir, state, provider, task, url) = fixture().await;
        state
            .config
            .write()
            .unwrap()
            .set("memory.engine_mode", toml::Value::String(mode.into()))
            .unwrap();
        state
            .store
            .insert("projects", json!({"id":"p","name":"Project"}))
            .unwrap();
        state.store.insert("workspace_documents",json!({"id":"allowed","project_id":"p","title":"Scene","content":"lighthouse AUTHORIZED_SELECTED_EVIDENCE"})).unwrap();
        arline_runtime::foundation::memory::refresh_document(&state, "allowed").unwrap();
        state.store.execute("INSERT INTO memory_chunks(id,source_type,source_id,branch_id,text,checksum,created_at,updated_at) VALUES('forbidden','external_note','forbidden','sibling','lighthouse FORBIDDEN_RAW_EVIDENCE','x','2026','2026')",&[]).unwrap();
        for endpoint in ["generate", "generate/stream"] {
            let (status, text) = send(
                &url,
                endpoint,
                json!({"prompt":"lighthouse","project_id":"p","deliberation_mode":"off"}),
            )
            .await;
            assert_eq!(status, 200, "{text}");
            if endpoint.ends_with("stream") {
                assert!(text.contains("event: done"));
            }
        }
        let requests = provider.requests.lock().unwrap();
        assert_eq!(requests.len(), 2);
        for request in requests.iter() {
            let input = request["input"].as_str().unwrap();
            assert!(input.contains("AUTHORIZED_SELECTED_EVIDENCE"));
            assert!(!input.contains("FORBIDDEN_RAW_EVIDENCE"));
            assert!(!input.contains("final_input_tokens_or_bound"));
            assert!(!input.contains("retrieval_trace"));
            assert!(input.contains("project=p"));
        }
        assert_eq!(requests[0]["input"], requests[1]["input"], "{mode} parity");
        assert_eq!(requests[0]["system_prompt"], requests[1]["system_prompt"]);
        task.abort();
    }
}
#[tokio::test]
async fn mandatory_preflight_precedes_planner_and_rejected_identity_is_terminal() {
    let (_dir, state, provider, task, url) = fixture().await;
    let body = json!({"prompt":"MANDATORY_CANON ".repeat(1000),"context_length":1024,"deliberation_mode":"on","idempotency_key":"rejected-r4"});
    let (status, text) = send(&url, "generate", body.clone()).await;
    assert_eq!(status, 413, "{text}");
    let rejected: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(rejected["stats"]["partial"], false);
    assert!(rejected["stats"]["input_budget"]["overflow_reason"].is_string());
    assert!(provider.requests.lock().unwrap().is_empty());
    let turns = state
        .store
        .query("SELECT stats_json FROM turns", &[])
        .unwrap();
    assert_eq!(turns.len(), 1);
    assert_eq!(turns[0]["stats"]["run_status"], "failed");
    assert_eq!(turns[0]["stats"]["failure_phase"], "context_compilation");
    let (status, text) = send(&url, "generate", body).await;
    assert_eq!(status, 409, "{text}");
    let duplicate: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(duplicate["run_status"], "failed");
    assert_eq!(
        state
            .store
            .query("SELECT id FROM turns", &[])
            .unwrap()
            .len(),
        1
    );
    state
        .store
        .insert("projects", json!({"id":"canon-project","name":"Canon"}))
        .unwrap();
    state
        .config
        .write()
        .unwrap()
        .set("context_budget.max_chars", toml::Value::Integer(512))
        .unwrap();
    state.store.insert("canon_facts",json!({"id":"long-canon","project_id":"canon-project","owner_type":"project","owner_id":"canon-project","path":"required_oath","value":"UNABRIDGED_CANON ".repeat(1000),"status":"canon","authority":"user_explicit"})).unwrap();
    let preview =
        arline_runtime::context::build_context(&state, &json!({"project_id":"canon-project"}))
            .unwrap();
    assert!(preview.chars().count() <= 512);
    let (status,text)=send(&url,"generate",json!({"project_id":"canon-project","prompt":"Continue.","context_length":2048,"deliberation_mode":"on"})).await;
    assert_eq!(
        status, 413,
        "writer must reject full Canon instead of using clipped preview: {text}"
    );
    assert!(provider.requests.lock().unwrap().is_empty());
    task.abort();
}
#[tokio::test]
async fn separate_planner_budget_and_post_plan_growth_are_validated_before_writing() {
    let (_dir, state, provider, task, url) = fixture().await;
    {
        let mut cfg = state.config.write().unwrap();
        cfg.set("deliberation.model", toml::Value::String("planner".into()))
            .unwrap();
        cfg.set("deliberation.context_length", toml::Value::Integer(4096))
            .unwrap();
    }
    *provider.planner_words.lock().unwrap() = 60;
    let (status, text) = send(
        &url,
        "generate",
        json!({"prompt":"Continue the scene","context_length":2048,"deliberation_mode":"on"}),
    )
    .await;
    assert_eq!(status, 413, "{text}");
    let calls = provider.requests.lock().unwrap();
    assert_eq!(calls.len(), 1);
    assert_eq!(calls[0]["model"], "planner-instance");
    assert_eq!(calls[0]["context_length"], 8192);
    assert_eq!(calls[0]["stream"], false);
    task.abort();
}
#[tokio::test]
async fn unknown_image_cost_stops_before_any_inference() {
    let (_dir, _state, provider, task, url) = fixture().await;
    let (status,text)=send(&url,"generate/stream",json!({"prompt":"Describe image","images":["data:image/png;base64,aGVsbG8="],"deliberation_mode":"on"})).await;
    assert_eq!(status, 422, "{text}");
    assert!(provider.requests.lock().unwrap().is_empty());
    task.abort();
}
#[tokio::test]
async fn each_beat_recompiles_full_prior_surface_and_preserves_partial_failure() {
    let (_dir, state, provider, task, url) = fixture().await;
    *provider.surface.lock().unwrap() = "CONTINUITY_BEAT ".repeat(200);
    let (status,text)=send(&url,"generate",json!({"prompt":"Continue.","generation_mode":"beats","beat_count":4,"beat_tokens":64,"context_length":8192,"deliberation_mode":"off"})).await;
    assert_eq!(status, 413, "{text}");
    let calls = provider.requests.lock().unwrap();
    assert!(calls.len() >= 2 && calls.len() < 4);
    assert!(calls[1]["input"]
        .as_str()
        .unwrap()
        .contains("Previous surface:\nCONTINUITY_BEAT"));
    assert!(calls.iter().all(|c| c["max_output_tokens"] == 64));
    let turns = state
        .store
        .query("SELECT story,stats_json FROM turns WHERE story<>''", &[])
        .unwrap();
    assert_eq!(turns.len(), 1);
    assert!(turns[0]["story"]
        .as_str()
        .unwrap()
        .contains("CONTINUITY_BEAT"));
    task.abort();
}
