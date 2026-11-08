//! ARLINE-O01 Phase A–C: retrieval/context integrity, durable generation
//! lifecycle, and request identity (INF-10).
use arline_runtime::{config::RuntimeConfig, router, AppState};
use axum::{body::Body, http::StatusCode, response::Response, routing::post, Router};
use futures_util::StreamExt;
use serde_json::{json, Value};
use std::{
    future::IntoFuture,
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::{net::TcpListener, task::JoinHandle};

type Captured = Arc<Mutex<Vec<Value>>>;

/// Mock LM Studio: records payloads, streams `deltas`, then ends or hangs.
async fn provider(
    deltas: &'static [&'static str],
    hold: bool,
    delay_ms: u64,
) -> (String, Captured, JoinHandle<()>) {
    let captured: Captured = Arc::new(Mutex::new(Vec::new()));
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let handler = captured.clone();
    let task = tokio::spawn(async move {
        let app = Router::new().route("/api/v1/models", axum::routing::get(||async {axum::Json(json!({"models":[{"type":"llm","key":"mock","capabilities":{"reasoning":{"allowed_options":["off","on"]}},"loaded_instances":[{"id":"mock","config":{"context_length":32768}}]}]}))})).route(
            "/api/v1/chat",
            post(move |axum::Json(payload): axum::Json<Value>| {
                let captured = handler.clone();
                async move {
                    let planner = payload["stream"] == false;
                    captured.lock().unwrap().push(payload);
                    if planner {
                        return Response::builder().header("content-type", "application/json").body(Body::from(json!({"output":[{"type":"message","content":"{\"scene_goal\":\"plan\"}"}]}).to_string())).unwrap();
                    }
                    tokio::time::sleep(Duration::from_millis(delay_ms)).await;
                    let stream = async_stream::stream! {
                        for delta in deltas {
                            yield Ok::<_, std::convert::Infallible>(format!("event: message\ndata: {{\"type\":\"message.delta\",\"content\":\"{delta}\"}}\n\n"));
                        }
                        if hold {
                            std::future::pending::<()>().await;
                        }
                        let all = deltas.concat();
                        yield Ok(format!("event: chat.end\ndata: {{\"result\":{{\"output\":[{{\"type\":\"message\",\"content\":\"{all}\"}}]}}}}\n\ndata: [DONE]\n\n"));
                    };
                    Response::builder().header("content-type", "text/event-stream").body(Body::from_stream(stream)).unwrap()
                }
            }),
        );
        let _ = axum::serve(listener, app).into_future().await;
    });
    (base, captured, task)
}

fn open_state(dir: &std::path::Path, base_url: &str) -> AppState {
    std::fs::write(dir.join("writer_system.txt"), "System.").unwrap();
    let config_path = dir.join("config.toml");
    std::fs::write(&config_path, format!(
        "[lmstudio]\nbase_url = \"{base_url}\"\nmodel = \"mock\"\ntimeout_seconds = 10.0\n[generation]\nreasoning = \"off\"\nvisible_output_tokens = 64\nreasoning_reserve_tokens = 64\n[writer]\nsystem_prompt_file = \"writer_system.txt\"\n[workspace]\ndatabase_path = \"data/history.db\"\n"
    )).unwrap();
    AppState::open(RuntimeConfig::load(&config_path, dir).unwrap()).unwrap()
}

async fn serve(state: &AppState) -> (String, JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let app = router(state.clone());
    (
        url,
        tokio::spawn(async move {
            let _ = axum::serve(listener, app).into_future().await;
        }),
    )
}

fn writer_inputs(captured: &Captured) -> Vec<String> {
    captured
        .lock()
        .unwrap()
        .iter()
        .filter(|p| p["stream"] == true)
        .map(|p| p["input"].as_str().unwrap_or_default().to_owned())
        .collect()
}

