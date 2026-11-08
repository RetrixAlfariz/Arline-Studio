//! Request-local narrative eligibility. Explicit references relax lineage only
//! for author inspection; they never override lifecycle, trust, time or POV.
use crate::{store::query_connection, ApiError, ApiResult, AppState};
use rusqlite::Connection;
use serde_json::Value;
use std::{cell::RefCell, collections::HashMap};

#[derive(Clone, Copy, Debug, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ContextLens {
    Author,
    Scene,
    Pov,
}
#[derive(Clone, Debug, Default, serde::Serialize, serde::Deserialize)]
pub struct NarrativeScope {
    pub project_id: Option<String>,
    pub world_id: Option<String>,
    pub branch_id: Option<String>,
    pub session_id: Option<String>,
    pub pov_variant_id: Option<String>,
    pub context_lens: Option<ContextLens>,
    pub story_order: Option<f64>,
    pub world_time: Option<Value>,
    pub allow_future_author_knowledge: Option<bool>,
    pub allow_scratch: Option<bool>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TimeOrder {
    Before,
    Equal,
    After,
    Incomparable,
}

fn decoded(value: &Value) -> Value {
    value
        .as_str()
        .and_then(|s| serde_json::from_str(s).ok())
        .unwrap_or_else(|| value.clone())
}
/// Numbers compare only with numbers, RFC3339 timestamps with timestamps.
/// Opaque fictional labels support equality, never lexical ordering.
pub fn compare_time(left: &Value, right: &Value) -> TimeOrder {
    let left = decoded(left);
    let right = decoded(right);
    let number = |v: &Value| {
        v.as_f64()
            .or_else(|| v.as_str()?.parse::<f64>().ok())
            .filter(|v| v.is_finite())
    };
    let ordering = if let (Some(a), Some(b)) = (number(&left), number(&right)) {
        Some(a.total_cmp(&b))
    } else if let (Some(a), Some(b)) = (left.as_str(), right.as_str()) {
        match (
            chrono::DateTime::parse_from_rfc3339(a),
            chrono::DateTime::parse_from_rfc3339(b),
        ) {
            (Ok(a), Ok(b)) => Some(a.cmp(&b)),
            _ if a == b => Some(std::cmp::Ordering::Equal),
            _ => None,
        }
    } else {
        None
    };
    match ordering {
        Some(std::cmp::Ordering::Less) => TimeOrder::Before,
        Some(std::cmp::Ordering::Equal) => TimeOrder::Equal,
        Some(std::cmp::Ordering::Greater) => TimeOrder::After,
        None => TimeOrder::Incomparable,
    }
}

pub(super) fn effective_body(state: &AppState, body: &Value) -> ApiResult<Value> {
    let mut body = body.clone();
    if let Some(session) = body["session_id"]
        .as_str()
        .and_then(|id| state.store.get("sessions", id).ok().flatten())
    {
        for key in ["project_id", "world_id", "branch_id"] {
            if !session[key].is_null() {
                if !body[key].is_null() && body[key] != session[key] {
                    return Err(ApiError::bad_request(format!(
                        "retrieval {key} conflicts with the active session"
                    )));
                }
                body[key] = session[key].clone();
            }
        }
    }
    if let Some(branch) = body["branch_id"]
        .as_str()
        .and_then(|id| state.store.get("world_branches", id).ok().flatten())
    {
        if body["world_id"].is_null() {
            body["world_id"] = branch["world_id"].clone();
        }
    }
    if let Some(world) = body["world_id"]
        .as_str()
        .and_then(|id| state.store.get("worlds", id).ok().flatten())
    {
        if body["project_id"].is_null() {
            body["project_id"] = world["project_id"].clone();
        } else if !world["project_id"].is_null() && body["project_id"] != world["project_id"] {
            let linked = state.store.query(
                "SELECT 1 FROM project_world_links WHERE project_id=? AND world_id=?",
                &[
                    &body["project_id"].as_str().unwrap_or_default(),
                    &body["world_id"].as_str().unwrap_or_default(),
                ],
            )?;
            if linked.is_empty() {
                return Err(ApiError::bad_request(
                    "retrieval world conflicts with its project",
                ));
            }
        }
    }
    let typed: NarrativeScope = serde_json::from_value(body.clone()).map_err(|_| {
        ApiError::bad_request("invalid narrative retrieval scope types or context lens")
    })?;
    if [
        &typed.project_id,
        &typed.world_id,
        &typed.branch_id,
        &typed.session_id,
        &typed.pov_variant_id,
    ]
    .iter()
    .filter_map(|v| v.as_ref())
    .any(|v| v.is_empty() || v.len() > 256)
    {
        return Err(ApiError::bad_request(
            "scope identifiers must contain 1..=256 bytes",
        ));
    }
    for (key, table, owner_key) in [
        ("branch_id", "world_branches", "world_id"),
        ("pov_variant_id", "entity_variants", "world_id"),
    ] {
        if let Some(owner) = body[key]
            .as_str()
            .and_then(|id| state.store.get(table, id).ok().flatten())
        {
            if let (Some(have), Some(want)) = (owner[owner_key].as_str(), body[owner_key].as_str())
            {
                if have != want {
                    return Err(ApiError::bad_request(
                        "retrieval branch/POV conflicts with its world",
                    ));
                }
            }
        }
    }
    Ok(body)
}

type RowCache = HashMap<(String, String), Option<Value>>;
pub(super) struct ScopeGate<'a> {
    pub connection: &'a Connection,
    pub body: &'a Value,
    cache: RefCell<RowCache>,
    branches: HashMap<String, Option<String>>,
    sessions: HashMap<String, Option<String>>,
    turn_sets: RefCell<HashMap<(String, String), Vec<String>>>,
    hidden: std::collections::HashSet<(String, String)>,
}
impl<'a> ScopeGate<'a> {
    pub fn new(connection: &'a Connection, body: &'a Value) -> ApiResult<Self> {
        let mut gate = Self {
            connection,
            body,
            cache: RefCell::new(HashMap::new()),
            branches: HashMap::new(),
            sessions: HashMap::new(),
            turn_sets: RefCell::new(HashMap::new()),
            hidden: Default::default(),
        };
        for row in query_connection(connection, "SELECT resource_type,resource_id FROM resource_lifecycle WHERE trashed_at IS NOT NULL OR archived_at IS NOT NULL", &[])? {
            gate.hidden.insert((row["resource_type"].as_str().unwrap_or_default().into(), row["resource_id"].as_str().unwrap_or_default().into()));
        }
        let mut current = body["branch_id"].as_str().map(str::to_owned);
        let mut cutoff: Option<String> = None;
        for _ in 0..128 {
            let Some(id) = current.take() else { break };
            if gate.branches.contains_key(&id) {
                break;
            }
            gate.branches.insert(id.clone(), cutoff.clone());
            let Some(row) = gate.get("world_branches", &id)? else {
                break;
            };
            if let Some(created) = row["created_at"].as_str() {
                cutoff = match cutoff {
                    Some(ref old)
                        if compare_time(
                            &Value::String(created.into()),
                            &Value::String(old.clone()),
                        ) != TimeOrder::Before =>
                    {
                        Some(old.clone())
                    }
                    _ => Some(created.into()),
                };
            }
            current = row["parent_branch_id"].as_str().map(str::to_owned);
        }
        let mut current = body["session_id"].as_str().map(str::to_owned);
        let mut cutoff = None;
        for _ in 0..256 {
            let Some(id) = current.take() else { break };
            if gate.sessions.contains_key(&id) {
                break;
            }
            gate.sessions.insert(id.clone(), cutoff.clone());
            let Some(row) = gate.get("sessions", &id)? else {
                break;
            };
            cutoff = row["forked_from_turn_id"].as_str().map(str::to_owned);
            current = row["parent_session_id"].as_str().map(str::to_owned);
            // An ancestor without a fork boundary cannot expose its whole history.
            if current.is_some() && cutoff.is_none() {
                break;
            }
        }
        Ok(gate)
    }
    fn get(&self, table: &str, id: &str) -> ApiResult<Option<Value>> {
        let key = (table.to_owned(), id.to_owned());
        if let Some(row) = self.cache.borrow().get(&key) {
            return Ok(row.clone());
        }
        let row = query_connection(
            self.connection,
            &format!("SELECT * FROM {table} WHERE id=?"),
            &[&id],
        )?
        .pop();
        self.cache.borrow_mut().insert(key, row.clone());
        Ok(row)
    }
    pub fn author_reference(&self, row: &Value) -> bool {
        self.body["context_lens"] == "author"
            && self.body["pov_variant_id"].is_null()
            && self.body["explicit_cross_scope_sources"]
                .as_array()
                .is_some_and(|items| {
                    items.iter().any(|item| {
                        item["source_type"].as_str().is_some()
                            && item["source_id"].as_str().is_some()
                            && item["source_type"] == row["source_type"]
                            && item["source_id"] == row["source_id"]
                    })
                })
    }
    /// SQL prefilter is conservative; evaluate still validates authoritative owners.
    pub fn prefilter(&self, alias: &str) -> (String, Vec<rusqlite::types::Value>) {
        use rusqlite::types::Value as Sql;
        let lifecycle=format!(" AND NOT EXISTS(SELECT 1 FROM resource_lifecycle l WHERE (l.trashed_at IS NOT NULL OR l.archived_at IS NOT NULL) AND ((l.resource_type=CASE {alias}.source_type WHEN 'canon_fact' THEN 'fact' WHEN 'chat_window' THEN 'turn' ELSE {alias}.source_type END AND l.resource_id={alias}.source_id) OR (l.resource_type='project' AND l.resource_id={alias}.project_id) OR (l.resource_type='world' AND l.resource_id={alias}.world_id) OR (l.resource_type='branch' AND l.resource_id={alias}.branch_id) OR (l.resource_type='session' AND l.resource_id={alias}.session_id)))");
        if self.body["context_lens"] == "author"
            && self.body["explicit_cross_scope_sources"]
                .as_array()
                .is_some_and(|v| !v.is_empty())
        {
            return (lifecycle, vec![]);
        }
        let mut sql = lifecycle;
        let mut values = vec![];
        for key in ["project_id", "world_id"] {
            if let Some(id) = self.body[key].as_str() {
                sql.push_str(&format!(" AND ({alias}.{key} IS NULL OR {alias}.{key}=?)"));
                values.push(Sql::Text(id.into()));
            }
        }
        let mut branches = self.branches.keys().cloned().collect::<Vec<_>>();
        branches.sort();
        sql.push_str(&format!(" AND ({alias}.branch_id IS NULL"));
        if !branches.is_empty() {
            sql.push_str(&format!(
                " OR {alias}.branch_id IN ({})",
                vec!["?"; branches.len()].join(",")
            ));
            values.extend(branches.into_iter().map(Sql::Text));
        }
        sql.push(')');
        (sql, values)
    }
    pub fn evaluate(&self, input: &Value) -> ApiResult<Result<Value, &'static str>> {
        let mut row = input.clone();
        if row["semantic_status"]
            .as_str()
            .is_some_and(|v| v != "active")
        {
            return Ok(Err("inactive"));
        }
        let kind = row["source_type"].as_str().unwrap_or_default().to_owned();
        let table = match kind.as_str() {
            "document" => Some("workspace_documents"),
            "entity_variant" => Some("entity_variants"),
            "canon_fact" => Some("canon_facts"),
            "relationship" => Some("relationships"),
            "timeline_event" => Some("timeline_events"),
            "turn" | "chat_window" => Some("turns"),
            _ => None,
        };
        let mut owners = vec![(
            if kind == "canon_fact" {
                "fact"
            } else if kind == "chat_window" {
                "turn"
            } else {
                &kind
            }
            .to_owned(),
            row["source_id"].as_str().unwrap_or_default().to_owned(),
        )];
        if let (Some(source_type), Some(source_id)) = (
            row["metadata"]["source_type"].as_str(),
            row["metadata"]["source_id"].as_str(),
        ) {
            let table = match source_type {
                "canon_fact" => Some("canon_facts"),
                "timeline_event" => Some("timeline_events"),
                "relationship" => Some("relationships"),
                "document" => Some("workspace_documents"),
                "entity_variant" => Some("entity_variants"),
                "turn" | "chat_window" => Some("turns"),
                _ => None,
            };
            if let Some(table) = table {
                if self.get(table, source_id)?.is_none() {
                    return Ok(Err("missing_provenance_source"));
                }
            }
            owners.push((
                if source_type == "canon_fact" {
                    "fact"
                } else {
                    source_type
                }
                .into(),
                source_id.into(),
            ));
        }
        if let Some(table) = table {
            let Some(mut source) =
                self.get(table, row["source_id"].as_str().unwrap_or_default())?
            else {
                return Ok(Err("missing_source"));
            };
            if source["archived"] == true || source["scratch_mode"] == true {
                return Ok(Err("lifecycle"));
            }
            if source["status"]
                .as_str()
                .is_some_and(|status| matches!(status, "rejected" | "superseded" | "deleted"))
            {
                return Ok(Err("inactive_source"));
            }
            if matches!(kind.as_str(), "turn" | "chat_window") {
                let Some(session) = self.get(
                    "sessions",
                    source["session_id"].as_str().unwrap_or_default(),
                )?
                else {
                    return Ok(Err("missing_owner"));
                };
                for key in ["project_id", "world_id", "branch_id"] {
                    source[key] = session[key].clone();
                }
            }
            if kind == "entity_variant" {
                let Some(family) = self.get(
                    "entity_families",
                    source["family_id"].as_str().unwrap_or_default(),
                )?
                else {
                    return Ok(Err("missing_owner"));
                };
                source["folder_id"] = family["folder_id"].clone();
                owners.push((
                    "entity_family".into(),
                    family["id"].as_str().unwrap_or_default().into(),
                ));
            }
            for key in [
                "project_id",
                "world_id",
                "branch_id",
                "session_id",
                "folder_id",
                "world_time",
                "world_time_json",
                "story_order",
                "authority",
                "trust_level",
                "semantic_class",
            ] {
                if let Some(value) = source.get(key) {
                    row[key] = value.clone();
                }
            }
            if kind == "canon_fact"
                && source["status"]
                    .as_str()
                    .is_some_and(|status| status != "canon")
            {
                row["authority"] = serde_json::json!("provisional");
            }
        }
        let mut folder = row["folder_id"].as_str().map(str::to_owned);
        let mut seen = std::collections::HashSet::new();
        while let Some(id) = folder {
            if !seen.insert(id.clone()) {
                return Ok(Err("owner_cycle"));
            }
            owners.push(("folder".into(), id.clone()));
            folder = self
                .get("workspace_folders", &id)?
                .and_then(|v| v["parent_id"].as_str().map(str::to_owned));
        }
        for (key, kind) in [
            ("project_id", "project"),
            ("world_id", "world"),
            ("branch_id", "branch"),
            ("session_id", "session"),
        ] {
            if let Some(id) = row[key].as_str() {
                owners.push((kind.into(), id.into()));
            }
        }
        if let (Some(kind), Some(id)) = (
            row["metadata"]["owner_type"].as_str(),
            row["metadata"]["owner_id"].as_str(),
        ) {
            owners.push((kind.into(), id.into()));
        }
        if owners.iter().any(|owner| self.hidden.contains(owner)) {
            return Ok(Err("lifecycle"));
        }
        if row["trust_level"] == "quarantined" {
            return Ok(Err("trust"));
        }
        let text = row["text"].as_str().unwrap_or_default().to_lowercase();
        if [
            "ignore all previous instructions",
            "system prompt",
            "developer message",
            "execute this command",
            "call the tool",
        ]
        .iter()
        .any(|s| text.contains(s))
        {
            return Ok(Err("instruction_hygiene"));
        }
        if row["authority"] == "scratch" && self.body["allow_scratch"] != true {
            return Ok(Err("scratch"));
        }
        let explicit = self.author_reference(&row);
        for key in ["project_id", "world_id"] {
            if let (Some(have), Some(want)) = (row[key].as_str(), self.body[key].as_str()) {
                if have != want && !explicit {
                    return Ok(Err("ownership"));
                }
            }
        }
        if !explicit {
            if let Some(branch) = row["branch_id"].as_str() {
                let Some(cutoff) = self.branches.get(branch) else {
                    return Ok(Err("branch"));
                };
                if let Some(cutoff) = cutoff {
                    if !matches!(
                        compare_time(&row["source_recorded_at"], &Value::String(cutoff.clone())),
                        TimeOrder::Before | TimeOrder::Equal
                    ) {
                        return Ok(Err("branch_cutoff"));
                    }
                }
            }
            if matches!(kind.as_str(), "turn" | "chat_window") {
                let Some(session) = row["session_id"].as_str() else {
                    return Ok(Err("session"));
                };
                let Some(cutoff) = self.sessions.get(session) else {
                    return Ok(Err("session"));
                };
                if let Some(cutoff) = cutoff {
                    let key = (session.to_owned(), cutoff.to_owned());
                    if !self.turn_sets.borrow().contains_key(&key) {
                        let rows = query_connection(
                            self.connection,
                            "SELECT id FROM turns WHERE session_id=? ORDER BY created_at,id",
                            &[&session],
                        )?;
                        let mut ids = vec![];
                        let mut found = false;
                        for turn in rows {
                            let id = turn["id"].as_str().unwrap_or_default().to_owned();
                            found = id == *cutoff;
                            ids.push(id);
                            if found {
                                break;
                            }
                        }
                        if !found {
                            ids.clear();
                        }
                        self.turn_sets.borrow_mut().insert(key.clone(), ids);
                    }
                    if !self.turn_sets.borrow()[&key]
                        .iter()
                        .any(|id| row["source_id"] == *id)
                    {
                        return Ok(Err("session_cutoff"));
                    }
                }
            }
        }
        let future = self.body["context_lens"] == "author"
            && self.body["allow_future_author_knowledge"] == true
            && self.body["pov_variant_id"].is_null();
        if !future {
            let have = row
                .get("world_time")
                .filter(|v| !v.is_null())
                .or_else(|| row.get("world_time_json").filter(|v| !v.is_null()));
            if let (Some(have), Some(want)) =
                (have, self.body.get("world_time").filter(|v| !v.is_null()))
            {
                match compare_time(have, want) {
                    TimeOrder::Before | TimeOrder::Equal => {}
                    TimeOrder::After => return Ok(Err("future_world_time")),
                    TimeOrder::Incomparable => return Ok(Err("incomparable_world_time")),
                }
            }
            if let (Some(have), Some(want)) = (
                row["story_order"].as_f64(),
                self.body["story_order"].as_f64(),
            ) {
                if have > want {
                    return Ok(Err("future_story_order"));
                }
            }
            if let Some(want) = self.body.get("world_time").filter(|v| !v.is_null()) {
                for (field, end) in [
                    ("valid_from_world_time_json", false),
                    ("valid_to_world_time_json", true),
                ] {
                    if let Some(time) = row["metadata"].get(field).filter(|v| !v.is_null()) {
                        let comparison = compare_time(time, want);
                        if (!end && !matches!(comparison, TimeOrder::Before | TimeOrder::Equal))
                            || (end && !matches!(comparison, TimeOrder::After))
                        {
                            return Ok(Err("temporal_interval"));
                        }
                    }
                }
            }
        }
        if let Some(pov) = self.body["pov_variant_id"].as_str() {
            if row["authority"] == "author_only" || row["semantic_class"] == "private" {
                return Ok(Err("pov"));
            }
            if kind == "epistemic" && row["metadata"]["character_variant_id"] != pov {
                return Ok(Err("pov"));
            }
            if let Some(visible) = row["metadata"]["visible_to"].as_array() {
                if !visible.iter().any(|id| id == pov) {
                    return Ok(Err("pov"));
                }
            }
        }
        Ok(Ok(row))
    }
}
