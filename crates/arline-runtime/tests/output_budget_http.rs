use arline_runtime::{config::RuntimeConfig, router, AppState};
use axum::{
    body::Body, extract::State, http::StatusCode, response::Response, routing::post as route_post,
    Router,
};
use serde_json::{json, Value};
use std::{
    future::IntoFuture,
    sync::{Arc, Mutex},
};
use tokio::net::TcpListener;

#[derive(Clone)]
struct Provider {
    requests: Arc<Mutex<Vec<Value>>>,
}

async fn chat(
    State(provider): State<Provider>,
    axum::Json(payload): axum::Json<Value>,
) -> Response {
    provider.requests.lock().unwrap().push(payload.clone());
    if payload["stream"] == false {
        return Response::builder()
            .status(StatusCode::OK)
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "output":[{"type":"message","content":"{\"scene_goal\":\"test plan\"}"}]
                })
                .to_string(),
            ))
            .unwrap();
    }
    let cutoff = payload["input"]
        .as_str()
        .is_some_and(|input| input.contains("cutoff"));
    let unknown_usage = payload["input"]
        .as_str()
        .is_some_and(|input| input.contains("unknown_usage"));
    let finish = if cutoff {
        ",\"finish_reason\":\"length\""
    } else {
        ""
    };
    let stats = if unknown_usage {
        String::new()
    } else {
        format!(",\"stats\":{{\"output_tokens\":3}}{finish}")
    };
    let body = format!("event: message\ndata: {{\"type\":\"message.delta\",\"content\":\"generated\"}}\n\nevent: chat.end\ndata: {{\"result\":{{\"output\":[{{\"type\":\"message\",\"content\":\"generated\"}}]{stats}}}}}\n\ndata: [DONE]\n\n");
    Response::builder()
        .status(StatusCode::OK)
        .header("content-type", "text/event-stream")
        .body(Body::from(body))
        .unwrap()
}

async fn provider() -> (String, Provider, tokio::task::JoinHandle<()>) {
    let provider = Provider {
        requests: Arc::new(Mutex::new(Vec::new())),
    };
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let task_provider = provider.clone();
    let task = tokio::spawn(async move {
        let _ = axum::serve(
            listener,
            Router::new()
                .route("/api/v1/models", axum::routing::get(||async {axum::Json(json!({"models":[{"type":"llm","key":"mock","capabilities":{"reasoning":{"allowed_options":["off","on"]}},"loaded_instances":[{"id":"mock","config":{"context_length":32768}}]}]}))}))
                .route("/api/v1/chat", route_post(chat))
                .with_state(task_provider),
        )
        .into_future()
        .await;
    });
    (format!("http://{address}"), provider, task)
}

async fn fixture(
    base_url: &str,
) -> (
    tempfile::TempDir,
    AppState,
    String,
    tokio::task::JoinHandle<()>,
) {
    let temp = tempfile::tempdir().unwrap();
    std::fs::write(temp.path().join("writer_system.txt"), "test writer").unwrap();
    let config_path = temp.path().join("config.toml");
    std::fs::write(&config_path, format!(
        "[lmstudio]\nbase_url=\"{base_url}\"\nmodel=\"mock\"\ntimeout_seconds=10.0\n[generation]\nreasoning=\"off\"\nvisible_output_tokens=512\nreasoning_reserve_tokens=64\noutput_budget_mode=\"fixed\"\n[writer]\nsystem_prompt_file=\"writer_system.txt\"\n[workspace]\ndatabase_path=\"data/history.db\"\n[reasoning_runtime]\nenforce_model_capabilities=false\n"
    )).unwrap();
    let state = AppState::open(RuntimeConfig::load(&config_path, temp.path()).unwrap()).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let task_state = state.clone();
    let task = tokio::spawn(async move {
        let _ = axum::serve(listener, router(task_state))
            .into_future()
            .await;
    });
    (temp, state, format!("http://{address}"), task)
}

async fn post_json(runtime: &str, path: &str, body: Value) -> (StatusCode, Value) {
    let response = reqwest::Client::new()
        .post(format!("{runtime}{path}"))
        .json(&body)
        .send()
        .await
        .unwrap();
    let status = response.status();
    let text = response.text().await.unwrap();
    let value = if path.ends_with("/stream") {
        text.split("event: done\ndata: ")
            .nth(1)
            .and_then(|chunk| chunk.lines().next())
            .and_then(|line| serde_json::from_str(line).ok())
            .unwrap_or_else(|| json!({"raw":text}))
    } else {
        serde_json::from_str(&text).unwrap_or_else(|_| json!({"raw":text}))
    };
    (status, value)
}

