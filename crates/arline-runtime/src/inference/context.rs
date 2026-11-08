//! R4: count complete writer payloads; never infer capacity from a model maximum.
mod counter;
#[cfg(test)]
mod tests;
use crate::{ApiError, ApiResult, AppState, RuntimeConfig};
use axum::http::StatusCode;
pub use counter::{AccountingState, TokenCount, WriterModel, WriterTokenCounter};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::time::Instant;

pub(crate) fn validate_config(cfg: &RuntimeConfig) -> ApiResult<()> {
    for key in [
        "context_compiler.safety_margin_tokens",
        "deliberation.context_length",
    ] {
        if let Some(value) = cfg.value(key) {
            if value
                .as_integer()
                .is_none_or(|n| n < i64::from(key != "context_compiler.safety_margin_tokens"))
            {
                return Err(ApiError::bad_request(format!(
                    "{key} must be a nonnegative/positive integer"
                )));
            }
        }
    }
    if let Some(value) = cfg.value("deliberation.model") {
        if value.as_str().is_none_or(str::is_empty) {
            return Err(ApiError::bad_request(
                "deliberation.model must be a nonempty model identifier",
            ));
        }
    }
    if let Some(value) = cfg.value("context_compiler.sdk_command") {
        let valid = value.as_array().is_some_and(|args| {
            !args.is_empty()
                && args.len() <= 16
                && args.iter().all(|v| {
                    v.as_str()
                        .is_some_and(|s| !s.is_empty() && s.len() <= 32768)
                })
                && args[0]
                    .as_str()
                    .is_some_and(|s| std::path::Path::new(s).is_absolute())
        });
        if !valid {
            return Err(ApiError::bad_request("context_compiler.sdk_command must contain an absolute executable path and up to 15 string arguments"));
        }
    }
    Ok(())
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ContextAuthority {
    System,
    CanonAndConstraints,
    UserRequest,
    Continuity,
    SelectedEvidence,
    SoftPlanner,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ContextItem {
    pub id: String,
    pub source_revision: Option<String>,
    pub content_type: String,
    pub authority: ContextAuthority,
    pub mandatory: bool,
    pub priority: usize,
    pub narrative_scope: Value,
    pub provenance: Value,
    #[serde(skip_serializing)]
    pub content: String,
    pub token_cost: Option<TokenCount>,
    pub decision_reason: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HistoryTurn {
    pub id: String,
    pub user: String,
    pub assistant: String,
}
impl HistoryTurn {
    fn render(&self) -> String {
        format!("User: {}\nAssistant: {}", self.user, self.assistant)
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ContextSelection {
    pub prompt: String,
    pub wcf: String,
    pub mode: String,
    pub aif: String,
    pub brief: String,
    pub unresolved: Vec<String>,
    pub deliberation: Value,
    pub evidence: Vec<Value>,
    pub history: Vec<HistoryTurn>,
    pub retrieval_state: Value,
    pub scope: Value,
    pub omitted_evidence: Vec<Value>,
    pub omitted_history_turns: usize,
    pub omitted_history_bytes: usize,
}
impl ContextSelection {
    pub fn from_analysis(body: &Value, analysis: &Value, history: Vec<HistoryTurn>) -> Self {
        let evidence = analysis["memory"].as_array().cloned().unwrap_or_default();
        let full = analysis["wcf"].as_str().unwrap_or_default();
        let wcf = if evidence.is_empty() {
            full
        } else {
            full.rsplit_once(crate::analysis::MEMORY_BLOCK_OPEN)
                .map(|(base, _)| base)
                .unwrap_or(full)
        }
        .to_owned();
        Self {
            prompt: body["prompt"].as_str().unwrap_or_default().into(),
            wcf,
            mode: body["input_mode"].as_str().unwrap_or("smart_hybrid").into(),
            aif: analysis["aif_core"].as_str().unwrap_or_default().into(),
            brief: analysis["narrative_brief"]["text"]
                .as_str()
                .unwrap_or_default()
                .into(),
            unresolved: analysis["unresolved"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|v| v.as_str().map(str::to_owned))
                .collect(),
            deliberation: analysis["deliberation"].clone(),
            evidence,
            history,
            retrieval_state: analysis["memory_diagnostic"].clone(),
            scope: json!({"project_id":body["project_id"],"world_id":body["world_id"],"branch_id":body["branch_id"],"session_id":body["session_id"],"pov_variant_id":body["pov_variant_id"]}),
            omitted_evidence: Vec::new(),
            omitted_history_turns: 0,
            omitted_history_bytes: 0,
        }
    }
    pub fn render(&self, kept: usize, history_start: usize) -> String {
        let wcf = crate::analysis::with_memory_block(&self.wcf, &self.evidence[..kept]);
        let context = crate::analysis::compose_input(
            &self.prompt,
            &wcf,
            &self.mode,
            &self.aif,
            &self.brief,
            &self.unresolved,
            Some(&self.deliberation),
        );
        if history_start >= self.history.len() {
            context
        } else {
            format!(
                "<CONVERSATION_HISTORY>\n{}\n</CONVERSATION_HISTORY>\n\n{context}",
                self.history[history_start..]
                    .iter()
                    .map(HistoryTurn::render)
                    .collect::<Vec<_>>()
                    .join("\n\n")
            )
        }
    }
    pub fn items(&self) -> Vec<ContextItem> {
        let mut items = vec![ContextItem {
            id: "mandatory-narrative".into(),
            source_revision: None,
            content_type: "narrative_context".into(),
            authority: ContextAuthority::CanonAndConstraints,
            mandatory: true,
            priority: 0,
            narrative_scope: self.scope.clone(),
            provenance: Value::Null,
            content: self.render(0, self.history.len()),
            token_cost: None,
            decision_reason: "mandatory narrative constraints and user request".into(),
        }];
        for (priority, row) in self.evidence.iter().enumerate() {
            items.push(ContextItem{id:row["id"].as_str().or_else(||row["source_id"].as_str()).unwrap_or_default().into(),source_revision:row["source_revision"].as_str().map(str::to_owned),content_type:"retrieved_passage".into(),authority:ContextAuthority::SelectedEvidence,mandatory:false,priority,narrative_scope:self.scope.clone(),provenance:json!({"source_type":row["source_type"],"source_id":row["source_id"],"authority":row["authority"],"trust_level":row["trust_level"]}),content:row["text"].as_str().unwrap_or_default().into(),token_cost:None,decision_reason:"R3 selected order; eligible for optional packing".into()});
        }
        items
    }
}
#[derive(Clone, Debug, Serialize)]
pub struct ContextBudget {
    pub loaded_context: u64,
    pub output_reserve: u64,
    pub safety_margin: u64,
    pub input_limit: u64,
}
#[derive(Clone, Debug, Serialize)]
#[serde(transparent)]
pub struct CompiledWriterContext {
    #[serde(skip)]
    pub payload: Value,
    pub context: String,
    #[serde(skip)]
    pub report: Value,
    #[serde(skip)]
    pub evidence: Vec<Value>,
    #[serde(skip)]
    pub selection: ContextSelection,
}
impl std::ops::Deref for CompiledWriterContext {
    type Target = str;
    fn deref(&self) -> &str {
        &self.context
    }
}

fn overflow(
    reason: &str,
    window: u64,
    reserve: u64,
    count: &TokenCount,
    model: &WriterModel,
    margin: u64,
) -> ApiError {
    ApiError::new(StatusCode::PAYLOAD_TOO_LARGE,format!("Context overflow: {reason}; input bound {}, effective window {window}, unchanged output reserve {reserve}. Reduce optional input or explicitly load a larger context.",count.tokens))
        .with_diagnostic(json!({"version":"r4.v1","writer_model":model,"counting":count,"context_window":window,"output_reserve_tokens":reserve,"safety_margin_tokens":margin,"final_input_tokens_or_bound":count.tokens,"remaining_context_tokens":0,"overflow_reason":reason}))
}
/// The builder is the actual provider serializer. Fragments are diagnostic only;
/// allocation decisions always count the reconstructed complete payload.
pub async fn compile(
    state: &AppState,
    cfg: &RuntimeConfig,
    body: &Value,
    selection: &ContextSelection,
    output_reserve: u64,
    build: impl Fn(&str) -> Value,
) -> ApiResult<CompiledWriterContext> {
    let started = Instant::now();
    let model_started = Instant::now();
    let mut counter = WriterTokenCounter::resolve(state, cfg, body).await?;
    let lookup_ms = model_started.elapsed().as_secs_f64() * 1000.0;
    let window = counter.model.context_length;
    let model_info = counter.model.clone();
    let margin = cfg
        .u64("context_compiler.safety_margin_tokens", 128)
        .max(window.div_ceil(20));
    let budget = ContextBudget {
        loaded_context: window,
        output_reserve,
        safety_margin: margin,
        input_limit: window.saturating_sub(output_reserve).saturating_sub(margin),
    };
    if selection.evidence.len() > 100 || selection.history.len() > 100 {
        return Err(ApiError::bad_request(
            "Context allocation supports at most 100 selected items and 100 history turns",
        ));
    }
    let mut count_ms = 0.0;
    let packing_started = Instant::now();
    let final_payload_count_ms;
    let (
        chosen,
        history_start,
        context,
        payload,
        cost,
        mandatory,
        original_cost,
        without_history,
        without_planner,
    ) = {
        let mut measure = async |context: &str| -> ApiResult<(Value, TokenCount)> {
            let mut payload = build(context);
            payload["model"] = json!(counter.model.instance_id);
            payload["context_length"] = json!(counter.model.loaded_context_length);
            let timer = Instant::now();
            let cost = counter.count(&payload).await?;
            count_ms += timer.elapsed().as_secs_f64() * 1000.0;
            Ok((payload, cost))
        };
        let mandatory_context = selection.render(0, selection.history.len());
        let (_, mandatory) = measure(&mandatory_context).await?;
        if mandatory.tokens > budget.input_limit {
            return Err(overflow(
                "mandatory Canon/state/request cannot fit",
                window,
                output_reserve,
                &mandatory,
                &model_info,
                margin,
            ));
        }
        let mut kept = selection.evidence.len();
        let mut history_start = 0;
        let mut context = selection.render(kept, history_start);
        let (_, mut cost) = measure(&context).await?;
        let original_cost = cost.tokens;
        while cost.tokens > budget.input_limit && kept > 0 {
            kept -= 1;
            context = selection.render(kept, history_start);
            (_, cost) = measure(&context).await?;
        }
        while cost.tokens > budget.input_limit && history_start < selection.history.len() {
            history_start += 1;
            context = selection.render(kept, history_start);
            (_, cost) = measure(&context).await?;
        }
        if cost.tokens > budget.input_limit {
            return Err(overflow(
                "final serialized payload cannot fit",
                window,
                output_reserve,
                &cost,
                &model_info,
                margin,
            ));
        }
        // Reconsider whole items removed from the tail. An oversized high-rank
        // passage must not prevent a smaller, still-authorized later item fitting.
        let prefix = kept;
        let mut chosen = (0..prefix).collect::<Vec<_>>();
        let mut packed = selection.clone();
        packed.evidence.truncate(prefix);
        for index in prefix..selection.evidence.len() {
            packed.evidence.push(selection.evidence[index].clone());
            let candidate = packed.render(packed.evidence.len(), history_start);
            let (_, candidate_cost) = measure(&candidate).await?;
            if candidate_cost.tokens <= budget.input_limit {
                chosen.push(index);
                context = candidate;
            } else {
                packed.evidence.pop();
            }
        }
        kept = chosen.len();
        let (_, without_history) = measure(&packed.render(kept, selection.history.len())).await?;
        let mut no_planner = selection.clone();
        no_planner.deliberation = json!({"status":"disabled"});
        let (_, without_planner) = measure(&no_planner.render(0, no_planner.history.len())).await?;
        // A helper can fail/downgrade while collecting diagnostic deltas. The
        // final decision must use the current method on the complete payload.
        let final_count_started = Instant::now();
        let (payload, cost) = measure(&context).await?;
        final_payload_count_ms = final_count_started.elapsed().as_secs_f64() * 1000.0;
        if cost.tokens > budget.input_limit {
            return Err(overflow(
                "final accounting changed; complete payload no longer fits",
                window,
                output_reserve,
                &cost,
                &model_info,
                margin,
            ));
        }
        (
            chosen,
            history_start,
            context,
            payload,
            cost,
            mandatory,
            original_cost,
            without_history,
            without_planner,
        )
    };
    // Metadata is not cached across calls/beats. A resize/reload before send is
    // detected; no theoretical max or request-supplied window can increase it.
    let packing_render_ms = (packing_started.elapsed().as_secs_f64() * 1000.0 - count_ms).max(0.0);
    let recheck_started = Instant::now();
    counter.confirm(state, cfg, body).await?;
    let model_revalidation_ms = recheck_started.elapsed().as_secs_f64() * 1000.0;
    let kept = chosen.len();
    let packed_evidence = chosen
        .iter()
        .map(|index| selection.evidence[*index].clone())
        .collect::<Vec<_>>();
    let included = packed_evidence
        .iter()
        .map(|row| row["id"].clone())
        .collect::<Vec<_>>();
    let mut excluded = selection.omitted_evidence.clone();
    excluded.extend(selection.evidence.iter().enumerate().filter(|(index,_)|!chosen.contains(index)).map(|(_,row)|json!({"id":row["id"],"source_id":row["source_id"],"reason":"context_budget"})));
    let history_dropped = selection.omitted_history_bytes
        + selection.history[..history_start]
            .iter()
            .map(|h| h.render().len())
            .sum::<usize>();
    let mut item_reports = selection.items();
    for item in &mut item_reports {
        let rendered = if matches!(item.authority, ContextAuthority::SelectedEvidence) {
            crate::analysis::with_memory_block("", &[selection.evidence[item.priority].clone()])
        } else {
            item.content.clone()
        };
        item.token_cost = Some(WriterTokenCounter::conservative(&json!({"input":rendered})));
        if !item.mandatory {
            item.decision_reason = if chosen.contains(&item.priority) {
                "included in stable R3 selected order"
            } else {
                "excluded: context_budget"
            }
            .into();
        }
    }
    for (id, content_type, authority, content) in [
        (
            "provider-system",
            "system_prompt",
            ContextAuthority::System,
            payload["system_prompt"]
                .as_str()
                .unwrap_or_default()
                .to_owned(),
        ),
        (
            "current-request",
            "user_and_beat_request",
            ContextAuthority::UserRequest,
            body["prompt"]
                .as_str()
                .unwrap_or(&selection.prompt)
                .to_owned(),
        ),
    ] {
        item_reports.push(ContextItem {
            id: id.into(),
            source_revision: None,
            content_type: content_type.into(),
            authority,
            mandatory: true,
            priority: 0,
            narrative_scope: selection.scope.clone(),
            provenance: Value::Null,
            token_cost: Some(WriterTokenCounter::conservative(&json!({"input":content}))),
            content,
            decision_reason: "mandatory; included in whole-payload validation".into(),
        });
    }
    for (priority, turn) in selection.history.iter().enumerate() {
        let content = turn.render();
        item_reports.push(ContextItem {
            id: turn.id.clone(),
            source_revision: None,
            content_type: "conversation_turn".into(),
            authority: ContextAuthority::Continuity,
            mandatory: false,
            priority: selection.history.len() - 1 - priority,
            narrative_scope: selection.scope.clone(),
            provenance: Value::Null,
            token_cost: Some(WriterTokenCounter::conservative(&json!({"input":content}))),
            content,
            decision_reason: if priority < history_start {
                "excluded as a complete oldest turn"
            } else {
                "included; higher retention priority than retrieval"
            }
            .into(),
        });
    }
    if selection.deliberation["status"] != "disabled" && !selection.deliberation.is_null() {
        let content = selection
            .deliberation
            .get("result")
            .cloned()
            .unwrap_or_else(|| json!({"scene_goal":selection.deliberation["scene_goal"]}))
            .to_string();
        item_reports.push(ContextItem {
            id: "soft-planner".into(),
            source_revision: None,
            content_type: "non_canon_planner_guidance".into(),
            authority: ContextAuthority::SoftPlanner,
            mandatory: true,
            priority: 0,
            narrative_scope: selection.scope.clone(),
            provenance: json!({"authority":"soft_non_canon"}),
            token_cost: Some(WriterTokenCounter::conservative(&json!({"input":content}))),
            content,
            decision_reason: "enabled planner guidance retained whole; never Canon authority"
                .into(),
        });
    }
    let report = json!({"version":"r4.v1","writer_model":counter.model,"counting":cost,"context_budget":budget,"context_window":window,"output_reserve_tokens":output_reserve,"safety_margin_tokens":margin,"mandatory_context_tokens":mandatory.tokens,"final_input_tokens_or_bound":cost.tokens,"remaining_context_tokens":window.saturating_sub(output_reserve).saturating_sub(margin).saturating_sub(cost.tokens),"input_limit_tokens":budget.input_limit,"estimated_input_tokens":cost.tokens,"system_prompt_tokens":0,"memory_items_kept":kept,"memory_items_dropped":excluded.len(),"included_evidence_ids":included,"excluded_evidence":excluded,"history_turns_kept":selection.history.len()-history_start,"history_turns_dropped":selection.omitted_history_turns+history_start,"history_bytes_dropped":history_dropped,"tokens_or_bound_saved":original_cost.saturating_sub(cost.tokens),"retrieval_state":selection.retrieval_state,"overflow_reason":Value::Null,"timings":{"model_lookup_ms":lookup_ms,"token_count_ms":count_ms,"total_compile_ms":started.elapsed().as_secs_f64()*1000.0},"diagnostic_costs":"whole payload counts include system, labels, provenance, separators and provider/template allowance; fragment counts are not additive"});
    let mut report = report;
    report["timings"]["packing_render_ms"] = json!(packing_render_ms);
    report["timings"]["final_payload_count_ms"] = json!(final_payload_count_ms);
    report["timings"]["model_revalidation_ms"] = json!(model_revalidation_ms);
    report["items"] = json!(item_reports);
    report["evidence_readiness"] = json!({
        "selection_state":if selection.evidence.is_empty() && selection.omitted_evidence.is_empty(){"retrieval_returned_no_selected_evidence"}else if kept==0{"selected_evidence_did_not_fit"}else{"selected_evidence_packed"},
        "retrieval_selected_items":selection.evidence.len()+selection.omitted_evidence.len(),
        "context_excluded_items":excluded.len(),
        "retrieval_reported_scope_exclusions":selection.retrieval_state["coverage"]["scope_exclusions"],
        "semantic_fallback":selection.retrieval_state["fallback"],
        "index_coverage_complete":selection.retrieval_state["coverage"]["complete"],
        "scope_observation":"R3 aggregate diagnostics only; SQL-pruned/private existence is not inferred from an empty selection"
    });
    report["component_accounting"] = json!({"method":"marginal whole-payload differences; not independent additive counts","selected_evidence":without_history.tokens as i128-mandatory.tokens as i128,"history":cost.tokens as i128-without_history.tokens as i128,"planner":mandatory.tokens as i128-without_planner.tokens as i128,"system_prompt_standalone_estimate":WriterTokenCounter::conservative(&json!({"input":payload["system_prompt"]})),"provider_template_allowance_tokens":cost.template_allowance_tokens,"system_prompt_tokens_compatibility_field":"zero additional reserve: system is included in the full serialized input count"});
    let mut next = selection.clone();
    next.evidence = packed_evidence.clone();
    next.history = selection.history[history_start..].to_vec();
    next.omitted_evidence = excluded;
    next.omitted_history_turns += history_start;
    next.omitted_history_bytes = history_dropped;
    Ok(CompiledWriterContext {
        payload,
        context,
        report,
        evidence: packed_evidence,
        selection: next,
    })
}

/// Planner and other provider calls that have no optional context items.
pub async fn validate_payload(
    state: &AppState,
    cfg: &RuntimeConfig,
    body: &Value,
    payload: &mut Value,
    reserve: u64,
) -> ApiResult<Value> {
    let mut counter = WriterTokenCounter::resolve(state, cfg, body).await?;
    payload["model"] = json!(counter.model.instance_id);
    payload["context_length"] = json!(counter.model.loaded_context_length);
    let count = counter.count(payload).await?;
    let window = counter.model.context_length;
    let margin = cfg
        .u64("context_compiler.safety_margin_tokens", 128)
        .max(window.div_ceil(20));
    if count.tokens.saturating_add(reserve).saturating_add(margin) > window {
        return Err(overflow(
            "provider payload cannot fit",
            window,
            reserve,
            &count,
            &counter.model,
            margin,
        ));
    }
    counter.confirm(state, cfg, body).await?;
    Ok(
        json!({"writer_model":counter.model,"counting":count,"output_reserve_tokens":reserve,"safety_margin_tokens":margin,"remaining_context_tokens":window-count.tokens-reserve-margin}),
    )
}

pub(crate) fn observe_usage(report: &mut Value, raw: &Value) {
    let actual = crate::inference::telemetry::normalize_provider_performance(raw).input_tokens;
    let counted = report["final_input_tokens_or_bound"]
        .as_u64()
        .or_else(|| report["counting"]["tokens"].as_u64());
    report["provider_usage_validation"] = json!({"actual_input_tokens":actual,"compiled_tokens_or_bound":counted,"within_bound":actual.zip(counted).map(|(actual,bound)|actual<=bound),"exact_match":actual.zip(counted).map(|(actual,bound)|actual==bound)});
    if actual
        .zip(counted)
        .is_some_and(|(actual, bound)| actual > bound)
        || (report["counting"]["state"] == "verified_model_compatible"
            && actual
                .zip(counted)
                .is_some_and(|(actual, bound)| actual != bound))
    {
        report["counting"]["state"] = json!("unavailable_or_untrusted");
        report["counting"]["confidence"] =
            json!("provider usage disagreed; requalification is required");
    }
}
