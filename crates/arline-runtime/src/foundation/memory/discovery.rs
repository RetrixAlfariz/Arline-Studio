//! Native discovery review/capture service.
//!
//! Discovery is deliberately provisional: capture writes observed propositions and
//! evidence instances, while canon/dismiss/reset are explicit user decisions.
use crate::{ApiError, ApiResult, AppState};
use rusqlite::params;
use serde_json::{json, Value};
use sha2::Digest;
use std::collections::HashMap;

fn now() -> String {
    chrono::Utc::now().to_rfc3339()
}
fn id(prefix: &str) -> String {
    format!("{prefix}-{}", uuid::Uuid::new_v4())
}
fn text(v: Option<&Value>) -> &str {
    v.and_then(Value::as_str).unwrap_or("")
}
fn filters(query: &HashMap<String, String>) -> Vec<(&'static str, Value)> {
    ["project_id", "world_id", "branch_id", "session_id"]
        .into_iter()
        .filter_map(|k| query.get(k).map(|v| (k, Value::String(v.clone()))))
        .collect()
}

fn enrich(row: &Value, state: &str) -> Value {
    let mut out = row.clone();
    if let Some(m) = out.as_object_mut() {
        m.insert("knowledge_state".into(), json!(state));
        m.insert(
            "provenance_state".into(),
            json!(if state == "dismissed" {
                "dismissed"
            } else {
                "supported"
            }),
        );
    }
    out
}

fn list(state: &AppState, query: &HashMap<String, String>) -> ApiResult<Value> {
    let include_dismissed = query
        .get("include_dismissed")
        .map(|x| x == "true")
        .unwrap_or(false);
    let mut rows = state
        .store
        .list("discovery_propositions", &filters(query))?;
    let mut counts = serde_json::Map::new();
    let mut items = Vec::new();
    for row in rows.drain(..) {
        let instances = state.store.query(
            "SELECT * FROM discovery_instances WHERE proposition_id=?",
            &[&row["id"].as_str().unwrap_or_default()],
        )?;
        let scope = serde_json::to_value(query).unwrap_or_else(|_| json!({}));
        let visible = instances
            .iter()
            .filter(|instance| {
                if instance["active"].as_i64().unwrap_or(0) == 0 {
                    return false;
                }
                let mut evidence = (*instance).clone();
                evidence["source_type"] = json!("turn");
                evidence["source_id"] = instance["source_turn_id"].clone();
                evidence["session_id"] = instance["source_session_id"].clone();
                evidence["source_recorded_at"] = instance["created_at"].clone();
                // Library browsing has no active session. Scope it directly
                // by project/world/branch; ScopeGate's session lineage would
                // otherwise reject every cross-session discovery. Active chat
                // queries still use the full lineage gate.
                if query.get("session_id").is_none() {
                    let same = |key: &str| {
                        query.get(key).is_none_or(|want| {
                            evidence
                                .get(key)
                                .and_then(Value::as_str)
                                .is_none_or(|got| got == want)
                        })
                    };
                    same("project_id") && same("world_id") && same("branch_id")
                } else {
                    super::scope_allowed(state, &evidence, &scope)
                }
            })
            .cloned()
            .collect::<Vec<_>>();
        let authority = row
            .get("authority_state")
            .and_then(Value::as_str)
            .unwrap_or("observed");
        if authority == "dismissed" && !include_dismissed {
            continue;
        }
        if visible.is_empty() && authority != "canon" {
            continue;
        }
        let mut item = enrich(
            &row,
            match authority {
                "canon" => "canon",
                "dismissed" => "dismissed",
                "reviewed" => "reviewed",
                _ => "detected",
            },
        );
        let support_count = visible.len();
        let qualified: Vec<&Value> = visible
            .iter()
            .filter(|x| x["qualifies_review"].as_i64().unwrap_or(0) != 0)
            .collect();
        let mut per_session: HashMap<String, std::collections::HashSet<String>> = HashMap::new();
        for instance in &qualified {
            let session = instance["source_session_id"]
                .as_str()
                .unwrap_or("")
                .to_owned();
            let key = format!(
                "{}:{}",
                instance["source_kind"].as_str().unwrap_or(""),
                instance["origin_turn_id"]
                    .as_str()
                    .or_else(|| instance["source_turn_id"].as_str())
                    .unwrap_or("")
            );
            per_session.entry(session).or_default().insert(key);
        }
        let reviewed = per_session.values().any(|x| x.len() >= 2);
        if authority != "canon" && authority != "dismissed" {
            item["knowledge_state"] = json!(if reviewed { "reviewed" } else { "detected" });
        }
        item["instances"] = json!(visible);
        item["support_count"] = json!(support_count);
        item["qualified_support_count"] = json!(qualified.len());
        item["inactive_support_count"] = json!(instances
            .iter()
            .filter(|x| x["active"].as_i64().unwrap_or(0) == 0)
            .count());
        item["provenance_state"] = json!(if instances
            .iter()
            .any(|x| x["active"].as_i64().unwrap_or(0) == 0)
        {
            "partial"
        } else {
            "active"
        });
        let key = item["knowledge_state"].as_str().unwrap_or("detected");
        let count = counts.get(key).and_then(Value::as_i64).unwrap_or(0);
        counts.insert(key.to_owned(), json!(count + 1));
        items.push(item);
    }
    Ok(json!({"items":items,"counts":counts,"store":{"propositions":items.len()}}))
}