fn writer_requests(provider: &Provider) -> Vec<Value> {
    provider
        .requests
        .lock()
        .unwrap()
        .iter()
        .filter(|x| x["stream"] == true)
        .cloned()
        .collect()
}

#[tokio::test]
async fn single_and_stream_preserve_resolved_budget_metadata() {
    let (url, provider, provider_task) = provider().await;
    let (_temp, _state, runtime, runtime_task) = fixture(&url).await;
    let (status, single) = post_json(&runtime, "/api/generate", json!({"prompt":"Write one short line.","output_budget_mode":"fixed","visible_output_tokens":512,"reasoning":"off"})).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        single["stats"]["output_budget"]["visible_target_tokens"],
        512
    );
    assert_eq!(
        single["stats"]["output_budget"]["api_max_output_tokens"],
        512
    );
    let (status, stream) = post_json(&runtime, "/api/generate/stream", json!({"prompt":"Write one short line.","output_budget_mode":"fixed","visible_output_tokens":512,"reasoning":"off"})).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        stream["stats"]["output_budget"]["visible_target_tokens"],
        512
    );
    assert_eq!(
        stream["stats"]["output_budget"]["api_max_output_tokens"],
        512
    );
    assert_eq!(writer_requests(&provider).len(), 2);
    runtime_task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn auto_floor_and_numeric_override_are_visible_in_provider_and_stats() {
    let (url, provider, provider_task) = provider().await;
    let (_temp, _state, runtime, runtime_task) = fixture(&url).await;
    let (status, auto) = post_json(&runtime, "/api/generate", json!({"prompt":"Continue.","output_budget_mode":"auto","task":"short_continue","reasoning":"off"})).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(auto["stats"]["output_budget"]["visible_target_tokens"], 512);
    let (status, fixed) = post_json(&runtime, "/api/generate", json!({"prompt":"Continue.","output_budget_mode":"auto","task":"short_continue","visible_output_tokens":900,"reasoning":"off"})).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        fixed["stats"]["output_budget"]["visible_target_tokens"],
        900
    );
    let writers = writer_requests(&provider);
    assert_eq!(writers[0]["max_output_tokens"], 512);
    assert_eq!(writers[1]["max_output_tokens"], 900);
    let (status, null_defaults) = post_json(
        &runtime,
        "/api/generate",
        json!({
            "prompt":"Continue.", "output_budget_mode":null, "visible_output_tokens":null,
            "reasoning_reserve_tokens":null, "max_output_tokens":null,
            "beat_tokens":null, "total_story_target_tokens":null,
            "deliberation_max_tokens":null, "reasoning":"off"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(null_defaults["stats"]["output_budget"]["mode"], "fixed");
    assert_eq!(
        null_defaults["stats"]["output_budget"]["visible_target_tokens"],
        512
    );
    assert_eq!(
        null_defaults["stats"]["output_budget"]["api_max_output_tokens"],
        512
    );
    assert_eq!(
        null_defaults["stats"]["output_budget"]["requested_reasoning_reserve_tokens"],
        64
    );
    runtime_task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn invalid_budget_is_rejected_before_provider_call() {
    let (url, provider, provider_task) = provider().await;
    let (_temp, _state, runtime, runtime_task) = fixture(&url).await;
    for body in [
        json!({"prompt":"x","visible_output_tokens":0}),
        json!({"prompt":"x","visible_output_tokens":"512"}),
        json!({"prompt":"x","reasoning_reserve_tokens":-1}),
        json!({"prompt":"x","max_output_tokens":18446744073709551615u128}),
    ] {
        let (status, _) = post_json(&runtime, "/api/generate", body).await;
        assert_eq!(status, StatusCode::BAD_REQUEST);
    }
    assert!(provider.requests.lock().unwrap().is_empty());
    runtime_task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn beats_split_total_exactly_and_keep_per_call_reserve() {
    let (url, provider, provider_task) = provider().await;
    let (_temp, _state, runtime, runtime_task) = fixture(&url).await;
    let (status, result) = post_json(
        &runtime,
        "/api/generate",
        json!({
            "prompt":"Advance the scene.", "generation_mode":"beats", "beat_count":3,
            "total_story_target_tokens":10, "reasoning":"on", "reasoning_reserve_tokens":4
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let writers = writer_requests(&provider);
    assert_eq!(writers.len(), 3);
    assert_eq!(
        writers
            .iter()
            .map(|x| x["max_output_tokens"].as_u64().unwrap())
            .collect::<Vec<_>>(),
        vec![8, 7, 7]
    );
    assert_eq!(
        result["stats"]["output_budget"]["visible_target_tokens"],
        10
    );
    assert_eq!(
        result["stats"]["output_budget"]["reasoning_reserve_tokens"],
        12
    );
    assert_eq!(
        result["stats"]["output_budget"]["api_max_output_tokens"],
        22
    );
    assert_eq!(
        result["stats"]["generation"]["beats"]
            .as_array()
            .unwrap()
            .len(),
        3
    );
    runtime_task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn planner_limit_is_independent_from_writer_limit() {
    let (url, provider, provider_task) = provider().await;
    let (_temp, _state, runtime, runtime_task) = fixture(&url).await;
    let (status, _) = post_json(&runtime, "/api/generate", json!({"prompt":"Deep scene.","deliberation_mode":"deep","visible_output_tokens":512,"deliberation_max_tokens":77,"reasoning":"off"})).await;
    assert_eq!(status, StatusCode::OK);
    let calls = provider.requests.lock().unwrap().clone();
    let planner = calls.iter().find(|x| x["stream"] == false).unwrap();
    let writer = calls.iter().find(|x| x["stream"] == true).unwrap();
    assert_eq!(planner["max_output_tokens"], 77);
    assert_eq!(writer["max_output_tokens"], 512);
    assert!(!writer["input"].as_str().unwrap().contains("output_budget"));
    runtime_task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn explicit_cap_under_target_is_reported_and_provider_cutoff_is_observed() {
    let (url, provider, provider_task) = provider().await;
    let (_temp, _state, runtime, runtime_task) = fixture(&url).await;
    let (status, result) = post_json(
        &runtime,
        "/api/generate",
        json!({
            "prompt":"cutoff", "output_budget_mode":"fixed", "visible_output_tokens":512,
            "max_output_tokens":128, "reasoning":"on", "reasoning_reserve_tokens":64
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let budget = &result["stats"]["output_budget"];
    assert_eq!(budget["visible_target_tokens"], 512);
    assert_eq!(budget["api_max_output_tokens"], 128);
    assert_eq!(budget["visible_target_exceeds_cap"], true);
    assert_eq!(budget["requested_reasoning_reserve_tokens"], 64);
    assert_eq!(budget["reasoning_reserve_tokens"], 0);
    assert_eq!(result["stats"]["output_cutoff"], true);
    assert_eq!(
        provider.requests.lock().unwrap().last().unwrap()["max_output_tokens"],
        128
    );
    runtime_task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn unknown_provider_usage_stays_unknown() {
    let (url, _provider, provider_task) = provider().await;
    let (_temp, _state, runtime, runtime_task) = fixture(&url).await;
    let (status, result) = post_json(
        &runtime,
        "/api/generate",
        json!({
            "prompt":"unknown_usage", "output_budget_mode":"fixed", "visible_output_tokens":512,
            "reasoning":"off"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert!(result["stats"]["total_output_tokens"].is_null());
    assert!(result["stats"]["output_cutoff"].is_null());
    assert!(result["stats"]["likely_output_budget_cutoff"].is_null());
    runtime_task.abort();
    provider_task.abort();
}

#[tokio::test]
async fn larger_explicit_cap_does_not_inflate_reasoning_reserve_on_single_and_stream() {
    let (url, provider, provider_task) = provider().await;
    let (_temp, _state, runtime, runtime_task) = fixture(&url).await;
    for path in ["/api/generate", "/api/generate/stream"] {
        let (status, result) = post_json(
            &runtime,
            path,
            json!({
                "prompt":"larger cap", "output_budget_mode":"fixed", "visible_output_tokens":512,
                "max_output_tokens":1000, "reasoning":"on", "reasoning_reserve_tokens":64
            }),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(
            result["stats"]["output_budget"]["api_max_output_tokens"],
            1000
        );
        assert_eq!(
            result["stats"]["output_budget"]["reasoning_reserve_tokens"],
            64
        );
        assert_eq!(
            result["stats"]["output_budget"]["visible_target_exceeds_cap"],
            false
        );
    }
    let writers = writer_requests(&provider);
    assert_eq!(
        writers
            .iter()
            .rev()
            .take(2)
            .map(|x| x["max_output_tokens"].as_u64().unwrap())
            .collect::<Vec<_>>(),
        vec![1000, 1000]
    );
    runtime_task.abort();
    provider_task.abort();
}
