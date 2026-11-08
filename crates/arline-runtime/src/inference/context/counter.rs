use super::*;
use sha2::{Digest, Sha256};
fn unavailable(message: impl Into<String>) -> ApiError {
    ApiError::new(StatusCode::SERVICE_UNAVAILABLE,message).with_diagnostic(json!({"counting":{"state":"unavailable_or_untrusted"},"overflow_reason":"loaded_model_or_capacity_unavailable_or_changed"}))
}
use std::{process::Stdio, time::Duration};
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, ChildStdout, Command},
};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AccountingState {
    VerifiedModelCompatible,
    ConservativeEstimated,
    UnavailableOrUntrusted,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TokenCount {
    pub state: AccountingState,
    pub tokens: u64,
    pub method: String,
    pub template_allowance_tokens: u64,
    pub confidence: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct WriterModel {
    pub model_key: String,
    pub instance_id: String,
    pub context_length: u64,
    pub loaded_context_length: u64,
    pub identity: String,
    pub capacity_source: String,
}
async fn model(state: &AppState, cfg: &RuntimeConfig, body: &Value) -> ApiResult<WriterModel> {
    let requested = body["model"].as_str().unwrap_or_else(|| {
        cfg.value("lmstudio.model")
            .and_then(toml::Value::as_str)
            .unwrap_or_default()
    });
    let raw: Value = if crate::inference::engine::is_llama(cfg) {
        crate::inference::engine::ensure_loaded(state, cfg, requested).await?;
        crate::inference::engine::models_payload(state, cfg).await
    } else {
        let url = format!(
            "{}/api/v1/models",
            cfg.str("lmstudio.base_url", "http://127.0.0.1:1234")
                .trim_end_matches('/')
        );
        let mut request = state.client.get(url).timeout(Duration::from_secs(3));
        let key = cfg.str("lmstudio.api_key", "");
        if !key.is_empty() {
            request = request.bearer_auth(key);
        }
        let raw = request
            .send()
            .await
            .map_err(|_| unavailable("Loaded writer model information unavailable"))?;
        if !raw.status().is_success() {
            return Err(unavailable("Loaded writer context capacity unavailable; load the writer and use LM Studio's v1 model API"));
        }
        raw.json()
            .await
            .map_err(|_| unavailable("Invalid loaded-model metadata"))?
    };
    let mut matches = vec![];
    for m in raw["models"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|m| m["type"] == "llm")
    {
        for instance in m["loaded_instances"].as_array().into_iter().flatten() {
            let id = instance["id"].as_str().unwrap_or_default();
            let key = m["key"].as_str().unwrap_or_default();
            if !id.is_empty() && (requested.is_empty() || requested == id || requested == key) {
                matches.push((m, instance));
            }
        }
    }
    if matches.len() != 1 {
        return Err(unavailable("Writer must resolve to exactly one loaded instance; explicitly load/select it before generation"));
    }
    let (m, instance) = matches[0];
    let loaded=instance["config"]["context_length"].as_u64().filter(|n|*n>0).ok_or_else(||unavailable("Loaded context length is not reported; theoretical model maximum is not a safe substitute"))?;
    let requested_window = match body.get("context_length").filter(|v| !v.is_null()) {
        Some(v) => v
            .as_u64()
            .filter(|n| *n > 0)
            .ok_or_else(|| ApiError::bad_request("context_length must be a positive integer"))?,
        None => cfg.u64("model_load.context_length", loaded),
    };
    let window = loaded.min(requested_window);
    let identity=format!("sha256:{:x}",Sha256::digest(serde_json::to_vec(&json!({"key":m["key"],"instance_id":instance["id"],"load_config":instance["config"],"architecture":m["architecture"],"format":m["format"]})).unwrap_or_default()));
    Ok(WriterModel {
        model_key: m["key"].as_str().unwrap_or_default().into(),
        instance_id: instance["id"].as_str().unwrap_or_default().into(),
        context_length: window,
        loaded_context_length: loaded,
        identity,
        capacity_source: "reported_loaded_instance; request/config can only lower it".into(),
    })
}
struct Sdk {
    _child: Child,
    input: ChildStdin,
    output: BufReader<ChildStdout>,
    _permit: tokio::sync::OwnedSemaphorePermit,
}
/// Native conservative accounting works without a helper, model downloads,
/// embedding tokenizers or a new service. An optional trusted SDK subprocess
/// can provide model-compatible counts qualified for its loaded instance.
pub struct WriterTokenCounter {
    pub model: WriterModel,
    sdk: Option<Sdk>,
    base: String,
    /// llama-server engine: exact counts via its chat template + tokenizer.
    llama: Option<(reqwest::Client, String)>,
}
impl WriterTokenCounter {
    pub async fn resolve(state: &AppState, cfg: &RuntimeConfig, body: &Value) -> ApiResult<Self> {
        let model = model(state, cfg, body).await?;
        let sdk = if let Some(args) = cfg
            .value("context_compiler.sdk_command")
            .and_then(toml::Value::as_array)
        {
            let args = args
                .iter()
                .map(|v| {
                    v.as_str().ok_or_else(|| {
                        ApiError::bad_request("SDK command arguments must be strings")
                    })
                })
                .collect::<ApiResult<Vec<_>>>()?;
            let Some(executable) = args.first() else {
                return Err(ApiError::bad_request("SDK command cannot be empty"));
            };
            static SLOTS: std::sync::OnceLock<std::sync::Arc<tokio::sync::Semaphore>> =
                std::sync::OnceLock::new();
            let permit = SLOTS
                .get_or_init(|| std::sync::Arc::new(tokio::sync::Semaphore::new(4)))
                .clone()
                .try_acquire_owned();
            let mut command = Command::new(executable);
            command
                .args(&args[1..])
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .kill_on_drop(true);
            #[cfg(windows)]
            command.creation_flags(0x08000000);
            if let Ok(permit) = permit {
                if let Ok(mut child) = command.spawn() {
                    Some(Sdk {
                        input: child.stdin.take().expect("piped stdin"),
                        output: BufReader::new(child.stdout.take().expect("piped stdout")),
                        _child: child,
                        _permit: permit,
                    })
                } else {
                    None
                }
            } else {
                None
            }
        } else {
            None
        };
        Ok(Self {
            model,
            sdk,
            base: cfg.str("lmstudio.base_url", "http://127.0.0.1:1234"),
            llama: crate::inference::engine::is_llama(cfg)
                .then(|| (state.client.clone(), crate::inference::engine::base_url(cfg))),
        })
    }
    pub async fn confirm(
        &self,
        state: &AppState,
        cfg: &RuntimeConfig,
        body: &Value,
    ) -> ApiResult<()> {
        if model(state, cfg, body).await? != self.model {
            return Err(unavailable(
                "Writer model/context changed during compilation; retry with the current instance",
            ));
        }
        Ok(())
    }
    pub async fn count(&mut self, payload: &Value) -> ApiResult<TokenCount> {
        if !payload["input"].is_string() {
            return Err(ApiError::new(StatusCode::UNPROCESSABLE_ENTITY,"Image/multimodal token cost is unavailable; no inference was sent. Use text-only input until the writer's image accounting is qualified.").with_diagnostic(json!({"writer_model":self.model,"counting":{"state":"unavailable_or_untrusted"},"overflow_reason":"unknown_multimodal_cost"})));
        }
        if let Some((client, base)) = &self.llama {
            // A failed exact count falls through to the conservative estimate below.
            if let Ok(tokens) =
                crate::inference::engine::exact_input_tokens(client, base, payload).await
            {
                return Ok(TokenCount {
                    state: AccountingState::VerifiedModelCompatible,
                    tokens,
                    method: "llama_server_apply_template_tokenize".into(),
                    template_allowance_tokens: 0,
                    confidence: "exact: loaded instance's chat template and tokenizer".into(),
                });
            }
        }
        if let Some(sdk) = self.sdk.as_mut() {
            let exchange = async {
                let message = json!({"model":self.model.instance_id,"base_url":self.base,"context_length":self.model.context_length,"payload":payload});
                let mut bytes = serde_json::to_vec(&message).map_err(|_| ())?;
                bytes.push(b'\n');
                sdk.input.write_all(&bytes).await.map_err(|_| ())?;
                sdk.input.flush().await.map_err(|_| ())?;
                let mut line = String::new();
                let read = (&mut sdk.output)
                    .take(8193)
                    .read_line(&mut line)
                    .await
                    .map_err(|_| ())?;
                if read == 0 || read > 8192 {
                    return Err(());
                }
                let raw: Value = serde_json::from_str(&line).map_err(|_| ())?;
                if raw["instance_id"] != self.model.instance_id
                    || raw["loaded_context_length"]
                        .as_u64()
                        .is_none_or(|n| n < self.model.context_length)
                {
                    return Err(());
                }
                let count: TokenCount =
                    serde_json::from_value(raw["count"].clone()).map_err(|_| ())?;
                if count.state == AccountingState::UnavailableOrUntrusted {
                    return Err(());
                }
                Ok(count)
            };
            if let Ok(Ok(count)) = tokio::time::timeout(Duration::from_secs(10), exchange).await {
                return Ok(count);
            }
            self.sdk = None; // kill/reap on drop; conservative fallback is explicit.
        }
        Ok(Self::conservative(payload))
    }
    pub fn conservative(payload: &Value) -> TokenCount {
        // UTF-8 byte budget dominates ordinary byte-fallback tokenization; JSON
        // serialization also counts role/control fields. Additional allowance
        // covers unobserved template tokens. This remains an estimate, not exact.
        let tokens = serde_json::to_vec(payload)
            .map(|v| v.len() as u64)
            .unwrap_or(u64::MAX)
            .saturating_add(256);
        TokenCount{state:AccountingState::ConservativeEstimated,tokens,method:"serialized_utf8_bytes_plus_template_allowance".into(),template_allowance_tokens:256,confidence:"conservative estimate calibrated against provisioned writer SDK/usage; custom templates and unsupported tokenizers are not universally proven".into()}
    }
}
