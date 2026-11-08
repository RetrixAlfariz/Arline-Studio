//! Inference engine seam: LM Studio (native v1 REST) or an Arline-managed
//! llama.cpp `llama-server` sidecar. llama-server traffic is reshaped into LM
//! Studio's payload, event and result shapes so the streaming, budget, telemetry
//! and context-compiler code stays engine-agnostic.
use crate::{config::RuntimeConfig, ApiError, ApiResult, AppState};
use axum::http::StatusCode;
use serde_json::{json, Value};
use std::{
    path::{Path, PathBuf},
    process::Stdio,
    time::{Duration, Instant},
};
use tokio::process::{Child, Command};

pub struct Sidecar {
    child: Child,
    pub key: String,
    pub context_length: u64,
}

pub fn is_llama(cfg: &RuntimeConfig) -> bool {
    cfg.str("inference.engine", "lmstudio") == "llama_server"
}

pub fn base_url(cfg: &RuntimeConfig) -> String {
    if is_llama(cfg) {
        format!("http://127.0.0.1:{}", cfg.u64("llama_server.port", 18080))
    } else {
        cfg.str("lmstudio.base_url", "http://127.0.0.1:1234")
            .trim_end_matches('/')
            .to_owned()
    }
}

pub fn chat_url(cfg: &RuntimeConfig) -> String {
    let path = if is_llama(cfg) { "/v1/chat/completions" } else { "/api/v1/chat" };
    format!("{}{path}", base_url(cfg))
}

/// Request body for the configured engine, built from an LM Studio-shaped payload.
pub fn provider_body(cfg: &RuntimeConfig, payload: &Value) -> Value {
    if is_llama(cfg) {
        llama_body(payload)
    } else {
        payload.clone()
    }
}

fn llama_messages(p: &Value) -> Value {
    let mut messages = Vec::new();
    if let Some(system) = p["system_prompt"].as_str().filter(|s| !s.is_empty()) {
        messages.push(json!({"role":"system","content":system}));
    }
    let user = match &p["input"] {
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(|item| {
                    if item["type"] == "image" {
                        json!({"type":"image_url","image_url":{"url":item["data_url"]}})
                    } else {
                        json!({"type":"text","text":item["content"]})
                    }
                })
                .collect(),
        ),
        other => other.clone(),
    };
    messages.push(json!({"role":"user","content":user}));
    Value::Array(messages)
}

fn thinking(p: &Value) -> bool {
    p.get("reasoning")
        .and_then(Value::as_str)
        .is_some_and(|mode| mode != "off")
}

fn llama_body(p: &Value) -> Value {
    let stream = p["stream"].as_bool().unwrap_or(false);
    let mut body = json!({"messages":llama_messages(p),"stream":stream,
        "chat_template_kwargs":{"enable_thinking":thinking(p)}});
    if stream {
        body["stream_options"] = json!({"include_usage":true});
    }
    if let Some(limit) = p.get("max_output_tokens") {
        body["max_tokens"] = limit.clone();
    }
    for key in ["model", "temperature", "top_p", "top_k", "min_p", "repeat_penalty", "seed"] {
        if let Some(value) = p.get(key) {
            body[key] = value.clone();
        }
    }
    body
}

fn llama_stats(usage: &Value, timings: &Value, finish: Option<&str>) -> Value {
    json!({"input_tokens":usage["prompt_tokens"],"total_output_tokens":usage["completion_tokens"],
        "cached_input_tokens":timings["cache_n"],"tokens_per_second":timings["predicted_per_second"],
        "time_to_first_token_seconds":timings["prompt_ms"].as_f64().map(|ms| ms / 1000.0),
        "finish_reason":finish})
}

/// Turns provider stream chunks into LM Studio-shaped events
/// (`reasoning.delta`, `message.delta`, `chat.end` with `result.stats`).
pub enum StreamNormalizer {
    Passthrough,
    Llama { finish: Option<String> },
}