/// 30 matching documents, each with a unique marker, all in one project.
fn seed_evidence(state: &AppState) {
    state
        .store
        .insert("projects", json!({"id":"o01","name":"O01"}))
        .unwrap();
    for i in 0..30 {
        let doc = state.store.insert("workspace_documents", json!({"project_id":"o01","title":format!("Doc {i}"),"content":format!("sapphire evidence OPAL_{i:02} lantern")})).unwrap();
        arline_runtime::foundation::memory::refresh_document(state, doc["id"].as_str().unwrap())
            .unwrap();
    }
}

fn seed_session(state: &AppState, id: &str) {
    state
        .store
        .insert(
            "sessions",
            json!({"id":id,"title":"O01","project_id":"o01"}),
        )
        .unwrap();
    state
        .store
        .insert(
            "turns",
            json!({"session_id":id,"user_prompt":"Earlier","story":"HISTORY_MARKER_LATEST"}),
        )
        .unwrap();
}

#[tokio::test]
async fn writer_receives_only_selected_compact_evidence() {
    let (base, captured, provider_task) = provider(&["Fresh prose."], false, 0).await;
    let temp = tempfile::tempdir().unwrap();
    let state = open_state(temp.path(), &base);
    seed_evidence(&state);
    let (url, task) = serve(&state).await;
    let response = reqwest::Client::new()
        .post(format!("{url}/api/generate"))
        .json(&json!({"project_id":"o01","prompt":"sapphire"}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let input = writer_inputs(&captured).pop().unwrap();
    let lines = input.lines().filter(|l| l.starts_with("MEMORY [")).count();
    let markers = (0..30)
        .filter(|i| input.contains(&format!("OPAL_{i:02}")))
        .count();
    // memory.final_k defaults to 12; 18 candidates must never reach the prompt.
    assert_eq!(lines, 12, "{input}");
    assert_eq!(
        markers, 12,
        "excluded evidence leaked into the writer prompt"
    );
    assert!(
        input.contains("MEMORY [document:"),
        "provenance missing: {input}"
    );
    for diagnostic in ["dense_score", "\"importance\"", "checksum", "index_state"] {
        assert!(
            !input.contains(diagnostic),
            "diagnostic {diagnostic} leaked into prompt"
        );
    }
    task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn input_budget_drops_memory_before_history_and_rejects_oversized_core() {
    let (base, captured, provider_task) = provider(&["Fresh prose."], false, 0).await;
    let temp = tempfile::tempdir().unwrap();
    let state = open_state(temp.path(), &base);
    seed_evidence(&state);
    for id in ["roomy", "tight", "tiny"] {
        seed_session(&state, id);
    }
    let (url, task) = serve(&state).await;
    let client = reqwest::Client::new();
    let run = |session: &str, window: u64| {
        client.post(format!("{url}/api/generate")).json(&json!({"session_id":session,"project_id":"o01","prompt":"sapphire","context_length":window})).send()
    };
    let roomy: Value = run("roomy", 32768).await.unwrap().json().await.unwrap();
    let budget = &roomy["stats"]["input_budget"];
    assert_eq!(budget["memory_items_dropped"], 0, "{budget}");
    let estimate = budget["estimated_input_tokens"].as_u64().unwrap();
    let overhead = budget["output_reserve_tokens"].as_u64().unwrap()
        + budget["system_prompt_tokens"].as_u64().unwrap();

    // Squeeze 60 tokens out: some memory must go, history must survive.
    let tight: Value = run("tight", overhead + estimate - 60)
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    let budget = &tight["stats"]["input_budget"];
    let dropped = budget["memory_items_dropped"].as_u64().unwrap();
    assert!(dropped >= 1, "{budget}");
    assert_eq!(budget["history_bytes_dropped"], 0, "{budget}");
    assert!(
        budget["estimated_input_tokens"].as_u64().unwrap()
            <= budget["input_limit_tokens"].as_u64().unwrap()
    );
    let input = writer_inputs(&captured).pop().unwrap();
    assert!(input.contains("HISTORY_MARKER_LATEST"));
    assert!(input.contains("<ARLINE_CONTEXT>") && input.contains("<REQUEST>"));
    assert_eq!(
        input.lines().filter(|l| l.starts_with("MEMORY [")).count() as u64,
        12 - dropped
    );

    let writer_calls = writer_inputs(&captured).len();
    let tiny = run("tiny", overhead + 10).await.unwrap();
    assert_eq!(tiny.status(), StatusCode::PAYLOAD_TOO_LARGE);
    assert_eq!(
        writer_inputs(&captured).len(),
        writer_calls,
        "oversized input reached the writer"
    );
    task.abort();
    provider_task.abort();
}

/// Guard the shared boundary independently of the default 12-result fixture.
/// A zero budget must not leak candidate text through any generation route.
#[tokio::test]
async fn selected_only_handoff_obeys_saved_limits_on_all_generation_paths() {
    for (endpoint, mode, limit, pack_tokens, expected) in [
        ("generate", "single", 3, 4096, 3),
        ("generate/stream", "single", 3, 4096, 3),
        ("generate", "beats", 3, 4096, 3),
        ("generate", "single", 3, 0, 0),
        ("generate/stream", "single", 3, 0, 0),
        ("generate", "beats", 3, 0, 0),
    ] {
        let (base, captured, provider_task) = provider(&["Fresh prose."], false, 0).await;
        let temp = tempfile::tempdir().unwrap();
        let state = open_state(temp.path(), &base);
        {
            let mut config = state.config.write().unwrap();
            config
                .set("memory.final_k", toml::Value::Integer(limit))
                .unwrap();
            config
                .set("memory.max_pack_tokens", toml::Value::Integer(pack_tokens))
                .unwrap();
        }
        seed_evidence(&state);
        let (url, task) = serve(&state).await;
        let response = reqwest::Client::new()
            .post(format!("{url}/api/{endpoint}"))
            .json(&json!({"project_id":"o01","prompt":"sapphire","generation_mode":mode,"beat_count":2,"deliberation_mode":"off"}))
            .send().await.unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        // Drain SSE as well as JSON so completion/persistence finishes before inspection.
        let response_text = response.text().await.unwrap();
        if endpoint.ends_with("stream") {
            assert!(response_text.contains("event: done"), "{response_text}");
        }
        let inputs = writer_inputs(&captured);
        assert_eq!(inputs.len(), if mode == "beats" { 2 } else { 1 });
        for input in inputs {
            assert_eq!(
                input
                    .lines()
                    .filter(|line| line.starts_with("MEMORY ["))
                    .count(),
                expected,
                "{endpoint}/{mode}, budget={pack_tokens}: {input}"
            );
            assert_eq!(
                (0..30)
                    .filter(|i| input.contains(&format!("OPAL_{i:02}")))
                    .count(),
                expected,
                "excluded candidates reached {endpoint}/{mode}"
            );
        }
        task.abort();
        provider_task.abort();
    }
}

/// R3 shares Phase A's boundary across all rollout modes and writer paths.
#[tokio::test]
async fn r3_modes_keep_forbidden_evidence_and_ranking_out_of_all_writer_paths() {
    for engine in ["legacy", "shadow", "hybrid"] {
        for (endpoint, mode) in [("generate", "single"), ("generate/stream", "single"), ("generate", "beats")] {
            let (base, captured, provider_task) = provider(&["Fresh prose."], false, 0).await;
            let temp = tempfile::tempdir().unwrap();
            let state = open_state(temp.path(), &base);
            state.config.write().unwrap().set("memory.engine_mode", toml::Value::String(engine.into())).unwrap();
            seed_evidence(&state);
            state.store.connection().unwrap().execute("INSERT INTO memory_chunks(id,source_type,source_id,branch_id,text,checksum,created_at,updated_at) VALUES('forbidden-r3','external_note','forbidden-r3','sibling','sapphire FORBIDDEN_R3_SECRET','x','2026','2026')",[]).unwrap();
            let (url, task) = serve(&state).await;
            let response = reqwest::Client::new().post(format!("{url}/api/{endpoint}"))
                .json(&json!({"project_id":"o01","prompt":"sapphire","generation_mode":mode,"beat_count":2,"deliberation_mode":"off"}))
                .send().await.unwrap();
            assert_eq!(response.status(), StatusCode::OK);
            let text=response.text().await.unwrap();
            if endpoint.ends_with("stream") {assert!(text.contains("event: done"));}
            let inputs=writer_inputs(&captured);
            assert_eq!(inputs.len(),if mode=="beats"{2}else{1});
            for input in inputs {
                assert!(!input.contains("FORBIDDEN_R3_SECRET"),"{engine}/{endpoint}");
                assert!(!input.contains("fusion_score"));assert!(!input.contains("retrieval_trace"));assert!(!input.contains("shadow_trace"));
                assert!(input.contains("MEMORY ["));
            }
            task.abort();provider_task.abort();
        }
    }
}

#[cfg(feature="native-bekko")]
#[tokio::test]
#[ignore="requires provisioned Bekko and ONNX Runtime; run with --test-threads=1"]
async fn r3_native_index_reaches_normal_streaming_and_beat_writers() {
    use arline_runtime::foundation::memory::{self,embedding::BekkoConfig,semantic_index::{index_pending,IndexScope}};
    for (endpoint,mode) in [("generate","single"),("generate/stream","single"),("generate","beats")] {
        let (base,captured,provider_task)=provider(&["Fresh prose."],false,0).await;
        let temp=tempfile::tempdir().unwrap();let state=open_state(temp.path(),&base);
        {
            let mut cfg=state.config.write().unwrap();
            for (key,value) in [("memory.engine_mode","hybrid".to_owned()),("memory.embedding.backend","native_bekko_onnx".into()),("memory.embedding.model_dir",std::env::var("ARLINE_BEKKO_MODEL_DIR").unwrap()),("memory.embedding.runtime_library",std::env::var("ARLINE_ONNX_RUNTIME").unwrap())] {cfg.set(key,toml::Value::String(value)).unwrap();}
            cfg.set("memory.embedding.enabled",toml::Value::Boolean(true)).unwrap();
        }
        state.store.insert("projects",json!({"id":"o01","name":"R3 native"})).unwrap();
        state.store.insert("workspace_documents",json!({"id":"native-r3","project_id":"o01","title":"Nafila","content":"Nafila purchased medicine at the pharmacy for her sick brother. NATIVE_R3_EVIDENCE"})).unwrap();
        memory::refresh_document(&state,"native-r3").unwrap();
        let config=BekkoConfig::from_runtime(&state.runtime_config().unwrap()).unwrap();
        let indexed=index_pending(state.clone(),config,IndexScope{project_id:Some("o01".into()),..Default::default()},32).await.unwrap();assert_eq!(indexed["status"],"completed","{indexed}");
        let (url,task)=serve(&state).await;
        let response=reqwest::Client::new().post(format!("{url}/api/{endpoint}"))
            .json(&json!({"project_id":"o01","prompt":"Siapa membeli obat?","generation_mode":mode,"beat_count":2,"deliberation_mode":"off"})).send().await.unwrap();
        assert_eq!(response.status(),StatusCode::OK);let text=response.text().await.unwrap();if endpoint.ends_with("stream"){assert!(text.contains("event: done"));}
        let inputs=writer_inputs(&captured);assert_eq!(inputs.len(),if mode=="beats"{2}else{1});
        for input in inputs{assert!(input.contains("NATIVE_R3_EVIDENCE"),"{endpoint}/{mode}: {input}");assert!(!input.contains("fusion_score"));}
        task.abort();provider_task.abort();state.embeddings.unload().await.unwrap();
    }
}

fn turn_for(state: &AppState, session: &str) -> Value {
    state
        .store
        .list("turns", &[("session_id", json!(session))])
        .unwrap()
        .pop()
        .unwrap()
}

#[tokio::test]
async fn done_is_sent_only_after_completed_status_is_committed() {
    let (base, _captured, provider_task) = provider(&["first"], false, 0).await;
    let temp = tempfile::tempdir().unwrap();
    let state = open_state(temp.path(), &base);
    let (url, task) = serve(&state).await;
    let response = reqwest::Client::new()
        .post(format!("{url}/api/generate/stream"))
        .json(&json!({"session_id":"ok","prompt":"Begin."}))
        .send()
        .await
        .unwrap();
    let mut bytes = response.bytes_stream();
    let mut seen = String::new();
    while !seen.contains("event: done") {
        seen.push_str(&String::from_utf8_lossy(
            &bytes
                .next()
                .await
                .expect("stream ended before done")
                .unwrap(),
        ));
    }
    let turn = turn_for(&state, "ok");
    assert_eq!(turn["stats"]["run_status"], "completed");
    assert_eq!(turn["story"], "first");
    task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn database_failure_at_commit_reports_error_instead_of_done() {
    let (base, _captured, provider_task) = provider(&["first"], false, 0).await;
    let temp = tempfile::tempdir().unwrap();
    let state = open_state(temp.path(), &base);
    // Fault injection: the commit write (status -> completed) fails like a full disk.
    state.store.connection().unwrap().execute_batch("CREATE TRIGGER o01_fail_commit BEFORE UPDATE OF stats_json ON turns WHEN json_extract(NEW.stats_json,'$.run_status')='completed' BEGIN SELECT RAISE(ABORT,'database or disk is full'); END;").unwrap();
    let (url, task) = serve(&state).await;
    let text = reqwest::Client::new()
        .post(format!("{url}/api/generate/stream"))
        .json(&json!({"session_id":"fault","prompt":"Begin."}))
        .send()
        .await
        .unwrap()
        .text()
        .await
        .unwrap();
    assert!(!text.contains("event: done"), "{text}");
    assert!(
        text.contains("event: error") && text.contains("could not be saved"),
        "{text}"
    );
    assert!(text.contains("\"persisted\":true"), "{text}");
    let turn = turn_for(&state, "fault");
    assert_eq!(turn["stats"]["run_status"], "failed");
    assert_eq!(
        turn["story"], "first",
        "partial output must survive a failed commit"
    );
    task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn cancel_persists_all_streamed_text_despite_checkpoint_throttle() {
    let (base, _captured, provider_task) = provider(&["a", "b", "c", "d"], true, 0).await;
    let temp = tempfile::tempdir().unwrap();
    let state = open_state(temp.path(), &base);
    let (url, task) = serve(&state).await;
    let response = reqwest::Client::new()
        .post(format!("{url}/api/generate/stream"))
        .json(&json!({"session_id":"cancel","prompt":"Begin."}))
        .send()
        .await
        .unwrap();
    let mut bytes = response.bytes_stream();
    let mut seen = String::new();
    while seen.matches("event: answer.delta").count() < 4 {
        seen.push_str(&String::from_utf8_lossy(
            &tokio::time::timeout(Duration::from_secs(3), bytes.next())
                .await
                .unwrap()
                .unwrap()
                .unwrap(),
        ));
    }
    drop(bytes);
    for _ in 0..40 {
        tokio::time::sleep(Duration::from_millis(25)).await;
        let turn = turn_for(&state, "cancel");
        if turn["stats"]["run_status"] == "cancelled" {
            assert_eq!(turn["story"], "abcd");
            // Throttled: four deltas within 250ms produce one checkpoint write.
            assert_eq!(turn["stats"]["checkpoint_writes"], 1);
            task.abort();
            provider_task.abort();
            return;
        }
    }
    panic!("cancellation was not persisted");
}

#[tokio::test]
async fn restart_marks_running_turns_interrupted_and_keeps_partial_text() {
    let temp = tempfile::tempdir().unwrap();
    {
        let state = open_state(temp.path(), "http://127.0.0.1:9");
        state
            .store
            .insert("sessions", json!({"id":"crash","title":"Crash"}))
            .unwrap();
        state.store.insert("turns", json!({"session_id":"crash","user_prompt":"p","story":"half a scene","stats_json":{"run_status":"running","partial":true}})).unwrap();
        state.store.insert("turns", json!({"session_id":"crash","user_prompt":"p","story":"done","stats_json":{"run_status":"completed","partial":false}})).unwrap();
    }
    let state = open_state(temp.path(), "http://127.0.0.1:9");
    let turns = state
        .store
        .list("turns", &[("session_id", json!("crash"))])
        .unwrap();
    let interrupted = turns.iter().find(|t| t["story"] == "half a scene").unwrap();
    assert_eq!(interrupted["stats"]["run_status"], "interrupted");
    assert_eq!(interrupted["stats"]["partial"], true);
    let completed = turns.iter().find(|t| t["story"] == "done").unwrap();
    assert_eq!(completed["stats"]["run_status"], "completed");
}

#[tokio::test]
async fn idempotency_key_allows_one_run_and_rejects_reuse_with_other_payload_or_scope() {
    let (base, captured, provider_task) = provider(&["Once."], false, 150).await;
    let temp = tempfile::tempdir().unwrap();
    let state = open_state(temp.path(), &base);
    let (url, task) = serve(&state).await;
    let client = reqwest::Client::new();
    let send = |path: &'static str, body: Value| {
        client.post(format!("{url}/api/{path}")).json(&body).send()
    };
    let request = json!({"session_id":"idem","prompt":"Write once.","idempotency_key":"key-1"});
    let (first, second) = tokio::join!(
        send("generate", request.clone()),
        send("generate", request.clone())
    );
    let mut statuses = [first.unwrap(), second.unwrap()];
    statuses.sort_by_key(|r| r.status());
    let [winner, duplicate] = statuses;
    assert_eq!(winner.status(), StatusCode::OK);
    assert_eq!(duplicate.status(), StatusCode::CONFLICT);
    let winner: Value = winner.json().await.unwrap();
    let duplicate: Value = duplicate.json().await.unwrap();
    assert_eq!(duplicate["run_id"], winner["run_id"]);
    assert_eq!(
        writer_inputs(&captured).len(),
        1,
        "duplicate request started a second writer run"
    );

    // A retry after completion points at the finished run.
    let retry: Value = send("generate", request.clone())
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(retry["run_status"], "completed");
    assert_eq!(retry["turn_id"], winner["turn_id"]);
    // The streaming endpoint shares the key space but is a different scope.
    assert_eq!(
        send("generate/stream", request.clone())
            .await
            .unwrap()
            .status(),
        StatusCode::UNPROCESSABLE_ENTITY
    );
    let mut other_payload = request.clone();
    other_payload["prompt"] = json!("Something else.");
    assert_eq!(
        send("generate", other_payload).await.unwrap().status(),
        StatusCode::UNPROCESSABLE_ENTITY
    );
    let mut other_scope = request.clone();
    other_scope["session_id"] = json!("elsewhere");
    assert_eq!(
        send("generate", other_scope).await.unwrap().status(),
        StatusCode::UNPROCESSABLE_ENTITY
    );
    assert_eq!(writer_inputs(&captured).len(), 1);

    // Deliberate regenerate uses a fresh identity and runs.
    let mut regenerate = request.clone();
    regenerate["idempotency_key"] = json!("key-2");
    assert_eq!(
        send("generate", regenerate).await.unwrap().status(),
        StatusCode::OK
    );
    assert_eq!(writer_inputs(&captured).len(), 2);
    // Requests without a key keep working as before.
    let mut keyless = request;
    keyless.as_object_mut().unwrap().remove("idempotency_key");
    assert_eq!(
        send("generate", keyless).await.unwrap().status(),
        StatusCode::OK
    );
    task.abort();
    provider_task.abort();
}
