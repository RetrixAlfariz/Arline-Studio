use crate::{ApiError, ApiResult, AppState};
use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use base64::{engine::general_purpose::STANDARD as BASE64, Engine};
use serde_json::{json, Value};
use std::{
    path::{Path, PathBuf},
    process::Command,
    time::Duration,
};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;

pub async fn handle(
    state: AppState,
    method: &str,
    path: &[&str],
    body: &Value,
) -> Option<ApiResult<Response>> {
    let result: ApiResult<Value> = match (method, path) {
        ("GET", ["config"]) => state.runtime_config().map(|config| config.api_payload()),
        ("POST", ["settings"]) => state
            .config
            .write()
            .map_err(|_| ApiError::internal("Configuration lock poisoned"))
            .and_then(|mut config| config.apply_settings(body)),
        ("GET", ["models"]) | ("POST", ["models", "query"]) => query_models(&state, body).await,
        ("POST", ["model", "reload"]) => reload_model(&state, body).await,
        _ => return None,
    };
    Some(result.map(|value| Json(value).into_response()))
}

fn provider(state: &AppState, body: &Value) -> ApiResult<(String, String)> {
    let config = state.runtime_config()?;
    let server = body
        .get("server_url")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .unwrap_or_else(|| config.str("lmstudio.base_url", "http://127.0.0.1:1234"));
    let url =
        url::Url::parse(&server).map_err(|_| ApiError::bad_request("Invalid LM Studio URL"))?;
    if !["http", "https"].contains(&url.scheme())
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err(ApiError::bad_request("Invalid LM Studio URL"));
    }
    if !is_local_server(&server) {
        return Err(ApiError::bad_request(
            "This local runtime requires a loopback LM Studio URL",
        ));
    }
    let key = body
        .get("api_key")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .unwrap_or_else(|| config.str("lmstudio.api_key", ""));
    Ok((server.trim_end_matches('/').to_owned(), key))
}

fn is_local_server(server: &str) -> bool {
    url::Url::parse(server)
        .ok()
        .and_then(|url| {
            url.host_str().map(|host| {
                let host = host.trim_matches(['[', ']']);
                host.eq_ignore_ascii_case("localhost")
                    || host
                        .parse::<std::net::IpAddr>()
                        .is_ok_and(|ip| ip.is_loopback())
            })
        })
        .unwrap_or(false)
}

fn lms_executable_path() -> PathBuf {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("C:\\Users\\Default"))
        .join(".cache")
        .join("lm-studio")
        .join("bin")
        .join(if cfg!(windows) { "lms.exe" } else { "lms" })
}

fn lms_load_args(model: &str, gpu_ratio: f64, context_length: u64) -> Vec<String> {
    vec![
        "load".to_owned(),
        model.to_owned(),
        "--gpu".to_owned(),
        format!("{gpu_ratio:.6}"),
        "--context-length".to_owned(),
        context_length.to_string(),
        "--yes".to_owned(),
    ]
}

async fn load_with_lms_cli(
    executable: &Path,
    model: &str,
    gpu_ratio: f64,
    context_length: u64,
) -> ApiResult<Value> {
    let executable = executable.to_owned();
    let args = lms_load_args(model, gpu_ratio, context_length);
    let output = tokio::task::spawn_blocking(move || {
        #[allow(unused_mut)]
        let mut command = Command::new(executable);
        command.args(args);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }
        command.output()
    })
    .await
    .map_err(|error| ApiError::internal(format!("LM Studio loader task failed: {error}")))?
    .map_err(|error| {
        ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            format!("LM Studio loader could not start: {error}"),
        )
    })?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
    if !output.status.success() {
        let detail = if stderr.is_empty() {
            stdout.clone()
        } else {
            stderr.clone()
        };
        return Err(ApiError::new(
            StatusCode::BAD_GATEWAY,
            format!(
                "LM Studio model load failed ({}): {}",
                output.status,
                detail.chars().take(2000).collect::<String>()
            ),
        ));
    }
    Ok(
        json!({"status":"success", "stdout":stdout.chars().take(4000).collect::<String>(), "stderr":stderr.chars().take(4000).collect::<String>()}),
    )
}

