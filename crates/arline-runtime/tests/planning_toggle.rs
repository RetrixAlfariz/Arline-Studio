use arline_runtime::{config::RuntimeConfig, router, AppState};
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
    response::Response,
    routing::{get, post},
    Json, Router,
};
use serde_json::{json, Value};
use std::sync::{Arc, Mutex};
use tower::ServiceExt;

struct HttpFixture {
    _temp: tempfile::TempDir,
    state: AppState,
    requests: Arc<Mutex<Vec<Value>>>,
    provider: tokio::task::JoinHandle<()>,
}

async fn http_fixture() -> HttpFixture {
    let requests = Arc::new(Mutex::new(Vec::<Value>::new()));
    let captured = requests.clone();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let provider = tokio::spawn(async move {
        axum::serve(
            listener,
            Router::new()
                .route(
                    "/api/v1/models",
                    get(|| async {
                        Json(json!({"models":[{"type":"llm","key":"testmodel","loaded_instances":[{"id":"testmodel","config":{"context_length":32768}}],"capabilities":{"reasoning":{"allowed_options":["off","on"]}}}]}))
                    }),
                )
                .route(
                    "/api/v1/chat",
                    post(move |Json(payload): Json<Value>| {
                        let captured = captured.clone();
                        async move {
                            captured.lock().unwrap().push(payload.clone());
                            if payload["stream"] == false {
                                Response::builder()
                                    .header("content-type", "application/json")
                                    .body(Body::from(json!({"output":[{"type":"message","content":"A planned scene."}]}).to_string()))
                                    .unwrap()
                            } else {
                                Response::builder()
                                    .header("content-type", "text/event-stream")
                                    .body(Body::from("event: message\ndata: {\"type\":\"message.delta\",\"content\":\"A completed scene.\"}\n\nevent: chat.end\ndata: {\"result\":{\"output\":[{\"type\":\"message\",\"content\":\"A completed scene.\"}]}}\n\n"))
                                    .unwrap()
                            }
                        }
                    }),
                ),
        )
        .await
        .unwrap();
    });
    let temporary = tempfile::tempdir().unwrap();
    let mut config = RuntimeConfig::create_default(
        temporary.path().join("config/arline.toml"),
        temporary.path(),
    )
    .unwrap();
    config
        .set("lmstudio.base_url", toml::Value::String(base))
        .unwrap();
    config
        .set("lmstudio.model", toml::Value::String("testmodel".into()))
        .unwrap();
    HttpFixture {
        _temp: temporary,
        state: AppState::open(config).unwrap(),
        requests,
        provider,
    }
}

