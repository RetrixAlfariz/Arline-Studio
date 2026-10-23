use arline_runtime::{config::RuntimeConfig, router, AppState};
use axum::{
    body::{Body, Bytes},
    extract::State,
    http::{HeaderMap, StatusCode},
    response::Response,
    routing::post,
    Router,
};
use futures_util::StreamExt;
use serde_json::{json, Value};
use std::{
    convert::Infallible,
    future::IntoFuture,
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::{net::TcpListener, sync::Notify, task::JoinHandle};

#[derive(Clone)]
struct MockProvider {
    requests: Arc<Mutex<Vec<(HeaderMap, Value)>>>,
    first_delta: Arc<Notify>,
    release: Arc<Notify>,
    hold_after_delta: bool,
}

#[derive(Clone)]
struct BeatProvider {
    requests: Arc<Mutex<Vec<Value>>>,
    calls: Arc<Mutex<usize>>,
    fail_at: Option<usize>,
}

async fn beat_chat(
    State(provider): State<BeatProvider>,
    axum::Json(payload): axum::Json<Value>,
) -> Response {
    let mut calls = provider.calls.lock().unwrap();
    *calls += 1;
    let call = *calls;
    provider.requests.lock().unwrap().push(payload);
    if provider.fail_at == Some(call) {
        return Response::builder()
            .status(StatusCode::INTERNAL_SERVER_ERROR)
            .body(Body::from("middle beat failed"))
            .unwrap();
    }
    let content = format!("beat-{call}");
    let body = format!(
        "event: message\ndata: {{\"type\":\"message.delta\",\"content\":\"{content}\"}}\n\nevent: chat.end\ndata: {{\"result\":{{\"output\":[{{\"type\":\"message\",\"content\":\"{content}\"}}]}}}}\n\ndata: [DONE]\n\n"
    );
    Response::builder()
        .status(StatusCode::OK)
        .header("content-type", "text/event-stream")
        .body(Body::from(body))
        .unwrap()
}

async fn beat_provider(fail_at: Option<usize>) -> (String, BeatProvider, JoinHandle<()>) {
    let provider = BeatProvider {
        requests: Arc::new(Mutex::new(Vec::new())),
        calls: Arc::new(Mutex::new(0)),
        fail_at,
    };
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server_provider = provider.clone();
    let task = tokio::spawn(async move {
        let _ = axum::serve(
            listener,
            Router::new()
                .route("/api/v1/chat", post(beat_chat))
                .with_state(server_provider),
        )
        .into_future()
        .await;
    });
    (format!("http://{address}"), provider, task)
}

async fn mock_chat(
    State(provider): State<MockProvider>,
    headers: HeaderMap,
    axum::Json(payload): axum::Json<Value>,
) -> Response {
    provider.requests.lock().unwrap().push((headers, payload));
    let first_delta = provider.first_delta.clone();
    let release = provider.release.clone();
    let hold = provider.hold_after_delta;
    let stream = async_stream::stream! {
        yield Ok::<Bytes, Infallible>(Bytes::from(
            "event: message\ndata: {\"type\":\"message.delta\",\"content\":\"first\"}\n\n",
        ));
        first_delta.notify_waiters();
        if hold {
            std::future::pending::<()>().await;
        } else {
            release.notified().await;
            yield Ok(Bytes::from("event: chat.end\ndata: {\"result\":{\"output\":[{\"type\":\"message\",\"content\":\"first\"}]}}\n\n"));
            yield Ok(Bytes::from("data: [DONE]\n\n"));
        }
    };
    Response::builder()
        .status(StatusCode::OK)
        .header("content-type", "text/event-stream")
        .body(Body::from_stream(stream))
        .unwrap()
}

async fn provider(hold_after_delta: bool) -> (String, MockProvider, JoinHandle<()>) {
    let provider = MockProvider {
        requests: Arc::new(Mutex::new(Vec::new())),
        first_delta: Arc::new(Notify::new()),
        release: Arc::new(Notify::new()),
        hold_after_delta,
    };
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server_provider = provider.clone();
    let task = tokio::spawn(async move {
        let _ = axum::serve(
            listener,
            Router::new()
                .route("/api/v1/chat", post(mock_chat))
                .with_state(server_provider),
        )
        .into_future()
        .await;
    });
    (format!("http://{address}"), provider, task)
}

async fn fixture(base_url: &str) -> (tempfile::TempDir, AppState, String, JoinHandle<()>) {
    let temp = tempfile::tempdir().unwrap();
    std::fs::write(
        temp.path().join("writer_system.txt"),
        "Loaded system prompt.",
    )
    .unwrap();
    let config_path = temp.path().join("config.toml");
    let config = format!(
        "[lmstudio]\nbase_url = \"{base_url}\"\nmodel = \"mock\"\napi_key = \"test-bearer\"\ntimeout_seconds = 10.0\n[generation]\nreasoning = \"off\"\nvisible_output_tokens = 64\nreasoning_reserve_tokens = 64\n[writer]\nsystem_prompt_file = \"writer_system.txt\"\n[workspace]\ndatabase_path = \"data/history.db\"\n"
    );
    std::fs::write(&config_path, config).unwrap();
    let state = AppState::open(RuntimeConfig::load(&config_path, temp.path()).unwrap()).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server_state = state.clone();
    let task = tokio::spawn(async move {
        let _ = axum::serve(listener, router(server_state))
            .into_future()
            .await;
    });
    (temp, state, format!("http://{address}"), task)
}

#[tokio::test]
async fn http_stream_delivers_delta_before_provider_completion_and_persists_turn() {
    let (provider_url, provider, provider_task) = provider(false).await;
    let (_temp, state, runtime_url, runtime_task) = fixture(&provider_url).await;
    let client = reqwest::Client::new();
    let response = client
        .post(format!("{runtime_url}/api/generate/stream"))
        .json(&json!({"session_id":"http-stream", "prompt":"Write a beginning."}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let mut bytes = response.bytes_stream();
    let mut output = String::new();
    while !output.contains("event: answer.delta") {
        let chunk = tokio::time::timeout(Duration::from_secs(3), bytes.next())
            .await
            .expect("runtime did not emit a delta")
            .expect("runtime stream ended before delta")
            .unwrap();
        output.push_str(&String::from_utf8_lossy(&chunk));
    }
    assert!(
        !output.contains("event: done"),
        "done arrived before upstream release"
    );
    let request = provider.requests.lock().unwrap().first().cloned().unwrap();
    assert_eq!(
        request.0.get("authorization").unwrap(),
        "Bearer test-bearer"
    );
    assert_eq!(request.1["reasoning"], "off");
    assert!(request.1["system_prompt"]
        .as_str()
        .unwrap()
        .contains("Loaded system prompt."));
    provider.release.notify_waiters();
    while let Some(chunk) = bytes.next().await {
        output.push_str(&String::from_utf8_lossy(&chunk.unwrap()));
    }
    assert!(output.contains("event: done"));
    let turns = state
        .store
        .list("turns", &[("session_id", json!("http-stream"))])
        .unwrap();
    assert_eq!(turns.len(), 1);
    assert_eq!(turns[0]["story"], "first");
    assert_eq!(turns[0]["stats"]["run_status"], "completed");
    runtime_task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn dropping_http_client_marks_partial_turn_cancelled() {
    let (provider_url, _provider, provider_task) = provider(true).await;
    let (_temp, state, runtime_url, runtime_task) = fixture(&provider_url).await;
    let client = reqwest::Client::new();
    let response = client
        .post(format!("{runtime_url}/api/generate/stream"))
        .json(&json!({"session_id":"cancel-stream", "prompt":"Start and cancel."}))
        .send()
        .await
        .unwrap();
    let mut bytes = response.bytes_stream();
    let mut first_output = String::new();
    while !first_output.contains("answer.delta") {
        let first = tokio::time::timeout(Duration::from_secs(3), bytes.next())
            .await
            .unwrap()
            .unwrap()
            .unwrap();
        first_output.push_str(&String::from_utf8_lossy(&first));
    }
    drop(bytes);
    let mut cancelled = false;
    for _ in 0..30 {
        tokio::time::sleep(Duration::from_millis(25)).await;
        let turns = state
            .store
            .list("turns", &[("session_id", json!("cancel-stream"))])
            .unwrap();
        if turns
            .first()
            .and_then(|turn| turn["stats"].get("run_status"))
            .and_then(Value::as_str)
            == Some("cancelled")
        {
            cancelled = true;
            assert_eq!(turns[0]["stats"]["partial"], true);
            break;
        }
    }
    assert!(
        cancelled,
        "dropping the client did not persist cancellation"
    );
    runtime_task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn streaming_generation_rejects_session_scope_mismatch_before_provider_call() {
    let (provider_url, provider, provider_task) = provider(false).await;
    let (_temp, state, runtime_url, runtime_task) = fixture(&provider_url).await;
    let _ = reqwest::Client::new()
        .get(format!("{runtime_url}/api/sessions"))
        .send()
        .await
        .unwrap();
    state
        .store
        .insert(
            "sessions",
            json!({
                "id":"scoped-session", "title":"Scoped", "project_id":"project-a",
                "created_at":"2026-10-23T00:00:00Z", "updated_at":"2026-10-23T00:00:00Z"
            }),
        )
        .unwrap();
    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/api/generate/stream"))
        .json(&json!({"session_id":"scoped-session", "project_id":"project-b", "prompt":"Wrong scope."}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    assert!(provider.requests.lock().unwrap().is_empty());
    runtime_task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn non_stream_generation_does_not_duplicate_final_provider_output() {
    let (provider_url, provider, provider_task) = provider(false).await;
    let (_temp, state, runtime_url, runtime_task) = fixture(&provider_url).await;
    provider.release.notify_one();
    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/api/generate"))
        .json(&json!({"prompt":"One sentence."}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["story"], "first");
    assert!(result["analysis_id"].as_str().is_some());
    let cached = state
        .store
        .query(
            "SELECT payload FROM analysis_cache WHERE id=?",
            &[&result["analysis_id"].as_str().unwrap()],
        )
        .unwrap();
    assert_eq!(cached.len(), 1);
    let turns = state
        .store
        .list(
            "turns",
            &[(
                "session_id",
                json!(result["session_id"].as_str().unwrap_or("")),
            )],
        )
        .unwrap();
    assert_eq!(turns[0]["feedback_status"], "unreviewed");
    runtime_task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn beat_generation_chains_previous_surface_and_persists_budget() {
    let (provider_url, provider, provider_task) = beat_provider(None).await;
    let (_temp, state, runtime_url, runtime_task) = fixture(&provider_url).await;
    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/api/generate"))
        .json(&json!({"session_id":"beat-session", "prompt":"Continue.", "generation_mode":"beats", "beat_count":3, "beat_tokens":256}))
        .send().await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let result: Value = response.json().await.unwrap();
    assert_eq!(provider.requests.lock().unwrap().len(), 3);
    let requests = provider.requests.lock().unwrap();
    assert!(requests[0]["input"]
        .as_str()
        .unwrap()
        .contains("Beat 1 of 3"));
    assert!(requests[1]["input"]
        .as_str()
        .unwrap()
        .contains("Previous surface:\nbeat-1"));
    assert!(requests[2]["input"].as_str().unwrap().contains("beat-2"));
    assert_eq!(result["stats"]["generation"]["total_budget"], 768);
    assert!(result["story"]
        .as_str()
        .unwrap()
        .contains("beat-1\n\nbeat-2\n\nbeat-3"));
    let cached = state
        .store
        .query(
            "SELECT payload FROM analysis_cache WHERE id=?",
            &[&result["analysis_id"].as_str().unwrap()],
        )
        .unwrap();
    let cached_payload: Value =
        serde_json::from_str(cached[0]["payload"].as_str().unwrap()).unwrap();
    assert_eq!(cached_payload["stats"]["generation"]["beat_count"], 3);
    runtime_task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn failed_middle_beat_persists_completed_prefix() {
    let (provider_url, provider, provider_task) = beat_provider(Some(2)).await;
    let (_temp, state, runtime_url, runtime_task) = fixture(&provider_url).await;
    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/api/generate"))
        .json(&json!({"session_id":"partial-beat", "prompt":"Continue.", "generation_mode":"beats", "beat_count":3, "beat_tokens":256}))
        .send().await.unwrap();
    assert!(!response.status().is_success());
    assert_eq!(*provider.calls.lock().unwrap(), 2);
    let turns = state
        .store
        .list("turns", &[("session_id", json!("partial-beat"))])
        .unwrap();
    assert_eq!(turns.len(), 1);
    assert_eq!(turns[0]["stats"]["run_status"], "partial");
    assert_eq!(turns[0]["stats"]["failed_beat"], 2);
    assert_eq!(turns[0]["story"], "beat-1");
    runtime_task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn actual_writer_receives_history_memory_and_one_persisted_planning_pass() {
    let captured = Arc::new(Mutex::new(Vec::<Value>::new()));
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let handler_captured = captured.clone();
    let provider_task = tokio::spawn(async move {
        axum::serve(listener,Router::new().route("/api/v1/chat",post(move |axum::Json(payload):axum::Json<Value>| {
            let captured=handler_captured.clone();async move {
                captured.lock().unwrap().push(payload.clone());
                if payload["stream"]==false {
                    Response::builder().header("content-type","application/json").body(Body::from(json!({"output":[{"type":"message","content":"{\"scene_goal\":\"PLAN_AMBER\",\"likely_beats\":[\"A measured step\"]}"}]}).to_string())).unwrap()
                }else{
                    Response::builder().header("content-type","text/event-stream").body(Body::from("event: message\ndata: {\"type\":\"message.delta\",\"content\":\"Fresh prose.\"}\n\nevent: chat.end\ndata: {\"result\":{\"output\":[{\"type\":\"message\",\"content\":\"Fresh prose.\"}],\"stats\":{\"output_tokens\":3}}}\n\ndata: [DONE]\n\n")).unwrap()
                }
            }
        }))).await.unwrap();
    });
    let (_temp, state, runtime, runtime_task) = fixture(&base).await;
    state
        .config
        .write()
        .unwrap()
        .set("deliberation.enabled", toml::Value::Boolean(true))
        .unwrap();
    state
        .store
        .insert(
            "projects",
            json!({"id":"retrieval-project","name":"Retrieval project"}),
        )
        .unwrap();
    let document=state.store.insert("workspace_documents",json!({"project_id":"retrieval-project","title":"Evidence","content":"sapphire RECALL_ONLY_OPAL"})).unwrap();
    arline_runtime::foundation::memory::refresh_document(&state, document["id"].as_str().unwrap())
        .unwrap();
    for (index, endpoint) in ["generate", "generate/stream"].into_iter().enumerate() {
        let session = format!("prepared-{index}");
        state
            .store
            .insert(
                "sessions",
                json!({"id":session,"title":"Continuity","project_id":"retrieval-project"}),
            )
            .unwrap();
        state.store.insert("turns",json!({"session_id":session,"user_prompt":"Old scene","story":"SHOULD_DROP_OLD_CONTEXT"})).unwrap();
        state.store.insert("turns",json!({"session_id":session,"user_prompt":"Opening","story":"REJECTED_ORIGINAL_SURFACE","feedback_status":"edited_accept","edited_story":"ORIGINAL_CONTINUITY_ZEBRA"})).unwrap();
        state
            .store
            .insert(
                "turns",
                json!({"session_id":session,"user_prompt":"Recent scene","story":"Latest action"}),
            )
            .unwrap();
        let response = reqwest::Client::new()
            .post(format!("{runtime}/api/{endpoint}"))
            .json(&json!({"session_id":session,"prompt":"sapphire"}))
            .send()
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let text = response.text().await.unwrap();
        let result: Value = if index == 0 {
            serde_json::from_str(&text).unwrap()
        } else {
            let done = text
                .split("event: done\ndata: ")
                .nth(1)
                .unwrap()
                .lines()
                .next()
                .unwrap();
            serde_json::from_str(done).unwrap()
        };
        let requests = captured.lock().unwrap().clone();
        assert_eq!(
            requests.len(),
            (index + 1) * 2,
            "planning must run once per request"
        );
        let writer = &requests[index * 2 + 1];
        let input = writer["input"].as_str().unwrap();
        assert!(
            input.contains("ORIGINAL_CONTINUITY_ZEBRA"),
            "history was lost: {input}"
        );
        assert!(
            !input.contains("SHOULD_DROP_OLD_CONTEXT"),
            "configured continuity turn limit ignored"
        );
        assert!(
            !input.contains("REJECTED_ORIGINAL_SURFACE"),
            "accepted author edit was ignored"
        );
        assert!(
            input.contains("RECALL_ONLY_OPAL"),
            "retrieval was only saved after generation: {input}"
        );
        assert!(
            input.contains("PLAN_AMBER"),
            "actual plan did not reach writer: {input}"
        );
        assert_eq!(input.matches("<REQUEST>").count(), 1);
        assert!(input.find("<CONVERSATION_HISTORY>").unwrap() < input.find("<REQUEST>").unwrap());
        let bundle =
            arline_runtime::analysis::cached(&state, result["analysis_id"].as_str().unwrap())
                .unwrap()
                .unwrap();
        assert_eq!(bundle["deliberation"]["status"], "model");
        assert_eq!(bundle["model_input"], writer["input"]);
    }
    runtime_task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn terminal_only_provider_output_preserves_text_stats_and_raw_response() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let provider = tokio::spawn(async move {
        axum::serve(listener, Router::new().route("/api/v1/chat", post(|| async {
            Response::builder().header("content-type", "text/event-stream").body(Body::from(
                "event: message.start\ndata: {\"type\":\"message.start\"}\n\nevent: reasoning.start\ndata: {\"type\":\"reasoning.start\"}\n\nevent: chat.end\ndata: {\"result\":{\"output\":[{\"type\":\"reasoning\",\"content\":\"A quiet plan\"},{\"type\":\"message\",\"content\":\"Only the final surface.\"}],\"stats\":{\"output_tokens\":5,\"tokens_per_second\":12.5}}}\n\ndata: [DONE]\n\n"
            )).unwrap()
        }))).await.unwrap();
    });
    let (_temp, state, runtime, task) = fixture(&base).await;
    for endpoint in ["generate", "generate/stream"] {
        let response = reqwest::Client::new()
            .post(format!("{runtime}/api/{endpoint}"))
            .json(&json!({"prompt":"Write one sentence."}))
            .send()
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let text = response.text().await.unwrap();
        let result: Value = if endpoint.ends_with("stream") {
            assert_eq!(text.matches("event: answer.delta").count(), 1);
            serde_json::from_str(
                text.split("event: done\ndata: ")
                    .nth(1)
                    .unwrap()
                    .lines()
                    .next()
                    .unwrap(),
            )
            .unwrap()
        } else {
            serde_json::from_str(&text).unwrap()
        };
        assert_eq!(result["story"], "Only the final surface.");
        assert_eq!(result["reasoning"], "A quiet plan");
        assert_eq!(result["stats"]["output_tokens"], 5);
        let bundle =
            arline_runtime::analysis::cached(&state, result["analysis_id"].as_str().unwrap())
                .unwrap()
                .unwrap();
        assert_eq!(bundle["raw_response"]["stats"]["tokens_per_second"], 12.5);
        assert_eq!(bundle["stats"]["output_tokens"], 5);
    }
    task.abort();
    provider.abort();
}

#[tokio::test]
async fn ablation_scores_validator_findings_and_keeps_provider_statistics() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let provider = tokio::spawn(async move {
        axum::serve(listener,Router::new().route("/api/v1/chat",post(||async {
        Response::builder().header("content-type","text/event-stream").body(Body::from("event: chat.end\ndata: {\"result\":{\"output\":[{\"type\":\"message\",\"content\":\"Mira Mira walks.\"}],\"stats\":{\"total_output_tokens\":5,\"reasoning_output_tokens\":0}}}\n\n")).unwrap()
    }))).await.unwrap();
    });
    let (_temp, _state, runtime, task) = fixture(&base).await;
    let response = reqwest::Client::new()
        .post(format!("{runtime}/api/ablation"))
        .json(&json!({"prompt":"Write Mira.","conditions":["raw:off"]}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let result: Value = response.json().await.unwrap();
    let row = &result["results"][0];
    assert_eq!(row["key"], "raw__thinking_off");
    assert_eq!(
        row["post_validation"]["quality_report"]["metrics"]["repetition_pairs"],
        1
    );
    assert!(row["diagnostic_score"].as_f64().unwrap() < 100.0);
    assert_eq!(row["stats"]["story_output_tokens"], 5);
    task.abort();
    provider.abort();
}

#[tokio::test]
async fn omitted_generation_overrides_use_saved_beat_settings() {
    let (base, provider, provider_task) = beat_provider(None).await;
    let (_temp, state, runtime, task) = fixture(&base).await;
    {
        let mut cfg = state.config.write().unwrap();
        cfg.set(
            "generation.generation_mode",
            toml::Value::String("beats".into()),
        )
        .unwrap();
        cfg.set("generation.beat_count", toml::Value::Integer(2))
            .unwrap();
        cfg.set("generation.beat_tokens", toml::Value::Integer(256))
            .unwrap();
    }
    let response = reqwest::Client::new()
        .post(format!("{runtime}/api/generate"))
        .json(&json!({"prompt":"Continue."}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let result: Value = response.json().await.unwrap();
    assert_eq!(*provider.calls.lock().unwrap(), 2);
    assert_eq!(result["stats"]["generation"]["tokens_per_beat"], 256);
    let cached = arline_runtime::analysis::cached(&state, result["analysis_id"].as_str().unwrap())
        .unwrap()
        .unwrap();
    assert_eq!(cached["model_input"].as_array().unwrap().len(), 2);
    assert!(cached["model_input"][1]
        .as_str()
        .unwrap()
        .contains("Previous surface:\nbeat-1"));
    task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn provider_error_after_a_prefix_is_never_saved_as_completed() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let provider = tokio::spawn(async move {
        axum::serve(listener,Router::new().route("/api/v1/chat",post(||async{Response::builder().header("content-type","text/event-stream").body(Body::from("event: message\ndata: {\"type\":\"message.delta\",\"content\":\"Partial surface\"}\n\nevent: error\ndata: {\"error\":{\"message\":\"decoder failed\"}}\n\n")).unwrap()}))).await.unwrap();
    });
    let (_temp, state, runtime, task) = fixture(&base).await;
    let response = reqwest::Client::new()
        .post(format!("{runtime}/api/generate"))
        .json(&json!({"prompt":"Continue.","session_id":"error-run"}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::INTERNAL_SERVER_ERROR);
    assert!(state
        .store
        .list("turns", &[("session_id", json!("error-run"))])
        .unwrap()
        .is_empty());
    let text = reqwest::Client::new()
        .post(format!("{runtime}/api/generate/stream"))
        .json(&json!({"prompt":"Continue.","session_id":"error-stream"}))
        .send()
        .await
        .unwrap()
        .text()
        .await
        .unwrap();
    assert!(text.contains("event: error"));
    assert!(!text.contains("event: done"));
    let rows = state
        .store
        .list("turns", &[("session_id", json!("error-stream"))])
        .unwrap();
    assert_eq!(rows[0]["stats"]["run_status"], "failed");
    assert_eq!(rows[0]["story"], "Partial surface");
    task.abort();
    provider.abort();
}

#[tokio::test]
async fn feedback_edits_capture_author_source_and_deletion_respects_fork_lineage() {
    let (_temp, state, runtime, task) = fixture("http://127.0.0.1:1").await;
    state
        .store
        .insert(
            "sessions",
            json!({"id":"feedback-session","title":"Feedback"}),
        )
        .unwrap();
    state.store.insert("turns", json!({"id":"feedback-turn","session_id":"feedback-session","user_prompt":"Mara is a patient archivist.","story":"Mara is a tired archivist."})).unwrap();
    arline_runtime::foundation::memory::refresh_turn(&state, "feedback-turn").unwrap();
    let client = reqwest::Client::new();
    let response=client.post(format!("{runtime}/api/turns/feedback-turn/feedback")).json(&json!({"status":"edited_accept","edited_story":"Mara is a careful archivist.","issues":[" tense ","tense"],"note":" fixed "})).send().await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["ok"], true);
    assert_eq!(
        result["turn"]["final_story"],
        "Mara is a careful archivist."
    );
    assert_eq!(result["turn"]["feedback_issues"], json!(["tense"]));
    assert_eq!(result["turn"]["feedback_note"], "fixed");
    assert!(result["dataset"].is_object());
    let sources=state.store.query("SELECT * FROM discovery_instances WHERE source_turn_id=? AND source_kind='user_edited_prose' AND active=1", &[&"feedback-turn"]).unwrap();
    assert!(
        !sources.is_empty(),
        "accepted author edits must enter discovery with explicit provenance"
    );
    state.store.insert("sessions",json!({"id":"child","title":"Child","parent_session_id":"feedback-session","forked_from_turn_id":"feedback-turn"})).unwrap();
    assert_eq!(
        client
            .delete(format!("{runtime}/api/turns/feedback-turn"))
            .send()
            .await
            .unwrap()
            .status(),
        StatusCode::CONFLICT
    );
    assert_eq!(
        client
            .delete(format!("{runtime}/api/sessions/child"))
            .send()
            .await
            .unwrap()
            .status(),
        StatusCode::OK
    );
    let deleted: Value = client
        .delete(format!("{runtime}/api/turns/feedback-turn"))
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(deleted["turn_id"], "feedback-turn");
    assert_eq!(deleted["session_id"], "feedback-session");
    assert!(state.store.get("turns", "feedback-turn").unwrap().is_none());
    assert!(state
        .store
        .query(
            "SELECT id FROM discovery_instances WHERE source_turn_id='feedback-turn' AND active=1",
            &[]
        )
        .unwrap()
        .is_empty());
    assert!(state.store.query("SELECT id FROM memory_chunks WHERE source_id='feedback-turn' AND semantic_status='active'",&[]).unwrap().is_empty());
    task.abort();
}