#[derive(Clone)]
struct Candidate {
    kind: String,
    key: String,
    label: String,
    predicate: String,
    value: Value,
    operation: String,
    object_type: Option<String>,
    object_key: Option<String>,
    object_label: Option<String>,
    start: i64,
    end: i64,
    span: String,
}

fn candidates(input: &str) -> Vec<Candidate> {
    let mut out = Vec::new();
    let mut offset = 0usize;
    for sentence in input.split(['.', '!', '?', '\n']) {
        let s = sentence.trim();
        let start = input[offset..]
            .find(s)
            .map(|x| offset + x)
            .unwrap_or(offset);
        offset = start + s.len();
        let words: Vec<&str> = s.split_whitespace().collect();
        if words.len() < 3 {
            continue;
        }
        let label = words[0].trim_matches(|c: char| !c.is_alphanumeric() && c != '-' && c != '_');
        if label.len() < 2 || !label.chars().next().is_some_and(|c| c.is_uppercase()) {
            continue;
        }
        let key = format!(
            "char:{}",
            label
                .to_ascii_lowercase()
                .replace(|c: char| !c.is_ascii_alphanumeric(), "_")
        );
        let lower = s.to_ascii_lowercase();
        if let Some(pos) = words
            .iter()
            .position(|w| matches!(w.to_ascii_lowercase().as_str(), "is" | "was" | "adalah"))
        {
            let value = words[pos + 1..].join(" ");
            if !value.is_empty() {
                out.push(Candidate {
                    kind: "character".into(),
                    key: key.clone(),
                    label: label.into(),
                    predicate: "personality.descriptor".into(),
                    value: json!(value),
                    operation: "update".into(),
                    object_type: None,
                    object_key: None,
                    object_label: None,
                    start: start as i64,
                    end: (start + s.len()) as i64,
                    span: s.into(),
                });
            }
        }
        if let Some(pos) = words.iter().position(|w| {
            matches!(
                w.to_ascii_lowercase().as_str(),
                "lives" | "resides" | "tinggal"
            )
        }) {
            if pos + 2 < words.len() {
                let place = words[pos + 2].trim_matches(|c: char| !c.is_alphanumeric());
                if !place.is_empty() {
                    out.push(Candidate {
                        kind: "character".into(),
                        key: key.clone(),
                        label: label.into(),
                        predicate: "resides_at".into(),
                        value: json!(true),
                        operation: "relation".into(),
                        object_type: Some("location".into()),
                        object_key: Some(format!("loc:{}", place.to_ascii_lowercase())),
                        object_label: Some(place.into()),
                        start: start as i64,
                        end: (start + s.len()) as i64,
                        span: s.into(),
                    });
                }
            }
        }
        if lower.contains("is a ") || lower.contains("adalah ") {
            out.push(Candidate {
                kind: "character".into(),
                key: key.clone(),
                label: label.into(),
                predicate: "entity.exists".into(),
                value: json!({"entity_type":"character","label":label}),
                operation: "create".into(),
                object_type: None,
                object_key: None,
                object_label: None,
                start: start as i64,
                end: (start + s.len()) as i64,
                span: s.into(),
            });
        }
    }
    out
}