fn ws_load_creation(
    model: &str,
    gpu_ratio: f64,
    context_length: u64,
    flash_attention: bool,
) -> Value {
    json!({
        "modelKey": model,
        "loadConfigStack": {"layers": [{
            "layerName": "apiOverride",
            "config": {"fields": [
                {"key":"load.gpuSplitConfig", "value":{"strategy":"evenly","disabledGpus":[],"priority":[],"customRatio":[]}},
                {"key":"llm.load.llama.acceleration.offloadRatio", "value": gpu_ratio},
                {"key":"llm.load.contextLength", "value": context_length},
                {"key":"llm.load.llama.flashAttention", "value": flash_attention}
            ]}
        }]}
    })
}

fn sha1_digest(input: &[u8]) -> [u8; 20] {
    let mut h = [
        0x67452301u32,
        0xefcdab89,
        0x98badcfe,
        0x10325476,
        0xc3d2e1f0,
    ];
    let bit_len = (input.len() as u64) * 8;
    let mut msg = input.to_vec();
    msg.push(0x80);
    while (msg.len() % 64) != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&bit_len.to_be_bytes());
    for chunk in msg.chunks_exact(64) {
        let mut w = [0u32; 80];
        for i in 0..16 {
            w[i] = u32::from_be_bytes(chunk[i * 4..i * 4 + 4].try_into().unwrap());
        }
        for i in 16..80 {
            w[i] = (w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]).rotate_left(1);
        }
        let (mut a, mut b, mut c, mut d, mut e) = (h[0], h[1], h[2], h[3], h[4]);
        for (i, &wi) in w.iter().enumerate() {
            let (f, k) = match i {
                0..=19 => ((b & c) | ((!b) & d), 0x5a827999),
                20..=39 => (b ^ c ^ d, 0x6ed9eba1),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8f1bbcdc),
                _ => (b ^ c ^ d, 0xca62c1d6),
            };
            let t = a
                .rotate_left(5)
                .wrapping_add(f)
                .wrapping_add(e)
                .wrapping_add(k)
                .wrapping_add(wi);
            (e, d, c, b, a) = (d, c, b.rotate_left(30), a, t);
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
    }
    let mut out = [0u8; 20];
    for (i, value) in h.iter().enumerate() {
        out[i * 4..i * 4 + 4].copy_from_slice(&value.to_be_bytes());
    }
    out
}

async fn ws_write(stream: &mut TcpStream, payload: &[u8]) -> ApiResult<()> {
    ws_write_frame(stream, payload, 0x1).await
}

async fn ws_write_frame(stream: &mut TcpStream, payload: &[u8], opcode: u8) -> ApiResult<()> {
    let mut frame = vec![0x80 | (opcode & 0x0f)];
    let len = payload.len();
    if len < 126 {
        frame.push(0x80 | len as u8);
    } else if len <= u16::MAX as usize {
        frame.push(0x80 | 126);
        frame.extend_from_slice(&(len as u16).to_be_bytes());
    } else {
        frame.push(0x80 | 127);
        frame.extend_from_slice(&(len as u64).to_be_bytes());
    }
    let mask = [0x73, 0x41, 0x72, 0x6c];
    frame.extend_from_slice(&mask);
    frame.extend(payload.iter().enumerate().map(|(i, b)| b ^ mask[i % 4]));
    stream.write_all(&frame).await.map_err(|e| {
        ApiError::new(
            StatusCode::BAD_GATEWAY,
            format!("LM Studio WebSocket write failed: {e}"),
        )
    })
}

