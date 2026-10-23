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
                        Json(json!({"models":[{"key":"testmodel","capabilities":{"reasoning":{"allowed_options":["off","on"]}}}]}))
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