pub fn capture(state: &AppState, turn_id: &str, source_kind: &str) -> ApiResult<Value> {
    let turn = state
        .store
        .get("turns", turn_id)?
        .ok_or_else(|| ApiError::not_found("Turn not found"))?;
    let session_id = turn["session_id"].as_str().unwrap_or("").to_owned();
    let session = state
        .store
        .get("sessions", &session_id)?
        .unwrap_or(json!({}));
    let body = if source_kind == "user_prompt" {
        text(turn.get("user_prompt")).to_owned()
    } else if source_kind == "accepted_generation" || source_kind == "story" {
        text(turn.get("story")).to_owned()
    } else if source_kind == "user_edited_prose" {
        text(turn.get("edited_story")).to_owned()
    } else {
        format!(
            "{} {}",
            text(turn.get("user_prompt")),
            text(turn.get("story"))
        )
    };
    let revision = format!("{:x}", sha2::Sha256::digest(body.as_bytes()));
    let project = session.get("project_id").and_then(Value::as_str);
    let world = session.get("world_id").and_then(Value::as_str);
    let branch = session.get("branch_id").and_then(Value::as_str);
    let timestamp = now();
    // A changed source revision supersedes its previous evidence while an
    // identical revision remains idempotent.
    state.store.connection()?.execute(
        "UPDATE discovery_instances SET active=0,invalidation_reason='source_revision_changed',updated_at=? WHERE source_turn_id=? AND source_kind=? AND active=1 AND source_revision<>?",
        params![timestamp, turn_id, source_kind, revision],
    )?;
    let mut prop_ids = Vec::new();
    for (idx, c) in candidates(&body).into_iter().enumerate() {
        let pkey = format!(
            "{}:{}:{}:{}",
            project.unwrap_or(""),
            c.key,
            c.predicate,
            serde_json::to_string(&c.value).unwrap_or_default()
        );
        let pid = state
            .store
            .connection()?
            .query_row(
                "SELECT id FROM discovery_propositions WHERE proposition_key=?",
                [&pkey],
                |r| r.get::<_, String>(0),
            )
            .unwrap_or_else(|_| id("PROP"));
        state.store.connection()?.execute("INSERT INTO discovery_propositions(id,proposition_key,project_id,world_id,subject_type,subject_key,subject_label,predicate,value_json,object_type,object_key,object_label,operation,authority_state,temporal_state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'observed','current_or_unspecified',?,?) ON CONFLICT(proposition_key) DO UPDATE SET updated_at=excluded.updated_at",params![pid,pkey,project,world,c.kind,c.key,c.label,c.predicate,serde_json::to_string(&c.value).unwrap_or_default(),c.object_type,c.object_key,c.object_label,c.operation,timestamp,timestamp])?;
        let inst_key = format!("{}:{}:{}:{}", turn_id, source_kind, revision, idx);
        let qualifies = matches!(source_kind, "user_prompt" | "user_edited_prose");
        state.store.connection()?.execute("INSERT OR IGNORE INTO discovery_instances(id,instance_key,proposition_id,source_kind,source_session_id,source_turn_id,origin_session_id,origin_turn_id,source_revision,project_id,world_id,branch_id,source_segment,span_start,span_end,span_text,extraction_confidence,explicitness,qualifies_review,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'explicit',?,?,?,?)",params![id("INST"),inst_key,pid,source_kind,session_id,turn_id,turn["lineage"]["forked_from_session_id"].as_str().unwrap_or(&session_id),turn["lineage"]["forked_from_turn_id"].as_str().unwrap_or(turn_id),revision,project,world,branch,format!("sentence:{idx}"),c.start,c.end,c.span,0.8,if qualifies {1} else {0},1,timestamp,timestamp])?;
        // A differing value for the same scoped subject/predicate is a
        // continuity conflict, but never create duplicate pairs.
        let prior: Vec<(String, String)> = state.store.connection()?.prepare(
            "SELECT id,value_json FROM discovery_propositions WHERE project_id IS ? AND world_id IS ? AND subject_key=? AND predicate=? AND id<>? AND authority_state!='dismissed'"
        )?.query_map(params![project,world,c.key,c.predicate,pid], |r| Ok((r.get(0)?,r.get(1)?)))?.filter_map(Result::ok).collect();
        for (left, old_value) in prior {
            if old_value != serde_json::to_string(&c.value).unwrap_or_default() {
                let exists: i64 = state.store.connection()?.query_row(
                    "SELECT COUNT(*) FROM continuity_conflicts WHERE (left_proposition_id=? AND right_proposition_id=?) OR (left_proposition_id=? AND right_proposition_id=?)",
                    params![left,pid,pid,left], |r| r.get(0),
                )?;
                if exists == 0 {
                    state.store.connection()?.execute("INSERT INTO continuity_conflicts(id,project_id,world_id,branch_id,session_id,subject_key,predicate,left_proposition_id,right_proposition_id,source_turn_id,reason,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",params![id("CONFLICT"),project,world,branch,"",c.key,c.predicate,left,pid,turn_id,"different observed values","open",timestamp])?;
                }
            }
        }
        prop_ids.push(pid);
    }
    Ok(
        json!({"turn_id":turn_id,"source_kind":source_kind,"propositions":prop_ids.len(),"instances":prop_ids.len(),"proposition_ids":prop_ids,"auto_canon":false}),
    )
}