async fn ws_read(stream: &mut TcpStream) -> ApiResult<Vec<u8>> {
    let mut assembled = Vec::new();
    let mut fragmented = false;
    loop {
        let mut head = [0u8; 2];
        stream.read_exact(&mut head).await.map_err(|e| {
            ApiError::new(
                StatusCode::BAD_GATEWAY,
                format!("LM Studio WebSocket read failed: {e}"),
            )
        })?;
        let opcode = head[0] & 0x0f;
        if opcode == 0x8 {
            return Err(ApiError::new(
                StatusCode::BAD_GATEWAY,
                "LM Studio closed the SDK channel",
            ));
        }
        let fin = head[0] & 0x80 != 0;
        let masked = head[1] & 0x80 != 0;
        let mut len = (head[1] & 0x7f) as u64;
        if len == 126 {
            let mut b = [0u8; 2];
            stream
                .read_exact(&mut b)
                .await
                .map_err(|e| ApiError::internal(e.to_string()))?;
            len = u16::from_be_bytes(b) as u64;
        } else if len == 127 {
            let mut b = [0u8; 8];
            stream
                .read_exact(&mut b)
                .await
                .map_err(|e| ApiError::internal(e.to_string()))?;
            len = u64::from_be_bytes(b);
        }
        if len > 8 * 1024 * 1024 {
            return Err(ApiError::new(
                StatusCode::BAD_GATEWAY,
                "LM Studio WebSocket frame is too large",
            ));
        }
        let mut mask = [0u8; 4];
        if masked {
            stream
                .read_exact(&mut mask)
                .await
                .map_err(|e| ApiError::internal(e.to_string()))?;
        }
        let mut payload = vec![0u8; len as usize];
        stream
            .read_exact(&mut payload)
            .await
            .map_err(|e| ApiError::internal(e.to_string()))?;
        if masked {
            for (i, b) in payload.iter_mut().enumerate() {
                *b ^= mask[i % 4];
            }
        }
        if opcode == 0x9 {
            ws_write_frame(stream, &payload, 0xA).await?;
            continue;
        }
        if opcode == 0xA {
            continue;
        }
        if opcode == 0x1 || opcode == 0x2 {
            assembled.clear();
            assembled.extend_from_slice(&payload);
            fragmented = !fin;
            if fin {
                return Ok(assembled);
            }
            continue;
        }
        if opcode == 0x0 && fragmented {
            assembled.extend_from_slice(&payload);
            if fin {
                return Ok(assembled);
            }
            continue;
        }
        return Err(ApiError::new(
            StatusCode::BAD_GATEWAY,
            "LM Studio sent an invalid WebSocket continuation frame",
        ));
    }
}