impl StreamNormalizer {
    pub fn for_config(cfg: &RuntimeConfig) -> Self {
        if is_llama(cfg) {
            Self::Llama { finish: None }
        } else {
            Self::Passthrough
        }
    }

    pub fn events(&mut self, chunk: Value) -> Vec<Value> {
        let Self::Llama { finish } = self else {
            return vec![chunk];
        };
        if let Some(error) = chunk.get("error") {
            return vec![json!({"type":"error","error":error})];
        }
        let mut events = Vec::new();
        if let Some(delta) = chunk.pointer("/choices/0/delta") {
            if let Some(text) = delta["reasoning_content"].as_str().filter(|s| !s.is_empty()) {
                events.push(json!({"type":"reasoning.delta","content":text}));
            }
            if let Some(text) = delta["content"].as_str().filter(|s| !s.is_empty()) {
                events.push(json!({"type":"message.delta","content":text}));
            }
        }
        if let Some(reason) = chunk
            .pointer("/choices/0/finish_reason")
            .and_then(Value::as_str)
        {
            *finish = Some(reason.to_owned());
        }
        // The usage chunk arrives last (stream_options.include_usage).
        if chunk.get("usage").is_some_and(Value::is_object) {
            events.push(json!({"type":"chat.end","result":{"output":[],
                "stats":llama_stats(&chunk["usage"],&chunk["timings"],finish.as_deref())}}));
        }
        events
    }
}

/// Non-streaming response in LM Studio's `{output:[...], stats}` shape.
pub fn normalize_response(cfg: &RuntimeConfig, raw: Value) -> Value {
    if !is_llama(cfg) {
        return raw;
    }
    let message = raw.pointer("/choices/0/message").cloned().unwrap_or(Value::Null);
    let mut output = Vec::new();
    if let Some(text) = message["reasoning_content"].as_str().filter(|s| !s.is_empty()) {
        output.push(json!({"type":"reasoning","content":text}));
    }
    output.push(json!({"type":"message","content":message["content"].as_str().unwrap_or("")}));
    let finish = raw.pointer("/choices/0/finish_reason").and_then(Value::as_str);
    json!({"output":output,"stats":llama_stats(&raw["usage"],&raw["timings"],finish)})
}

/// Exact prompt tokens via the loaded model's own chat template and tokenizer.
pub async fn exact_input_tokens(
    client: &reqwest::Client,
    base: &str,
    payload: &Value,
) -> ApiResult<u64> {
    let templated: Value = client
        .post(format!("{base}/apply-template"))
        .json(&json!({"messages":llama_messages(payload),"chat_template_kwargs":{"enable_thinking":thinking(payload)}}))
        .send()
        .await
        .map_err(provider_error)?
        .json()
        .await
        .map_err(provider_error)?;
    let prompt = templated["prompt"]
        .as_str()
        .ok_or_else(|| ApiError::internal("llama-server apply-template returned no prompt"))?;
    let tokens: Value = client
        .post(format!("{base}/tokenize"))
        .json(&json!({"content":prompt,"add_special":true}))
        .send()
        .await
        .map_err(provider_error)?
        .json()
        .await
        .map_err(provider_error)?;
    tokens["tokens"]
        .as_array()
        .map(|t| t.len() as u64)
        .ok_or_else(|| ApiError::internal("llama-server tokenize returned no tokens"))
}

fn provider_error(error: reqwest::Error) -> ApiError {
    ApiError::new(
        StatusCode::SERVICE_UNAVAILABLE,
        format!("llama-server request failed: {error}"),
    )
}

fn resolve(cfg: &RuntimeConfig, value: &str) -> PathBuf {
    let path = PathBuf::from(value);
    if path.is_absolute() {
        path
    } else {
        cfg.root.join(path)
    }
}

