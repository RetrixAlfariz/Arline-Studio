pub mod analysis;
pub mod canon_workflows;
pub mod config;
pub mod context;
pub mod domain_events;
pub mod foundation;
pub mod foundation_extended;
pub mod generation;
pub mod import;
pub mod io_services;
pub mod models;
pub mod profile;
pub mod request_contracts;
pub mod store;
pub mod workspace;
pub mod workspace_advanced;

use axum::{
    body::{to_bytes, Body},
    extract::{Request, State},
    http::{header, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    Json, Router,
};
use config::RuntimeConfig;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    path::PathBuf,
    sync::{Arc, RwLock},
    time::Duration,
};
use store::Store;

include!(concat!(env!("OUT_DIR"), "/assets.rs"));

#[derive(Clone)]
pub struct AppState {
    pub store: Store,
    pub config: Arc<RwLock<RuntimeConfig>>,
    pub client: reqwest::Client,
    pub root: PathBuf,
    pub storage_gate: Arc<tokio::sync::RwLock<()>>,
    pub projection_gate: Arc<std::sync::Mutex<()>>,
}

impl AppState {
    pub fn open(config: RuntimeConfig) -> ApiResult<Self> {
        let store = Store::open(config.database_path())?;
        let client = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(10))
            .timeout(Duration::from_secs_f64(
                config
                    .f64("lmstudio.timeout_seconds", 600.0)
                    .clamp(1.0, 3600.0),
            ))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|error| ApiError::internal(error.to_string()))?;
        foundation::FoundationStore::new(store.clone())?;
        foundation::memory::initialize(&store)?;
        generation::initialize(&store)?;
        analysis::ensure_schema(&store)?;
        domain_events::initialize(&store)?;
        Ok(Self {
            root: config.root.clone(),
            store,
            config: Arc::new(RwLock::new(config)),
            client,
            storage_gate: Arc::new(tokio::sync::RwLock::new(())),
            projection_gate: Arc::new(std::sync::Mutex::new(())),
        })
    }

    pub fn runtime_config(&self) -> ApiResult<RuntimeConfig> {
        self.config
            .read()
            .map(|value| value.clone())
            .map_err(|_| ApiError::internal("Runtime configuration lock poisoned"))
    }
}

#[derive(Debug)]
pub struct ApiError {
    pub status: StatusCode,
    pub message: String,
}

pub type ApiResult<T> = Result<T, ApiError>;

impl ApiError {
    pub fn new(status: StatusCode, message: impl Into<String>) -> Self {
        Self {
            status,
            message: message.into(),
        }
    }
    pub fn bad_request(message: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, message)
    }
    pub fn not_found(message: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, message)
    }
    pub fn internal(message: impl Into<String>) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, message)
    }
}
impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.message.fmt(f)
    }
}
impl std::error::Error for ApiError {}
impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({"detail":self.message}))).into_response()
    }
}
impl From<rusqlite::Error> for ApiError {
    fn from(error: rusqlite::Error) -> Self {
        match &error {
            rusqlite::Error::QueryReturnedNoRows => Self::not_found("Resource not found"),
            rusqlite::Error::SqliteFailure(code, _)
                if code.code == rusqlite::ErrorCode::ConstraintViolation =>
            {
                Self::bad_request(error.to_string())
            }
            _ => Self::internal(error.to_string()),
        }
    }
}
impl From<std::io::Error> for ApiError {
    fn from(error: std::io::Error) -> Self {
        Self::internal(error.to_string())
    }
}
impl From<serde_json::Error> for ApiError {
    fn from(error: serde_json::Error) -> Self {
        Self::bad_request(error.to_string())
    }
}

pub fn router(state: AppState) -> Router {
    Router::new().fallback(dispatch).with_state(state)
}