async fn native_ws_load(
    server: &str,
    model: &str,
    gpu_ratio: f64,
    context_length: u64,
    flash_attention: bool,
    api_key: &str,
) -> ApiResult<Value> {
    let url = url::Url::parse(server)
        .map_err(|e| ApiError::bad_request(format!("Invalid LM Studio URL: {e}")))?;
    if url.scheme() != "http" {
        return Err(ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "Native LM Studio SDK transport requires an http loopback URL",
        ));
    }
    let host = url
        .host_str()
        .ok_or_else(|| ApiError::bad_request("LM Studio URL has no host"))?;
    let port = url.port_or_known_default().unwrap_or(80);
    let mut stream = TcpStream::connect((host, port)).await.map_err(|e| {
        ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            format!("LM Studio SDK connection failed: {e}"),
        )
    })?;
    // RFC 6455 requires Sec-WebSocket-Key to be the base64 encoding of exactly
    // 16 nonce bytes. UUID v4 supplies those bytes without adding a variable prefix.
    let key = BASE64.encode(uuid::Uuid::new_v4().as_bytes());
    let accept = BASE64.encode(sha1_digest(
        format!("{key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11").as_bytes(),
    ));
    let request = format!("GET /llm HTTP/1.1\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Extensions: permessage-deflate; client_max_window_bits\r\nHost: {host}:{port}\r\n\r\n");
    stream
        .write_all(request.as_bytes())
        .await
        .map_err(|e| ApiError::internal(e.to_string()))?;
    let mut response = Vec::new();
    let mut byte = [0u8; 1];
    while !response.windows(4).any(|w| w == b"\r\n\r\n") && response.len() < 8192 {
        stream.read_exact(&mut byte).await.map_err(|e| {
            ApiError::new(
                StatusCode::BAD_GATEWAY,
                format!("LM Studio handshake failed: {e}"),
            )
        })?;
        response.push(byte[0]);
    }
    let text = String::from_utf8_lossy(&response);
    if !text.starts_with("HTTP/1.1 101")
        || !text.to_ascii_lowercase().contains(&format!(
            "sec-websocket-accept: {}",
            accept.to_ascii_lowercase()
        ))
    {
        return Err(ApiError::new(
            StatusCode::BAD_GATEWAY,
            format!(
                "LM Studio SDK handshake rejected: {}",
                text.lines().next().unwrap_or("unknown")
            ),
        ));
    }
    let (client_identifier, client_passkey) = api_key
        .strip_prefix("sk-lm-")
        .and_then(|token| token.split_once(':'))
        .filter(|(identifier, passkey)| identifier.len() == 8 && passkey.len() == 20)
        .map(|(identifier, passkey)| (identifier.to_owned(), passkey.to_owned()))
        .unwrap_or_else(|| ("guest:arline".to_owned(), "arline".to_owned()));
    ws_write(&mut stream, serde_json::to_string(&json!({"authVersion":1,"clientIdentifier":client_identifier,"clientPasskey":client_passkey})).unwrap().as_bytes()).await?;
    let auth: Value = serde_json::from_slice(&ws_read(&mut stream).await?).map_err(|e| {
        ApiError::new(
            StatusCode::BAD_GATEWAY,
            format!("LM Studio auth response invalid: {e}"),
        )
    })?;
    if auth.get("success") != Some(&Value::Bool(true)) {
        return Err(ApiError::new(
            StatusCode::BAD_GATEWAY,
            format!("LM Studio SDK authentication failed: {auth}"),
        ));
    }
    let create = json!({"type":"channelCreate","endpoint":"loadModel","channelId":0,"creationParameter":ws_load_creation(model,gpu_ratio,context_length,flash_attention)});
    ws_write(
        &mut stream,
        serde_json::to_string(&create).unwrap().as_bytes(),
    )
    .await?;
    loop {
        let msg: Value = serde_json::from_slice(&ws_read(&mut stream).await?).map_err(|e| {
            ApiError::new(
                StatusCode::BAD_GATEWAY,
                format!("LM Studio SDK response invalid: {e}"),
            )
        })?;
        if msg.get("type").and_then(Value::as_str) == Some("channelSend")
            && msg.get("channelId") == Some(&Value::from(0))
        {
            let inner = msg.get("message").cloned().unwrap_or_default();
            match inner.get("type").and_then(Value::as_str) {
                Some("success") => return Ok(inner),
                Some("error") => {
                    return Err(ApiError::new(StatusCode::BAD_GATEWAY, inner.to_string()))
                }
                _ => {}
            }
        } else if msg.get("type").and_then(Value::as_str) == Some("channelError") {
            return Err(ApiError::new(StatusCode::BAD_GATEWAY, msg.to_string()));
        }
    }
}

async fn provider_json(request: reqwest::RequestBuilder) -> ApiResult<Value> {
    let response = request.send().await.map_err(|error| {
        ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            format!("LM Studio connection failed: {error}"),
        )
    })?;
    let status = response.status();
    let bytes = response
        .bytes()
        .await
        .map_err(|error| ApiError::new(StatusCode::BAD_GATEWAY, error.to_string()))?;
    if !status.is_success() {
        return Err(ApiError::new(
            StatusCode::BAD_GATEWAY,
            format!(
                "LM Studio returned HTTP {}: {}",
                status.as_u16(),
                String::from_utf8_lossy(&bytes)
                    .chars()
                    .take(1200)
                    .collect::<String>()
            ),
        ));
    }
    serde_json::from_slice(&bytes).map_err(|error| {
        ApiError::new(
            StatusCode::BAD_GATEWAY,
            format!("LM Studio returned invalid JSON: {error}"),
        )
    })
}