fn backfill(state: &AppState, query: &HashMap<String, String>) -> ApiResult<Value> {
    let mut turns = state.store.query(
        "SELECT t.* FROM turns t JOIN sessions s ON s.id=t.session_id WHERE (? IS NULL OR s.project_id=?) ORDER BY t.created_at",
        &[&query.get("project_id"), &query.get("project_id")],
    )?;
    if let Some(limit) = query.get("limit").and_then(|v| v.parse::<usize>().ok()) {
        turns.truncate(limit);
    }
    let source_kind = query
        .get("source_kind")
        .map(String::as_str)
        .unwrap_or("user_prompt");
    let mut reports = Vec::new();
    let mut propositions = 0i64;
    let mut instances = 0i64;
    for turn in turns {
        let Some(turn_id) = turn.get("id").and_then(Value::as_str) else {
            continue;
        };
        let report = capture(state, turn_id, source_kind)?;
        propositions += report["propositions"].as_i64().unwrap_or(0);
        instances += report["instances"].as_i64().unwrap_or(0);
        reports.push(report);
    }
    Ok(
        json!({"turns":reports.len(),"propositions":propositions,"instances":instances,"reports":reports,"auto_canon":false}),
    )
}

fn decision(state: &AppState, pid: &str, action: &str, body: &Value) -> ApiResult<Value> {
    let note = text(body.get("note"));
    let authority = match action {
        "canon" => "canon",
        "dismiss" => "dismissed",
        "reset" => "observed",
        _ => return Err(ApiError::bad_request("unknown discovery action")),
    };
    let prop = state
        .store
        .get("discovery_propositions", pid)?
        .ok_or_else(|| ApiError::not_found("Discovery proposition not found"))?;
    let ts = now();
    let con = state.store.connection()?;
    let tx = con.unchecked_transaction()?;
    tx.execute("UPDATE discovery_propositions SET authority_state=?,promoted_at=CASE WHEN ?='canon' THEN ? ELSE promoted_at END,updated_at=? WHERE id=?",params![authority,authority,ts,ts,pid])?;
    tx.execute("INSERT INTO discovery_decisions(id,proposition_id,action,note,created_at) VALUES(?,?,?,?,?)",params![id("DEC"),pid,action,note,ts])?;
    let mut materialized = Value::Null;
    if action == "canon" {
        let project = prop["project_id"]
            .as_str()
            .or_else(|| body.get("project_id").and_then(Value::as_str))
            .ok_or_else(|| ApiError::bad_request("project_id is required to promote discovery"))?;
        let world = prop["world_id"].as_str();
        let label = prop["subject_label"]
            .as_str()
            .unwrap_or("Discovered entity");
        let kind = prop["subject_type"].as_str().unwrap_or("lore");
        let family_id=tx.query_row("SELECT id FROM entity_families WHERE project_id=? AND lower(name)=lower(?) LIMIT 1",params![project,label],|r|r.get::<_,String>(0)).unwrap_or_else(|_|id("FAM"));
        tx.execute("INSERT OR IGNORE INTO entity_families(id,project_id,entity_type,name,slug,description,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",params![family_id,project,kind,label,label.to_ascii_lowercase().replace(' ',"-"),"Discovered from narrative evidence.",ts,ts])?;
        let mut resource_type = "entity_family".to_owned();
        let mut resource_id = family_id.clone();
        let variant_id = if let Some(w) = world {
            let v = id("VAR");
            tx.execute("INSERT OR IGNORE INTO entity_variants(id,family_id,world_id,display_name,canon_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",params![v,family_id,w,label,"canon",ts,ts])?;
            tx.query_row(
                "SELECT id FROM entity_variants WHERE family_id=? AND world_id=? LIMIT 1",
                params![family_id, w],
                |r| r.get::<_, String>(0),
            )
            .ok()
        } else {
            None
        };
        let w = world.unwrap_or("");
        if let Some(v) = variant_id.as_ref() {
            if prop["operation"].as_str() == Some("relation") {
                let object_key = prop["object_key"].as_str().unwrap_or("");
                let object_label = prop["object_label"].as_str().unwrap_or(object_key);
                let object_type = prop["object_type"].as_str().unwrap_or("lore");
                let object_family = tx.query_row("SELECT id FROM entity_families WHERE project_id=? AND lower(name)=lower(?) LIMIT 1",params![project,object_label],|r|r.get::<_,String>(0)).unwrap_or_else(|_|id("FAM"));
                tx.execute("INSERT OR IGNORE INTO entity_families(id,project_id,entity_type,name,slug,description,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",params![object_family,project,object_type,object_label,object_label.to_ascii_lowercase().replace(' ',"-"),"Discovered relation target.",ts,ts])?;
                let object_variant = tx
                    .query_row(
                        "SELECT id FROM entity_variants WHERE family_id=? AND world_id=? LIMIT 1",
                        params![object_family, w],
                        |r| r.get::<_, String>(0),
                    )
                    .unwrap_or_else(|_| id("VAR"));
                tx.execute("INSERT OR IGNORE INTO entity_variants(id,family_id,world_id,display_name,canon_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",params![object_variant,object_family,w,object_label,"canon",ts,ts])?;
                let rel_id = id("REL");
                tx.execute("INSERT INTO relationships(id,world_id,subject_variant_id,object_variant_id,relation_type,status,canon_status,attributes_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",params![rel_id,w,v,object_variant,prop["predicate"].as_str().unwrap_or("related_to"),"current","canon",json!({"value":prop["value_json"].as_str().unwrap_or("null"),"source":"discovery","source_id":pid}).to_string(),ts,ts])?;
                resource_type = "relationship".into();
                resource_id = rel_id;
            } else {
                resource_type = "fact".into();
                let fid = id("FACT");
                tx.execute("INSERT INTO canon_facts(id,project_id,world_id,owner_type,owner_id,path,value_json,status,authority,source_type,source_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",params![fid,project,world,"entity_variant",v,prop["predicate"].as_str().unwrap_or("discovery"),prop["value_json"].as_str().unwrap_or("null"),"canon","user_promoted","discovery_proposition",pid,ts,ts])?;
                resource_id = fid;
            }
        }
        tx.execute("UPDATE discovery_propositions SET materialized_resource_type=?,materialized_resource_id=?,target_resource_type='entity_family',target_resource_id=? WHERE id=?",params![resource_type,resource_id,family_id,pid])?;
        materialized =
            json!({"resource_type":resource_type,"resource_id":resource_id,"family_id":family_id});
    }
    tx.commit()?;
    Ok(
        json!({"id":pid,"authority_state":authority,"action":action,"note":note,"materialized":materialized}),
    )
}