pub fn models_dir(cfg: &RuntimeConfig) -> Option<PathBuf> {
    let configured = cfg.str("llama_server.models_dir", "");
    if !configured.is_empty() {
        return Some(resolve(cfg, &configured));
    }
    // Reuse LM Studio's download folder so existing GGUFs need no copy.
    let home = std::env::var_os("USERPROFILE").or_else(|| std::env::var_os("HOME"))?;
    let settings = std::fs::read(PathBuf::from(home).join(".cache/lm-studio/settings.json")).ok()?;
    let settings: Value = serde_json::from_slice(&settings).ok()?;
    settings["downloadsFolder"].as_str().map(PathBuf::from)
}

/// Native folder picker on the user's desktop (the runtime is loopback-only).
/// `Ok(None)` means the user cancelled.
pub async fn pick_folder(start: Option<PathBuf>) -> ApiResult<Option<PathBuf>> {
    #[cfg(windows)]
    {
        tokio::task::spawn_blocking(move || {
            let mut dialog = rfd::FileDialog::new().set_title("Choose the folder that holds your GGUF models");
            if let Some(dir) = start.filter(|d| d.is_dir()) {
                dialog = dialog.set_directory(dir);
            }
            dialog.pick_folder()
        })
        .await
        .map_err(|e| ApiError::internal(format!("folder dialog failed: {e}")))
    }
    #[cfg(not(windows))]
    {
        let _ = start;
        Err(ApiError::new(
            StatusCode::NOT_IMPLEMENTED,
            "Folder picker is Windows-only; type the folder path instead",
        ))
    }
}

/// GGUF models keyed like LM Studio: the containing folder's name, lowercased,
/// or `folder/file-stem` when a folder holds several weight files.
pub fn catalog(cfg: &RuntimeConfig) -> Vec<(String, PathBuf)> {
    let mut found = Vec::new();
    if let Some(dir) = models_dir(cfg) {
        collect_gguf(&dir, 3, &mut found);
    }
    found.sort();
    keyed(found)
}

fn collect_gguf(dir: &Path, depth: u8, out: &mut Vec<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for path in entries.flatten().map(|entry| entry.path()) {
        if path.is_dir() && depth > 0 {
            collect_gguf(&path, depth - 1, out);
        } else if path.extension().is_some_and(|ext| ext.eq_ignore_ascii_case("gguf"))
            && !path
                .file_name()
                .is_some_and(|n| n.to_string_lossy().to_ascii_lowercase().starts_with("mmproj"))
        {
            out.push(path);
        }
    }
}

fn keyed(paths: Vec<PathBuf>) -> Vec<(String, PathBuf)> {
    let folder = |p: &Path| {
        p.parent()
            .and_then(Path::file_name)
            .map(|n| n.to_string_lossy().to_ascii_lowercase())
            .unwrap_or_default()
    };
    paths
        .iter()
        .map(|path| {
            let siblings = paths.iter().filter(|p| p.parent() == path.parent()).count();
            let stem = path
                .file_stem()
                .map(|n| n.to_string_lossy().to_ascii_lowercase())
                .unwrap_or_default();
            let key = if siblings == 1 {
                folder(path)
            } else {
                format!("{}/{stem}", folder(path))
            };
            (key, path.clone())
        })
        .collect()
}

async fn running(state: &AppState) -> Option<(String, u64)> {
    let mut guard = state.llama.lock().await;
    let alive = guard
        .as_mut()
        .is_some_and(|sidecar| matches!(sidecar.child.try_wait(), Ok(None)));
    if !alive {
        *guard = None;
    }
    guard.as_ref().map(|s| (s.key.clone(), s.context_length))
}

/// LM Studio-shaped `/api/v1/models` payload for the GGUF catalog.
pub async fn models_payload(state: &AppState, cfg: &RuntimeConfig) -> Value {
    let loaded = running(state).await;
    let models: Vec<Value> = catalog(cfg)
        .into_iter()
        .map(|(key, path)| {
            // shortcut: embedding/reranker detection by name; read GGUF metadata if mislabelled.
            let kind = if key.contains("embed") || key.contains("rerank") { "embedding" } else { "llm" };
            let instances = match &loaded {
                Some((id, ctx)) if *id == key => json!([{"id":key,"config":{"context_length":ctx}}]),
                _ => json!([]),
            };
            json!({"type":kind,"key":key,"display_name":key,"path":path,"format":"gguf",
                "loaded_instances":instances,
                "capabilities":{"reasoning":{"allowed_options":["off","on"]},"vision":false}})
        })
        .collect();
    json!({"models":models})
}