pub async fn query_models(state: &AppState, body: &Value) -> ApiResult<Value> {
    let (server, key) = provider(state, body)?;
    let mut request = state.client.get(format!("{server}/api/v1/models"));
    if !key.is_empty() {
        request = request.bearer_auth(key);
    }
    let result = provider_json(request).await?;
    let models = result
        .get("models")
        .or_else(|| result.get("data"))
        .and_then(Value::as_array)
        .ok_or_else(|| {
            ApiError::new(
                StatusCode::BAD_GATEWAY,
                "LM Studio model list has no models array",
            )
        })?;
    Ok(
        json!({"models": models.iter().filter(|model| model.get("type").and_then(Value::as_str)!=Some("embedding")).map(normalize_model).collect::<Vec<_>>()}),
    )
}

fn normalize_model(model: &Value) -> Value {
    let reasoning = model
        .pointer("/capabilities/reasoning")
        .or_else(|| model.get("reasoning"))
        .cloned()
        .unwrap_or(json!({}));
    let allowed = reasoning
        .get("allowed_options")
        .cloned()
        .unwrap_or(json!([]));
    let loaded = model
        .get("loaded_instances")
        .and_then(Value::as_array)
        .is_some_and(|items| !items.is_empty())
        || model
            .get("loaded")
            .and_then(Value::as_bool)
            .unwrap_or(false);
    json!({
        "key":model.get("key").or_else(||model.get("id")), "display_name":model.get("display_name").or_else(||model.get("key")).or_else(||model.get("id")),
        "loaded":loaded,"loaded_instances":model.get("loaded_instances").cloned().unwrap_or(json!([])),
        "max_context_length":model.get("max_context_length"),"reasoning":reasoning,"format":model.get("format"),
        "capabilities":{"provider":"lmstudio","context_window":model.get("max_context_length"),"streaming":true,
            "separate_reasoning_stream":allowed.as_array().is_some_and(|items|!items.is_empty()),"reasoning_modes":allowed,
            "vision":model.pointer("/capabilities/vision").and_then(Value::as_bool).unwrap_or(false),
            "sampling_controls":["temperature","top_p","top_k","min_p","repeat_penalty"]}
    })
}