pub fn handle(
    state: &AppState,
    method: &str,
    path: &[&str],
    query: &HashMap<String, String>,
    body: &Value,
) -> Option<ApiResult<Value>> {
    if path.first() != Some(&"discoveries") {
        return None;
    }
    let tail = &path[1..];
    let result = (|| -> ApiResult<Value> {
        match (method,tail) {
        ("GET",[])=>list(state,query), ("POST",["capture-turn",id])=>capture(state,id,query.get("source_kind").map(String::as_str).unwrap_or("user_prompt")),
        ("POST",["backfill"])=>backfill(state,query),
        ("GET",[id])=>match state.store.get("discovery_propositions",id)? { Some(v)=>Ok(enrich(&v,v["authority_state"].as_str().unwrap_or("detected"))), None=>Err(ApiError::not_found("Discovery proposition not found")) },
        ("POST",[id,"canon"])=>decision(state,id,"canon",body), ("POST",[id,"dismiss"])=>decision(state,id,"dismiss",body), ("POST",[id,"reset"])=>decision(state,id,"reset",body),
        ("POST",[pid,"edit"])=>if state.store.get("discovery_propositions",pid)?.is_none(){Err(ApiError::not_found("Discovery proposition not found"))}else{let value=body.get("value").cloned().unwrap_or(Value::Null); state.store.connection().and_then(|c|{c.execute("UPDATE discovery_propositions SET value_json=?,authority_state='reviewed',updated_at=? WHERE id=?",params![serde_json::to_string(&value).unwrap_or_default(),now(),pid])?; c.execute("INSERT INTO discovery_decisions(id,proposition_id,action,note,created_at) VALUES(?,?,?,?,?)",params![id("DEC"),pid,"edit",text(body.get("note")),now()]).map_err(|e|ApiError::internal(e.to_string()))}).map(|_|json!({"id":pid,"value":value,"authority_state":"reviewed"}))},
        ("GET",["continuity","status"])=>Ok(json!({"enabled":true,"open_conflicts":state.store.query("SELECT * FROM continuity_conflicts WHERE status='open'",&[])?.len()})),
        ("GET",["continuity","conflicts"])=>state.store.query("SELECT * FROM continuity_conflicts",&[]).map(|x|json!({"items":x})),
        ("POST",["continuity","conflicts",conflict_id,"resolve"])=>if state.store.get("continuity_conflicts",conflict_id)?.is_none(){Err(ApiError::not_found("Continuity conflict not found"))}else{state.store.connection().and_then(|c|{let ts=now(); let action=match text(body.get("action")){"dismiss"=>"dismissed",_=>"resolved"}; c.execute("UPDATE continuity_conflicts SET status=?,resolved_at=? WHERE id=?",params![action,ts,conflict_id])?; c.execute("INSERT INTO continuity_conflict_resolutions(id,conflict_id,action,from_proposition_id,to_proposition_id,note,created_at) VALUES(?,?,?,?,?,?,?)",params![format!("RESOLVE-{}",uuid::Uuid::new_v4()),conflict_id,action,body.get("from_proposition_id").and_then(Value::as_str),body.get("to_proposition_id").and_then(Value::as_str),text(body.get("note")),ts]).map_err(|e|ApiError::internal(e.to_string()))}).map(|_|json!({"id":conflict_id,"status":"resolved"}))},
        ("GET",["resource",typ,rid])=>state.store.query("SELECT * FROM discovery_propositions WHERE (subject_key=? OR object_key=?) AND authority_state!='dismissed'",&[&rid,&rid]).map(|x|json!({"resource_type":typ,"resource_id":rid,"items":x})),
        ("GET",["turn",id,"report"])=>state.store.query("SELECT * FROM discovery_instances WHERE source_turn_id=?",&[&id]).map(|x|json!({"turn_id":id,"instances":x})),
        _=>Err(ApiError::not_found("Discovery route not found")),
    }
    })();
    Some(result)
}