async fn dispatch(State(state): State<AppState>, request: Request) -> Response {
    let method = request.method().as_str().to_owned();
    let raw_path = request.uri().path().to_owned();
    let query: HashMap<String, String> =
        url::form_urlencoded::parse(request.uri().query().unwrap_or("").as_bytes())
            .into_owned()
            .collect();
    let origin = request
        .headers()
        .get(header::ORIGIN)
        .and_then(|value| value.to_str().ok())
        .map(str::to_owned);
    let host = request
        .headers()
        .get(header::HOST)
        .and_then(|value| value.to_str().ok())
        .unwrap_or("")
        .to_owned();
    if !host.is_empty() {
        let local_host = format!("http://{host}")
            .parse::<url::Url>()
            .ok()
            .is_some_and(|url| {
                url.host_str().is_some_and(|name| {
                    name == "localhost"
                        || name
                            .parse::<std::net::IpAddr>()
                            .is_ok_and(|ip| ip.is_loopback())
                })
            });
        if !local_host {
            return ApiError::new(StatusCode::FORBIDDEN, "Invalid local runtime host")
                .into_response();
        }
    }
    // A local runtime must not accept a browser page using it as a cross-origin write API.
    if let Some(origin) = origin {
        if !["GET", "HEAD", "OPTIONS"].contains(&method.as_str())
            && origin != format!("http://{host}")
            && origin != format!("https://{host}")
        {
            return ApiError::new(StatusCode::FORBIDDEN, "Cross-origin writes are not allowed")
                .into_response();
        }
    }
    let path_owned: Vec<String> = raw_path
        .trim_matches('/')
        .split('/')
        .filter(|part| !part.is_empty())
        .map(|part| {
            percent_encoding::percent_decode_str(part)
                .decode_utf8_lossy()
                .into_owned()
        })
        .collect();
    if path_owned
        .iter()
        .any(|part| part == ".." || part.contains(['/', '\\', '\0']))
    {
        return ApiError::bad_request("Invalid path segment").into_response();
    }
    let body_bytes = match to_bytes(request.into_body(), 32 * 1024 * 1024).await {
        Ok(bytes) => bytes,
        Err(_) => {
            return ApiError::new(StatusCode::PAYLOAD_TOO_LARGE, "Request body exceeds 32 MiB")
                .into_response()
        }
    };
    let body: Value = if body_bytes.is_empty() {
        json!({})
    } else {
        match serde_json::from_slice(&body_bytes) {
            Ok(value) => value,
            Err(error) => {
                return ApiError::bad_request(format!("Invalid JSON body: {error}")).into_response()
            }
        }
    };
    let path: Vec<&str> = path_owned.iter().map(String::as_str).collect();
    let mut body = body;
    if method == "GET" && path.as_slice() == ["api", "models"] {
        if let Some(server) = query.get("server_url") {
            body["server_url"] = json!(server);
        }
    }
    if let Err(errors) = request_contracts::validate(&method, &path, &body) {
        return (
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({"detail":errors})),
        )
            .into_response();
    }
    let storage_guard = if path.as_slice() == ["api", "storage", "reset"] {
        None
    } else {
        Some(state.storage_gate.clone().read_owned().await)
    };
    let result = if path.first() == Some(&"api") {
        let api = &path[1..];
        if api == ["health"] && method == "GET" {
            Ok(Json(json!({"ok":true,"runtime":"rust","python_required":false,"version":env!("CARGO_PKG_VERSION")})).into_response())
        } else if api == ["frontend"] && method == "GET" {
            Ok(Json(json!({"mode":"react","built":EMBEDDED_ASSETS.iter().any(|(name,_)| *name=="/index.html"),"frontend_root":"embedded"})).into_response())
        } else if let Some(response) =
            io_services::handle(&state, &method, api, &query, &body).await
        {
            response
        } else if let Some(response) =
            foundation_extended::handle(&state, &method, api, &query, &body)
        {
            response.map(|value| Json(value).into_response())
        } else if let Some(response) = canon_workflows::handle(&state, &method, api, &query, &body)
        {
            response.map(|value| Json(value).into_response())
        } else if let Some(response) =
            workspace_advanced::handle(&state, &method, api, &query, &body)
        {
            response.map(|value| Json(value).into_response())
        } else if let Some(response) = models::handle(state.clone(), &method, api, &body).await {
            response
        } else if let Some(response) = workspace::handle(&state, &method, api, &query, &body) {
            response.map(|value| Json(value).into_response())
        } else if let Some(response) =
            generation::handle(state.clone(), &method, api, &query, body.clone()).await
        {
            response
        } else if let Some(response) =
            foundation::handle(state.clone(), &method, api, &query, body).await
        {
            response
        } else {
            Err(ApiError::not_found(format!(
                "Unknown API route: {method} {raw_path}"
            )))
        }
    } else if method == "GET" && matches!(path.as_slice(), ["downloads" | "dataset-downloads", _]) {
        io_services::download(&state, path[0], path[1])
    } else if method == "GET" || method == "HEAD" {
        let asset_name = if raw_path == "/" {
            "/index.html"
        } else {
            &raw_path
        };
        match EMBEDDED_ASSETS.iter().find(|(name, _)| *name == asset_name) {
            Some((name, bytes)) => {
                let data = if method == "HEAD" { &[][..] } else { *bytes };
                let mut response = Response::new(Body::from(data));
                response
                    .headers_mut()
                    .insert(header::CONTENT_TYPE, HeaderValue::from_static(mime(name)));
                response.headers_mut().insert(
                    header::X_CONTENT_TYPE_OPTIONS,
                    HeaderValue::from_static("nosniff"),
                );
                Ok(response)
            }
            None => Err(ApiError::not_found("Asset not found")),
        }
    } else {
        Err(ApiError::not_found("Route not found"))
    };
    if matches!(method.as_str(), "POST" | "PUT" | "PATCH" | "DELETE") {
        if let Err(error) = domain_events::flush(&state) {
            // The source mutation is durable. Retain its queued notification so
            // a subsequent request can retry a failed derived-cache rebuild.
            eprintln!("Workspace projection refresh deferred: {}", error.message);
        }
    }
    let response = result.unwrap_or_else(IntoResponse::into_response);
    let (parts, body) = response.into_parts();
    let stream = async_stream::stream! {
        let _guard=storage_guard;
        let mut stream=body.into_data_stream();
        use futures_util::StreamExt;
        while let Some(chunk)=stream.next().await {yield chunk;}
    };
    Response::from_parts(parts, Body::from_stream(stream))
}

fn mime(path: &str) -> &'static str {
    match path.rsplit('.').next().unwrap_or("") {
        "html" => "text/html; charset=utf-8",
        "js" | "mjs" => "text/javascript; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "json" => "application/json",
        "svg" => "image/svg+xml",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "webp" => "image/webp",
        "ico" => "image/x-icon",
        "woff2" => "font/woff2",
        _ => "application/octet-stream",
    }
}