fn executable(cfg: &RuntimeConfig) -> PathBuf {
    let configured = cfg.str("llama_server.executable", "");
    if configured.is_empty() {
        PathBuf::from(if cfg!(windows) { "llama-server.exe" } else { "llama-server" })
    } else {
        resolve(cfg, &configured)
    }
}

/// shortcut: the prebuilt binary is CUDA 13; installed toolkit DLLs are put on
/// the child PATH. Ship cudart DLLs beside the exe for machines without one.
fn child_path() -> std::ffi::OsString {
    let mut dirs: Vec<PathBuf> = std::env::vars_os()
        .filter(|(name, _)| name.to_string_lossy().starts_with("CUDA_PATH_V13"))
        .map(|(_, value)| PathBuf::from(value).join("bin").join("x64"))
        .collect();
    dirs.extend(std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default()));
    std::env::join_paths(dirs).unwrap_or_default()
}

/// (Re)start the sidecar with `key` and wait until it serves requests.
pub async fn load(
    state: &AppState,
    cfg: &RuntimeConfig,
    key: &str,
    context_length: u64,
    gpu_ratio: f64,
) -> ApiResult<Value> {
    let path = catalog(cfg)
        .into_iter()
        .find(|(k, _)| k == key)
        .map(|(_, p)| p)
        .ok_or_else(|| {
            ApiError::bad_request(format!(
                "No GGUF model {key:?} in the llama-server models directory"
            ))
        })?;
    let mut guard = state.llama.lock().await;
    if let Some(mut old) = guard.take() {
        let _ = old.child.kill().await;
    }
    let port = cfg.u64("llama_server.port", 18080).to_string();
    let health = format!("http://127.0.0.1:{port}/health");
    // Windows lets a second server bind the same port; a stranger answering
    // there would silently receive Arline's traffic.
    if state
        .client
        .get(&health)
        .timeout(Duration::from_secs(1))
        .send()
        .await
        .is_ok()
    {
        return Err(ApiError::new(
            StatusCode::CONFLICT,
            format!("Port {port} is already in use by another server; stop it or change llama_server.port"),
        ));
    }
    // shortcut: partial offload is all-or-nothing; map gpu_ratio to a layer count if needed.
    let layers = if gpu_ratio > 0.0 { "999" } else { "0" };
    let log_dir = cfg
        .database_path()
        .parent()
        .map(|p| p.join("logs"))
        .unwrap_or_else(|| PathBuf::from("logs"));
    std::fs::create_dir_all(&log_dir)?;
    let log = std::fs::File::create(log_dir.join("llama-server.log"))?;
    let mut command = Command::new(executable(cfg));
    command
        .arg("-m")
        .arg(&path)
        .args(["-c", &context_length.to_string(), "-ngl", layers, "--parallel", "1"])
        .args(["--jinja", "--host", "127.0.0.1", "--port", &port, "--alias", key])
        .env("PATH", child_path())
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(log)
        .kill_on_drop(true);
    if cfg.bool("model_load.flash_attention", true) {
        command.args(["--flash-attn", "on"]);
    }
    #[cfg(windows)]
    command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    let mut child = command.spawn().map_err(|error| {
        ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            format!("llama-server could not start ({}): {error}", executable(cfg).display()),
        )
    })?;
    #[cfg(windows)]
    if let Some(handle) = child.raw_handle() {
        kill_with_parent::assign(handle);
    }
    let started = Instant::now();
    let limit = Duration::from_secs_f64(cfg.f64("lmstudio.timeout_seconds", 600.0).clamp(5.0, 600.0));
    loop {
        if let Ok(Some(status)) = child.try_wait() {
            return Err(ApiError::new(
                StatusCode::SERVICE_UNAVAILABLE,
                format!("llama-server exited during load ({status}); see {}", log_dir.join("llama-server.log").display()),
            ));
        }
        let ready = state
            .client
            .get(&health)
            .timeout(Duration::from_secs(2))
            .send()
            .await
            .is_ok_and(|r| r.status().is_success());
        if ready {
            break;
        }
        if started.elapsed() > limit {
            let _ = child.kill().await;
            return Err(ApiError::new(
                StatusCode::GATEWAY_TIMEOUT,
                "llama-server did not become ready in time",
            ));
        }
        tokio::time::sleep(Duration::from_millis(250)).await;
    }
    let props: Value = match state
        .client
        .get(format!("http://127.0.0.1:{port}/props"))
        .send()
        .await
    {
        Ok(response) => response.json().await.unwrap_or(Value::Null),
        Err(_) => Value::Null,
    };
    if props["model_path"].as_str().map(PathBuf::from) != Some(path.clone()) {
        let _ = child.kill().await;
        return Err(ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "llama-server on the configured port is not serving the requested model",
        ));
    }
    *guard = Some(Sidecar {
        child,
        key: key.to_owned(),
        context_length,
    });
    Ok(json!({"type":"success","engine":"llama_server","model":key,"path":path,
        "context_length":context_length,"port":port,"load_seconds":started.elapsed().as_secs_f64()}))
}