async fn reload_model(state: &AppState, body: &Value) -> ApiResult<Value> {
    let config = state.runtime_config()?;
    let model = body
        .get("model")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .unwrap_or_else(|| config.str("lmstudio.model", ""));
    if model.is_empty() {
        return Err(ApiError::bad_request("Select a model first"));
    }
    let gpu_ratio = match body.get("gpu_ratio") {
        Some(value) => value
            .as_f64()
            .ok_or_else(|| ApiError::bad_request("gpu_ratio must be a number"))?,
        None => config.f64("model_load.gpu_ratio", 1.0),
    };
    if !gpu_ratio.is_finite() || !(0.0..=1.0).contains(&gpu_ratio) {
        return Err(ApiError::bad_request("gpu_ratio must be between 0 and 1"));
    }
    let context_length = match body.get("context_length") {
        Some(value) => value
            .as_u64()
            .ok_or_else(|| ApiError::bad_request("context_length must be a positive integer"))?,
        None => config.u64("model_load.context_length", 32768),
    };
    if context_length == 0 {
        return Err(ApiError::bad_request("context_length must be positive"));
    }
    let (server, key) = provider(state, body)?;
    if !is_local_server(&server) {
        return Err(ApiError::bad_request(
            "Native LM Studio loading is only supported for a local server",
        ));
    }
    let listed = query_models(state, body).await?;
    let existing = listed["models"].as_array().and_then(|models| {
        models
            .iter()
            .find(|item| item["key"].as_str() == Some(&model))
    });
    let mut unloaded = Vec::new();
    if let Some(instances) = existing.and_then(|item| item["loaded_instances"].as_array()) {
        for instance in instances {
            if let Some(id) = instance
                .get("id")
                .or_else(|| instance.get("instance_id"))
                .and_then(Value::as_str)
            {
                let mut request = state
                    .client
                    .post(format!("{server}/api/v1/models/unload"))
                    .json(&json!({"instance_id":id}));
                if !key.is_empty() {
                    request = request.bearer_auth(&key);
                }
                provider_json(request).await?;
                unloaded.push(id.to_owned());
            }
        }
    }
    let flash_attention = config.bool("model_load.flash_attention", true);
    let native_timeout = config.f64("lmstudio.timeout_seconds", 600.0).max(1.0);
    let (result, native_failure) = match tokio::time::timeout(
        Duration::from_secs_f64(native_timeout),
        native_ws_load(
            &server,
            &model,
            gpu_ratio,
            context_length,
            flash_attention,
            &key,
        ),
    )
    .await
    {
        Err(_) => {
            let native_error = ApiError::new(
                StatusCode::GATEWAY_TIMEOUT,
                format!("LM Studio SDK load timed out after {native_timeout:.0}s"),
            );
            let executable = lms_executable_path();
            if !executable.is_file() {
                return Err(native_error);
            }
            let diagnostic = native_error.message.clone();
            (
                load_with_lms_cli(&executable, &model, gpu_ratio, context_length).await?,
                Some(diagnostic),
            )
        }
        Ok(Ok(value)) => (value, None),
        Ok(Err(native_error)) => {
            // Keep the established CLI fallback for older LM Studio builds, but only report
            // flash attention as applied when the native SDK accepted the KV field.
            let executable = lms_executable_path();
            if !executable.is_file() {
                return Err(native_error);
            }
            let diagnostic = native_error.message.clone();
            (
                load_with_lms_cli(&executable, &model, gpu_ratio, context_length).await?,
                Some(diagnostic),
            )
        }
    };
    let native_applied = result.get("type").and_then(Value::as_str) == Some("success");
    Ok(
        json!({"ok":true,"result":{"action":"reloaded","model":model,"unloaded_instances":unloaded,"native_response":result,"native_failure":native_failure,
        "gpu_ratio":gpu_ratio,"context_length":context_length,
        "flash_attention":{"requested":flash_attention,"applied":native_applied,"reason":if native_applied {Value::Null} else {json!("LM Studio CLI fallback cannot apply flash-attention")}}},"config":config.api_payload()}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::net::TcpListener;
    #[test]
    fn model_metadata_retains_vision_and_reasoning_contract() {
        let value = normalize_model(
            &json!({"key":"local","loaded_instances":[{"id":"instance"}],"capabilities":{"vision":true,"reasoning":{"allowed_options":["off","on"]}}}),
        );
        assert_eq!(value["loaded"], true);
        assert_eq!(value["capabilities"]["vision"], true);
        assert_eq!(
            value["capabilities"]["reasoning_modes"],
            json!(["off", "on"])
        );
    }

    #[test]
    fn lms_load_args_forward_model_gpu_context_and_confirmation() {
        assert_eq!(
            lms_load_args("qwen/model", 0.5, 16384),
            vec![
                "load",
                "qwen/model",
                "--gpu",
                "0.500000",
                "--context-length",
                "16384",
                "--yes"
            ]
        );
    }

    #[test]
    fn only_loopback_servers_are_allowed_for_native_loading() {
        assert!(is_local_server("http://127.0.0.1:1234"));
        assert!(is_local_server("http://localhost:1234"));
        assert!(is_local_server("http://[::1]:1234"));
        assert!(!is_local_server("https://example.test"));
    }

    #[test]
    fn native_sdk_creation_forwards_all_requested_kv_fields() {
        let value = ws_load_creation("qwen/model", 0.5, 16384, true);
        assert_eq!(
            value["loadConfigStack"]["layers"][0]["layerName"],
            "apiOverride"
        );
        let fields = value["loadConfigStack"]["layers"][0]["config"]["fields"]
            .as_array()
            .unwrap();
        assert!(fields
            .iter()
            .any(|x| x["key"] == "llm.load.contextLength" && x["value"] == 16384));
        assert!(fields
            .iter()
            .any(|x| x["key"] == "llm.load.llama.acceleration.offloadRatio" && x["value"] == 0.5));
        assert!(fields
            .iter()
            .any(|x| x["key"] == "llm.load.llama.flashAttention" && x["value"] == true));
    }

    #[test]
    fn websocket_accept_sha1_matches_rfc_vector() {
        assert_eq!(
            BASE64.encode(sha1_digest(b"The quick brown fox jumps over the lazy dog")),
            "L9ThxnotKPzthJ7hu3bnORuT6xI="
        );
        assert_eq!(
            BASE64.encode(sha1_digest(
                b"dGhlIHNhbXBsZSBub25jZQ==258EAFA5-E914-47DA-95CA-C5AB0DC85B11",
            )),
            "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
        );
    }

    #[tokio::test]
    async fn native_sdk_transport_completes_authenticated_load_channel() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut request = Vec::new();
            let mut byte = [0u8; 1];
            while !request.windows(4).any(|w| w == b"\r\n\r\n") {
                stream.read_exact(&mut byte).await.unwrap();
                request.push(byte[0]);
            }
            let request = String::from_utf8(request).unwrap();
            let ws_key = request
                .lines()
                .find_map(|line| line.strip_prefix("Sec-WebSocket-Key: "))
                .unwrap()
                .trim();
            let accept = BASE64.encode(sha1_digest(
                format!("{ws_key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11").as_bytes(),
            ));
            stream
                .write_all(
                    format!(
                        "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n"
                    )
                    .as_bytes(),
                )
                .await
                .unwrap();
            // Exercise control-frame handling: the client must answer ping with pong.
            stream
                .write_all(&[0x89, 0x04, b'p', b'i', b'n', b'g'])
                .await
                .unwrap();
            let auth: Value = serde_json::from_slice(&ws_read(&mut stream).await.unwrap()).unwrap();
            assert_eq!(auth["authVersion"], 1);
            let auth_response = br#"{"success":true}"#;
            stream.write_all(&[0x01, 9]).await.unwrap();
            stream.write_all(&auth_response[..9]).await.unwrap();
            stream.write_all(&[0x80, 7]).await.unwrap();
            stream.write_all(&auth_response[9..]).await.unwrap();
            let create: Value =
                serde_json::from_slice(&ws_read(&mut stream).await.unwrap()).unwrap();
            assert_eq!(create["type"], "channelCreate");
            assert_eq!(create["endpoint"], "loadModel");
            assert_eq!(
                create["creationParameter"]["loadConfigStack"]["layers"][0]["config"]["fields"][2]
                    ["key"],
                "llm.load.contextLength"
            );
            assert_eq!(
                create["creationParameter"]["loadConfigStack"]["layers"][0]["config"]["fields"][3]
                    ["key"],
                "llm.load.llama.flashAttention"
            );
            ws_write(&mut stream, br#"{"type":"channelSend","channelId":0,"message":{"type":"success","info":{"modelKey":"qwen/model"}}}"#).await.unwrap();
        });
        let result = native_ws_load(
            &format!("http://{address}"),
            "qwen/model",
            0.5,
            16384,
            true,
            "",
        )
        .await
        .unwrap();
        assert_eq!(result["type"], "success");
        server.await.unwrap();
    }
}