async fn call_http(fixture: &HttpFixture, endpoint: &str, body: Value) -> (StatusCode, Value) {
    let response = router(fixture.state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(format!("/api/{endpoint}"))
                .header("content-type", "application/json")
                .body(Body::from(body.to_string()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let text = String::from_utf8(
        to_bytes(response.into_body(), 4 * 1024 * 1024)
            .await
            .unwrap()
            .to_vec(),
    )
    .unwrap();
    if !status.is_success() {
        return (status, json!(text));
    }
    let value = if endpoint.ends_with("stream") {
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
    (status, value)
}

fn assert_routing(result: &Value, mode: &str, planning: bool, reason: &str) {
    let routing = &result["deliberation"]["routing"];
    assert_eq!(routing["requested_mode"], mode);
    assert_eq!(routing["planning_enabled"], planning);
    assert_eq!(
        routing["effective_mode"],
        if planning { "deep" } else { "fast" }
    );
    assert_eq!(routing["preparation_fast_path"], !planning);
    if !reason.is_empty() {
        assert_eq!(routing["reason"], reason);
    }
    let metadata = &result["stats"]["inference"]["metadata"];
    assert_eq!(metadata["deliberation_requested_mode"], mode);
    assert_eq!(
        metadata["deliberation_effective_mode"],
        if planning { "deep" } else { "fast" }
    );
    assert_eq!(metadata["preparation_fast_path"], !planning);
    assert!(result["post_validation"].is_object());
    assert!(result["wcf_validation"].is_object());
}

#[tokio::test]
async fn planning_override_is_independent_of_saved_default_and_reasoning() {
    let requests = Arc::new(Mutex::new(Vec::<Value>::new()));
    let captured = requests.clone();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let provider = tokio::spawn(async move {
        axum::serve(
            listener,
            Router::new()
                .route(
                    "/api/v1/models",
                    get(|| async {
                        Json(json!({"models":[{"type":"llm","key":"testmodel","loaded_instances":[{"id":"testmodel","config":{"context_length":32768}}],"capabilities":{"reasoning":{"allowed_options":["off","on"]}}}]}))
                    }),
                )
                .route(
                    "/api/v1/chat",
                    post(move |Json(payload): Json<Value>| {
                        let requests = captured.clone();
                        async move {
                            requests.lock().unwrap().push(payload.clone());
                            if payload["stream"] == false {
                                Response::builder().header("content-type", "application/json")
                                    .body(Body::from(json!({"output":[{"type":"message","content":"{\"scene_goal\":\"PLAN_TOGGLE\"}"}]}).to_string())).unwrap()
                            } else {
                                Response::builder().header("content-type", "text/event-stream")
                                    .body(Body::from("event: message\ndata: {\"type\":\"message.delta\",\"content\":\"A completed scene.\"}\n\nevent: chat.end\ndata: {\"result\":{\"output\":[{\"type\":\"message\",\"content\":\"A completed scene.\"}]}}\n\n")).unwrap()
                            }
                        }
                    }),
                ),
        )
        .await
        .unwrap();
    });
    let temporary = tempfile::tempdir().unwrap();
    let mut config = RuntimeConfig::create_default(
        temporary.path().join("config/arline.toml"),
        temporary.path(),
    )
    .unwrap();
    config
        .set("lmstudio.base_url", toml::Value::String(base))
        .unwrap();
    config
        .set("lmstudio.model", toml::Value::String("testmodel".into()))
        .unwrap();
    let state = AppState::open(config).unwrap();
    for endpoint in ["generate", "generate/stream"] {
        for (saved, mode, reasoning, enabled) in [
            (false, None, "off", false),
            (false, Some("on"), "off", true),
            (true, Some("off"), "on", false),
        ] {
            state
                .config
                .write()
                .unwrap()
                .set("deliberation.enabled", toml::Value::Boolean(saved))
                .unwrap();
            let mut body = json!({"prompt":"Write one sentence.","reasoning":reasoning});
            if let Some(mode) = mode {
                body["deliberation_mode"] = json!(mode);
            }
            let previous = requests.lock().unwrap().len();
            let response = router(state.clone())
                .oneshot(
                    Request::builder()
                        .method("POST")
                        .uri(format!("/api/{endpoint}"))
                        .header("content-type", "application/json")
                        .body(Body::from(body.to_string()))
                        .unwrap(),
                )
                .await
                .unwrap();
            assert_eq!(response.status(), StatusCode::OK);
            let text = String::from_utf8(
                to_bytes(response.into_body(), 1024 * 1024)
                    .await
                    .unwrap()
                    .to_vec(),
            )
            .unwrap();
            let result: Value = serde_json::from_str(if endpoint.ends_with("stream") {
                text.split("event: done\ndata: ")
                    .nth(1)
                    .unwrap()
                    .lines()
                    .next()
                    .unwrap()
            } else {
                &text
            })
            .unwrap();
            assert_eq!(result["story"], "A completed scene.");
            assert_eq!(
                result["deliberation"]["status"],
                if enabled { "model" } else { "disabled" }
            );
            let calls = requests.lock().unwrap();
            assert_eq!(calls.len() - previous, if enabled { 2 } else { 1 });
            let writer = calls.last().unwrap();
            assert_eq!(writer["reasoning"], reasoning);
            assert_eq!(
                writer["input"].as_str().unwrap().contains("PLAN_TOGGLE"),
                enabled
            );
        }
    }
    provider.abort();
}

#[tokio::test]
async fn deliberation_modes_route_both_http_endpoints_and_preserve_metadata() {
    for endpoint in ["generate", "generate/stream"] {
        let fixture = http_fixture().await;
        fixture
            .state
            .config
            .write()
            .unwrap()
            .set("deliberation.mode", toml::Value::String("fast".into()))
            .unwrap();
        let long_prompt = "ambiguous ".repeat(90);
        let cases = vec![
            (
                json!({"prompt":"Write one sentence.","deliberation_mode":"fast"}),
                "fast",
                false,
                "explicit_fast",
            ),
            (
                json!({"prompt":"Write one sentence.","deliberation_mode":"auto"}),
                "auto",
                false,
                "auto_simple",
            ),
            (
                json!({"prompt":"Write one sentence.","deliberation_mode":"deep"}),
                "deep",
                true,
                "explicit_deep",
            ),
            (
                json!({"prompt":"Explore this scene with two possible directions.","conversation_mode":"story_lab","deliberation_mode":"auto"}),
                "auto",
                true,
                "auto_complex",
            ),
            (
                json!({"prompt":long_prompt,"deliberation_mode":"auto"}),
                "auto",
                true,
                "auto_complex",
            ),
            (
                json!({"prompt":"/intuition Give me an instinctive read.","deliberation_mode":"fast"}),
                "fast",
                true,
                "explicit_author_command",
            ),
            (
                json!({"prompt":"/alternatives Give me two alternatives.","deliberation_mode":"auto"}),
                "auto",
                true,
                "explicit_author_command",
            ),
            (
                json!({"prompt":"/intuition Keep this disabled.","deliberation_mode":"off"}),
                "off",
                false,
                "explicit_off",
            ),
        ];
        for (body, mode, planning, reason) in cases {
            let before = fixture.requests.lock().unwrap().len();
            let (status, result) = call_http(&fixture, endpoint, body).await;
            assert_eq!(status, StatusCode::OK, "{endpoint} {mode}");
            assert_routing(&result, mode, planning, reason);
            let calls = fixture.requests.lock().unwrap();
            assert_eq!(calls.len() - before, if planning { 2 } else { 1 });
            let writer = calls.last().unwrap()["input"].as_str().unwrap();
            for key in ["requested_mode", "effective_mode", "preparation_fast_path"] {
                assert!(
                    !writer.contains(key),
                    "routing key leaked into writer input: {key}"
                );
            }
            drop(calls);
        }
        fixture.provider.abort();
    }
}

#[tokio::test]
async fn saved_mode_fallback_and_legacy_explicit_modes_have_precedence() {
    let fixture = http_fixture().await;
    for (saved, body, expected, planning) in [
        (
            "auto",
            json!({"prompt":"Write one sentence."}),
            "auto",
            false,
        ),
        (
            "deep",
            json!({"prompt":"Write one sentence.","deliberation_mode":null}),
            "deep",
            true,
        ),
        (
            "auto",
            json!({"prompt":"Write one sentence.","deliberation_mode":"on"}),
            "on",
            true,
        ),
        (
            "deep",
            json!({"prompt":"Write one sentence.","deliberation_mode":"off"}),
            "off",
            false,
        ),
    ] {
        fixture
            .state
            .config
            .write()
            .unwrap()
            .set("deliberation.mode", toml::Value::String(saved.into()))
            .unwrap();
        let (status, result) = call_http(&fixture, "generate", body).await;
        assert_eq!(status, StatusCode::OK);
        assert_routing(&result, expected, planning, "");
    }
    fixture.provider.abort();
}

#[tokio::test]
async fn invalid_deliberation_mode_is_rejected_before_provider_call() {
    let fixture = http_fixture().await;
    for endpoint in ["generate", "generate/stream"] {
        let before = fixture.requests.lock().unwrap().len();
        let (status, _) = call_http(
            &fixture,
            endpoint,
            json!({"prompt":"Write one sentence.","deliberation_mode":"invalid"}),
        )
        .await;
        assert_eq!(status, StatusCode::BAD_REQUEST);
        assert_eq!(fixture.requests.lock().unwrap().len(), before);
    }
    fixture.provider.abort();
}

#[tokio::test]
async fn fast_generation_keeps_active_branch_canon_and_rejects_foreign_reference() {
    let fixture = http_fixture().await;
    for (id, name) in [("project-a", "Project A"), ("project-b", "Project B")] {
        fixture
            .state
            .store
            .insert("projects", json!({"id":id,"name":name,"slug":id}))
            .unwrap();
    }
    fixture
        .state
        .store
        .insert(
            "worlds",
            json!({"id":"world-a","project_id":"project-a","name":"World A","slug":"world-a"}),
        )
        .unwrap();
    fixture
        .state
        .store
        .insert(
            "world_branches",
            json!({"id":"branch-a","world_id":"world-a","name":"branch-a","slug":"branch-a"}),
        )
        .unwrap();
    fixture
        .state
        .store
        .insert(
            "world_branches",
            json!({"id":"branch-b","world_id":"world-a","name":"branch-b","slug":"branch-b"}),
        )
        .unwrap();
    fixture.state.store.insert("canon_facts", json!({"id":"active","project_id":"project-a","world_id":"world-a","branch_id":"branch-a","owner_type":"world","owner_id":"world-a","path":"rule.active","value":"Active branch canon","status":"canon","authority":"user_explicit","source_type":"manual"})).unwrap();
    fixture.state.store.insert("canon_facts", json!({"id":"inactive","project_id":"project-a","world_id":"world-a","branch_id":"branch-b","owner_type":"world","owner_id":"world-a","path":"rule.inactive","value":"Inactive branch canon","status":"canon","authority":"user_explicit","source_type":"manual"})).unwrap();
    fixture.state.store.insert("canon_facts", json!({"id":"foreign","project_id":"project-b","world_id":null,"branch_id":null,"owner_type":"world","owner_id":"project-b","path":"rule.foreign","value":"Foreign project canon","status":"canon","authority":"user_explicit","source_type":"manual"})).unwrap();
    fixture.state.store.insert("workspace_documents", json!({"id":"foreign-doc","project_id":"project-b","title":"Foreign","content":"Private foreign content","document_type":"scene"})).unwrap();

    let before = fixture.requests.lock().unwrap().len();
    let (status, result) = call_http(&fixture, "generate", json!({"project_id":"project-a","world_id":"world-a","branch_id":"branch-a","prompt":"Write one sentence.","deliberation_mode":"fast"})).await;
    assert_eq!(status, StatusCode::OK);
    assert_routing(&result, "fast", false, "explicit_fast");
    let writer = fixture.requests.lock().unwrap()[before]["input"]
        .as_str()
        .unwrap()
        .to_owned();
    assert!(writer.contains("Active branch canon"));
    assert!(!writer.contains("Inactive branch canon"));
    assert!(!writer.contains("Foreign project canon"));
    let before = fixture.requests.lock().unwrap().len();
    let (status, _) = call_http(&fixture, "generate", json!({"project_id":"project-a","world_id":"world-a","prompt":"Write one sentence.","deliberation_mode":"fast","references":[{"type":"document","id":"foreign-doc"}]})).await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(fixture.requests.lock().unwrap().len(), before);
    fixture.provider.abort();
}