/// `kill_on_drop` only runs on a clean shutdown. A kill-on-close Job Object makes
/// Windows end the sidecar (and free its VRAM and port) however Arline exits.
#[cfg(windows)]
mod kill_with_parent {
    use std::{ffi::c_void, sync::OnceLock};

    #[repr(C)]
    #[derive(Default)]
    struct BasicLimit {
        per_process_user_time: i64,
        per_job_user_time: i64,
        limit_flags: u32,
        min_working_set: usize,
        max_working_set: usize,
        active_process_limit: u32,
        affinity: usize,
        priority_class: u32,
        scheduling_class: u32,
    }
    #[repr(C)]
    #[derive(Default)]
    struct ExtendedLimit {
        basic: BasicLimit,
        io_counters: [u64; 6],
        process_memory_limit: usize,
        job_memory_limit: usize,
        peak_process_memory: usize,
        peak_job_memory: usize,
    }
    const KILL_ON_JOB_CLOSE: u32 = 0x2000;
    const EXTENDED_LIMIT_INFORMATION: i32 = 9;
    #[link(name = "kernel32")]
    extern "system" {
        fn CreateJobObjectW(attributes: *mut c_void, name: *const u16) -> *mut c_void;
        fn SetInformationJobObject(job: *mut c_void, class: i32, info: *mut c_void, len: u32) -> i32;
        fn AssignProcessToJobObject(job: *mut c_void, process: *mut c_void) -> i32;
    }
    // The job handle is never closed; process exit closes it and kills members.
    static JOB: OnceLock<usize> = OnceLock::new();

    pub fn assign(process: std::os::windows::io::RawHandle) {
        let job = *JOB.get_or_init(|| unsafe {
            let job = CreateJobObjectW(std::ptr::null_mut(), std::ptr::null());
            if job.is_null() {
                return 0;
            }
            let mut info = ExtendedLimit::default();
            info.basic.limit_flags = KILL_ON_JOB_CLOSE;
            SetInformationJobObject(
                job,
                EXTENDED_LIMIT_INFORMATION,
                (&mut info as *mut ExtendedLimit).cast(),
                std::mem::size_of::<ExtendedLimit>() as u32,
            );
            job as usize
        });
        if job != 0 {
            // Best effort: on failure the clean-shutdown kill_on_drop path still applies.
            unsafe { AssignProcessToJobObject(job as *mut c_void, process.cast()) };
        }
    }

    #[test]
    fn extended_limit_matches_win64_layout() {
        assert_eq!(std::mem::size_of::<ExtendedLimit>(), 144);
    }
}

/// Auto-load the writer when nothing (or a different model) is running.
pub async fn ensure_loaded(state: &AppState, cfg: &RuntimeConfig, requested: &str) -> ApiResult<()> {
    if !is_llama(cfg) || !cfg.bool("lmstudio.auto_load", true) {
        return Ok(());
    }
    let key = if requested.is_empty() {
        cfg.str("lmstudio.model", "")
    } else {
        requested.to_owned()
    };
    match running(state).await {
        Some((loaded, _)) if key.is_empty() || loaded == key => Ok(()),
        _ if key.is_empty() => Ok(()),
        _ => load(
            state,
            cfg,
            &key,
            cfg.u64("model_load.context_length", 32768),
            cfg.f64("model_load.gpu_ratio", 1.0),
        )
        .await
        .map(|_| ()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn llama_body_maps_lmstudio_payload() {
        let body = llama_body(&json!({"model":"m","input":"hi","system_prompt":"sys","stream":true,
            "max_output_tokens":64,"temperature":0.5,"reasoning":"on","context_length":4096}));
        assert_eq!(body["messages"][0], json!({"role":"system","content":"sys"}));
        assert_eq!(body["messages"][1], json!({"role":"user","content":"hi"}));
        assert_eq!(body["max_tokens"], 64);
        assert_eq!(body["chat_template_kwargs"]["enable_thinking"], true);
        assert_eq!(body["stream_options"]["include_usage"], true);
        assert!(body.get("context_length").is_none());
        let off = llama_body(&json!({"input":"x","reasoning":"off"}));
        assert_eq!(off["chat_template_kwargs"]["enable_thinking"], false);
    }

    #[test]
    fn stream_chunks_become_lmstudio_events() {
        let mut n = StreamNormalizer::Llama { finish: None };
        assert_eq!(
            n.events(json!({"choices":[{"delta":{"reasoning_content":"think"}}]})),
            vec![json!({"type":"reasoning.delta","content":"think"})]
        );
        assert_eq!(
            n.events(json!({"choices":[{"delta":{"content":"Mara"}}]})),
            vec![json!({"type":"message.delta","content":"Mara"})]
        );
        assert!(n.events(json!({"choices":[{"delta":{},"finish_reason":"length"}]})).is_empty());
        let end = n.events(json!({"choices":[],"usage":{"prompt_tokens":29,"completion_tokens":44},
            "timings":{"prompt_ms":61.0,"predicted_per_second":105.9,"cache_n":0}}));
        let stats = &end[0]["result"]["stats"];
        assert_eq!(end[0]["type"], "chat.end");
        assert_eq!(stats["input_tokens"], 29);
        assert_eq!(stats["total_output_tokens"], 44);
        assert_eq!(stats["finish_reason"], "length");
        assert_eq!(stats["time_to_first_token_seconds"], 0.061);
        assert_eq!(
            n.events(json!({"error":{"message":"boom"}}))[0]["type"],
            "error"
        );
        let mut passthrough = StreamNormalizer::Passthrough;
        assert_eq!(passthrough.events(json!({"x":1})), vec![json!({"x":1})]);
    }

    #[test]
    fn catalog_keys_match_lmstudio_folder_keys() {
        let keys = keyed(vec![
            PathBuf::from("m/Pub/Qwen3.5-4B-Aggressive/q4.gguf"),
            PathBuf::from("m/Pub/Multi/a-Q4.gguf"),
            PathBuf::from("m/Pub/Multi/a-Q8.gguf"),
        ]);
        assert_eq!(keys[0].0, "qwen3.5-4b-aggressive");
        assert_eq!(keys[1].0, "multi/a-q4");
        assert_eq!(keys[2].0, "multi/a-q8");
    }
}
