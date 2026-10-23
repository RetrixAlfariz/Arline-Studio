//! Canon workflow parity handlers.  This module owns the state-changing flows
//! that are intentionally absent from the generic CRUD dispatcher.
use crate::{foundation::FoundationStore, ApiError, ApiResult, AppState};
use rusqlite::{params, OptionalExtension};
use serde_json::{json, Map, Value};
use std::collections::HashMap;

fn id(prefix: &str) -> String {
    format!("{}-{}", prefix, uuid::Uuid::new_v4())
}
fn text(v: Option<&Value>) -> String {
    v.and_then(Value::as_str).unwrap_or("").trim().to_owned()
}
fn obj(v: &Value) -> ApiResult<&Map<String, Value>> {
    v.as_object()
        .ok_or_else(|| ApiError::bad_request("JSON object required"))
}

fn normalize_profile(input: &Value) -> ApiResult<Value> {
    let mut p = obj(input)?.clone();
    let defaults = [
        ("preferred_names", json!([])),
        ("personal_details", json!({})),
        ("creative_profile", json!({})),
        ("collaboration", json!({})),
        ("presence_defaults", json!({})),
        (
            "boundaries",
            json!({"prefer":[],"avoid":[],"ask_before":[]}),
        ),
        (
            "memory_policy",
            json!({"schema_version":2,"enabled":true,"learn_from_chats":true,"categories":{},"behavior":{"ask_before_sensitive":true,"forget_inactive_days":90,"prevent_personal_canon":true}}),
        ),
    ];
    for (key, value) in defaults {
        p.entry(key.to_owned()).or_insert(value);
    }
    if !p.get("display_name").is_some_and(Value::is_string) {
        p.insert("display_name".into(), json!(""));
    }
    if !p.get("about").is_some_and(Value::is_string) {
        p.insert("about".into(), json!(""));
    }
    Ok(Value::Object(p))
}

fn promote_presence(state: &AppState, body: &Value) -> ApiResult<Value> {
    let b = obj(body)?;
    let name = text(b.get("name"));
    let project = text(b.get("project_id"));
    let world = text(b.get("world_id"));
    if name.is_empty() || project.is_empty() || world.is_empty() {
        return Err(ApiError::bad_request(
            "project_id, world_id, and name are required",
        ));
    }
    let blueprint = b.get("blueprint").cloned().unwrap_or(json!({}));
    let family=state.store.insert("entity_families",json!({"id":id("FAM"),"project_id":project,"entity_type":"character","name":name,"description":"Promoted from a Story Lab Presence Blueprint.","shared_core":{"presence_blueprint":blueprint}}))?;
    let variant=state.store.insert("entity_variants",json!({"id":id("VAR"),"family_id":family["id"],"world_id":world,"branch_id":b.get("branch_id"),"display_name":name,"summary":"User-designed story Presence.","canon_status":"draft","attributes":{"presence_blueprint":blueprint}}))?;
    Ok(json!({"family":family,"variant":variant}))
}

fn promote_user_entity(state: &AppState, body: &Value) -> ApiResult<Value> {
    let b = obj(body)?;
    let name = text(b.get("name"));
    if name.is_empty() {
        return Err(ApiError::bad_request(
            "A display name is required before creating a self entity",
        ));
    }
    let details = b.get("personal_details").cloned().unwrap_or(json!({}));
    let mut projected = Map::new();
    if let Some(d) = details.as_object() {
        for (k, v) in d {
            if let Some(o) = v.as_object() {
                let vis = text(o.get("visibility"));
                if !o.get("sensitive").and_then(Value::as_bool).unwrap_or(false)
                    && (vis == "collaboration" || vis == "story_presence")
                {
                    if let Some(value) = o.get("value") {
                        projected.insert(k.clone(), value.clone());
                    }
                }
            }
        }
    }
    let snapshot = json!({"source":"personalization","display_name":name,"about":text(b.get("about")),"creative_profile":b.get("creative_profile").cloned().unwrap_or(json!({})),"personal_details":projected,"presence_defaults":b.get("presence_defaults").cloned().unwrap_or(json!({}))});
    let family=state.store.insert("entity_families",json!({"id":id("FAM"),"project_id":b.get("project_id"),"entity_type":"character","name":name,"description":text(b.get("about")),"shared_core":{"user_profile_projection":snapshot}}))?;
    let world = text(b.get("world_id"));
    let variant=state.store.insert("entity_variants",json!({"id":id("VAR"),"family_id":family["id"],"world_id":if world.is_empty(){Value::Null}else{json!(world)},"branch_id":b.get("branch_id"),"display_name":name,"summary":text(b.get("about")),"canon_status":"draft","attributes":{"user_profile_projection":snapshot}}))?;
    let mut profile =
        normalize_profile(&FoundationStore::from_store(state.store.clone()).user_profile()?)?;
    if let Some(p) = profile.as_object_mut() {
        p.insert("display_name".into(), json!(name));
        p.insert("about".into(), b.get("about").cloned().unwrap_or(json!("")));
        p.insert("presence_defaults".into(),json!({"mode":"linked_entity","identity_source":"self_entity","entity_family_id":family["id"],"entity_variant_id":variant["id"],"display_name":name}));
    }
    let saved = FoundationStore::from_store(state.store.clone()).save_user_profile(&profile)?;
    Ok(json!({"family":family,"variant":variant,"profile":saved}))
}

fn extract_profile(state: &AppState, input: &str) -> Value {
    let f = FoundationStore::from_store(state.store.clone());
    let mut out = f.extract_profile(input);
    let lower = input.to_ascii_lowercase();
    if out
        .get("display_name")
        .and_then(Value::as_str)
        .unwrap_or("")
        .is_empty()
    {
        for marker in ["my name is ", "nama saya ", "namaku "] {
            if let Some(pos) = lower.find(marker) {
                let value = input[pos + marker.len()..]
                    .split(['.', ',', '\n'])
                    .next()
                    .unwrap_or("")
                    .trim();
                if !value.is_empty() {
                    if let Some(o) = out.as_object_mut() {
                        o.insert("display_name".into(), json!(value));
                        if let Some(fields) = o.get_mut("fields").and_then(Value::as_array_mut) {
                            fields.push(json!({"key":"full_name","label":"Full name","value":value,"visibility":"private","confidence":0.98,"source":input,"sensitive":false,"included":true}));
                        }
                    }
                    break;
                }
            }
        }
    }
    out
}

fn state_proposals(body: &Value) -> ApiResult<Value> {
    let source = obj(body)?;
    let input = text(source.get("text"));
    if input.is_empty() {
        return Err(ApiError::bad_request("Text is empty"));
    }
    let mut entities = Vec::new();
    let mut relations = Vec::new();
    let mut claims = Vec::new();
    for sentence in input
        .split(['.', '!', '?', '\n'])
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        if let Some((left, right)) = sentence
            .split_once(" lives in ")
            .or_else(|| sentence.split_once(" tinggal di "))
        {
            let name = left.trim().trim_start_matches("Character ").trim();
            let place = right.trim();
            if !name.is_empty() && !place.is_empty() {
                entities.push(json!({"name":name,"kind":"character","confidence":0.9}));
                entities.push(json!({"name":place,"kind":"location","confidence":0.9}));
                relations.push(json!({"subject":name,"object":place,"relation_type":"lives_in","confidence":0.9}));
                continue;
            }
        }
        claims.push(json!({"text":sentence,"status":"discussion","canonical":false}));
    }
    Ok(
        json!({"source":{"project_id":source.get("project_id"),"world_id":source.get("world_id"),"branch_id":source.get("branch_id"),"session_id":source.get("session_id"),"turn_id":source.get("turn_id")},"entities":entities,"relations":relations,"claims":claims,"reference_resolutions":[],"patches":[],"events":[],"conflicts":[],"uncertainties":[]}),
    )
}

fn proposal_specs(prompt: &str) -> Vec<Value> {
    let mut out = Vec::new();
    for raw in prompt
        .split(['.', '!', '?', '\n'])
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        let low = raw.to_ascii_lowercase();
        let kind = if low.contains("location ")
            || low.contains("city ")
            || low.contains("town ")
            || low.contains("village ")
        {
            "location"
        } else if low.contains("plot") || low.contains("story") || low.contains("scene") {
            "plot"
        } else {
            "character"
        };
        let marker = [
            "named ",
            "called ",
            "bernama ",
            "karakter ",
            "location ",
            "city ",
            "kota ",
        ];
        let mut name = String::new();
        for m in marker {
            if let Some(pos) = low.find(m) {
                name = raw[pos + m.len()..]
                    .split_whitespace()
                    .take(3)
                    .collect::<Vec<_>>()
                    .join(" ");
                break;
            }
        }
        if name.is_empty() {
            name = raw.split_whitespace().take(9).collect::<Vec<_>>().join(" ");
        }
        name = name
            .trim_matches(|c: char| !c.is_alphanumeric() && c != '\'' && c != '-')
            .to_owned();
        if !name.is_empty() {
            out.push(json!({"kind":kind,"name":name,"content":raw,"operation":"create"}));
        }
    }
    out
}

fn stage(state: &AppState, body: &Value, proposal: Value) -> ApiResult<Value> {
    let b = obj(body)?;
    let project = text(b.get("project_id"));
    if project.is_empty() {
        return Err(ApiError::bad_request("project_id is required"));
    }
    let world = text(b.get("world_id"));
    let branch = text(b.get("branch_id"));
    let row = state.store.insert("staged_changes", json!({"id":id("CHANGE"),"project_id":project,"world_id":if world.is_empty(){Value::Null}else{json!(world)},"branch_id":if branch.is_empty(){Value::Null}else{json!(branch)},"session_id":b.get("session_id"),"turn_id":b.get("turn_id"),"owner_type":"story_lab_sheet","owner_id":proposal.get("name").and_then(Value::as_str).unwrap_or(""),"path":"story_lab_sheet","old_value":Value::Null,"proposed_value":proposal,"confidence":0.9,"status":"pending","source_text":text(b.get("source_text"))}))?;
    Ok(
        json!({"change":row,"proposal":row.get("proposed_value").cloned().unwrap_or(json!({})),"resource":Value::Null,"branch":Value::Null}),
    )
}

fn apply_one(state: &AppState, change_id: &str, body: &Value) -> ApiResult<Value> {
    let change = state
        .store
        .get("staged_changes", change_id)?
        .ok_or_else(|| ApiError::not_found("Sheet proposal not found"))?;
    let status = text(change.get("status"));
    if status != "pending" {
        return Err(ApiError::new(
            axum::http::StatusCode::CONFLICT,
            "Sheet proposal is already resolved",
        ));
    }
    let action = text(obj(body)?.get("action")).to_ascii_lowercase();
    if action == "reject" {
        let c = state
            .store
            .update("staged_changes", change_id, json!({"status":"rejected"}))?;
        return Ok(json!({"change":c,"resource":null,"branch":null}));
    }
    if action != "accept" && action != "branch" {
        return Err(ApiError::bad_request(
            "Action must be accept, reject, or branch",
        ));
    }
    let mut p = change.get("proposed_value").cloned().unwrap_or(json!({}));
    if let Some(extra) = obj(body)?.get("proposal") {
        if let (Some(a), Some(b)) = (p.as_object_mut(), extra.as_object()) {
            for (k, v) in b {
                a.insert(k.clone(), v.clone());
            }
        }
    }
    let po = obj(&p)?;
    let kind = text(po.get("kind"));
    let name = text(po.get("name"));
    let content = text(po.get("content"));
    if name.is_empty() || (kind != "relationship" && content.is_empty()) {
        return Err(ApiError::bad_request("Sheet name and content are required"));
    }
    let project = text(change.get("project_id"));
    let world = text(change.get("world_id"));
    let mut branch = if action == "branch" {
        text(obj(body)?.get("target_branch_id"))
    } else {
        text(change.get("branch_id"))
    };
    let mut created_branch = Value::Null;
    if action == "branch" && branch.is_empty() && !world.is_empty() {
        let branch_name =
            text(obj(body)?.get("branch_name")).if_empty(|| format!("{} proposal", name));
        let slug = branch_name.to_ascii_lowercase().replace(' ', "-");
        branch = id("BRANCH");
        created_branch = state.store.insert("world_branches", json!({"id":branch,"world_id":world,"name":branch_name,"slug":slug,"kind":"sandbox","canon_status":"what_if","description":format!("Story Lab sheet proposal: {}",name)}))?;
    }
    let branchv = if branch.is_empty() {
        Value::Null
    } else {
        json!(branch)
    };
    let resource=match kind.as_str() {
        "character"|"location" => {
            let family=state.store.insert("entity_families",json!({"id":id("FAM"),"project_id":"PROJ-WORLD-BIBLE","entity_type":kind,"name":name,"description":content,"shared_core":{}}))?;
            let variant = state.store.insert("entity_variants",json!({"id":id("VAR"),"family_id":family["id"],"world_id":world,"branch_id":branchv,"display_name":name,"summary":content,"canon_status":if action=="branch"{"what_if"}else{"draft"}}))?;
            if !project.is_empty() && state.store.get("projects", &project)?.is_some() {
                let _ = state.store.insert("project_manifest_refs", json!({"id":id("REF"),"project_id":project,"resource_type":"entity_family","resource_id":family["id"],"label":name,"priority":1}));
            }
            variant
        },
        "plot" => state.store.insert("workspace_documents",json!({"id":id("DOC"),"project_id":project,"world_id":if world.is_empty(){Value::Null}else{json!(world)},"branch_id":branchv,"title":name,"content":content,"document_type":"outline","status":"planned"}))?,
        "relationship" => {
            let subject = text(po.get("subject_variant_id"));
            let object = text(po.get("object_variant_id"));
            if subject.is_empty() || object.is_empty() { return Err(ApiError::bad_request("Relationship endpoints must resolve to two entity variants")); }
            state.store.insert("relationships", json!({"id":id("REL"),"world_id":world,"branch_id":branchv,"subject_variant_id":subject,"object_variant_id":object,"relation_type":text(po.get("relation_type")).if_empty(||"related_to".to_owned()),"status":"current","canon_status":if action=="branch"{"what_if"}else{"draft"},"attributes":{"source":"story_lab"}}))?
        },
        _ => return Err(ApiError::bad_request("Invalid sheet proposal kind")),
    };
    let c = state
        .store
        .update("staged_changes", change_id, json!({"status":"accepted"}))?;
    Ok(json!({"change":c,"resource":resource,"branch":created_branch}))
}

fn merge(state: &AppState, body: &Value, preview: bool) -> ApiResult<Value> {
    let b = obj(body)?;
    let src = text(b.get("source_family_id"));
    let dst = text(b.get("target_family_id"));
    if src.is_empty() || dst.is_empty() || src == dst {
        return Err(ApiError::bad_request(
            "Two distinct entity families are required",
        ));
    }
    let sf = state
        .store
        .get("entity_families", &src)?
        .ok_or_else(|| ApiError::not_found("source family not found"))?;
    let tf = state
        .store
        .get("entity_families", &dst)?
        .ok_or_else(|| ApiError::not_found("target family not found"))?;
    if sf.get("project_id") != tf.get("project_id") {
        return Err(ApiError::bad_request(
            "Entity families must share a project scope",
        ));
    }
    let sv = state
        .store
        .list("entity_variants", &[("family_id", json!(src))])?;
    let tv = state
        .store
        .list("entity_variants", &[("family_id", json!(dst))])?;
    if preview {
        return Ok(
            json!({"source":sf,"target":tf,"source_variants":sv,"target_variants":tv,"counts":{"variants":sv.len(),"relationships":state.store.query("SELECT * FROM relationships WHERE subject_variant_id IN (SELECT id FROM entity_variants WHERE family_id=?) OR object_variant_id IN (SELECT id FROM entity_variants WHERE family_id=?)",&[&src,&src])?.len()}}),
        );
    }
    let mut con = state.store.connection()?;
    let tx = con
        .transaction()
        .map_err(|e| ApiError::internal(e.to_string()))?;
    for row in &sv {
        let idv = text(row.get("id"));
        let world = text(row.get("world_id"));
        let branch = row.get("branch_id").and_then(Value::as_str);
        let existing:Option<String>=tx.query_row("SELECT id FROM entity_variants WHERE family_id=? AND world_id=? AND branch_id IS ?",params![dst,world,branch],|r|r.get(0)).optional().map_err(|e|ApiError::internal(e.to_string()))?;
        if let Some(target) = existing {
            tx.execute(
                "UPDATE relationships SET subject_variant_id=? WHERE subject_variant_id=?",
                params![target, idv],
            )
            .map_err(|e| ApiError::internal(e.to_string()))?;
            tx.execute(
                "UPDATE relationships SET object_variant_id=? WHERE object_variant_id=?",
                params![target, idv],
            )
            .map_err(|e| ApiError::internal(e.to_string()))?;
            tx.execute(
                "UPDATE canon_facts SET owner_id=? WHERE owner_id=?",
                params![target, idv],
            )
            .map_err(|e| ApiError::internal(e.to_string()))?;
            tx.execute("UPDATE resource_media SET resource_id=? WHERE resource_type='entity_variant' AND resource_id=?", params![target,idv]).map_err(|e| ApiError::internal(e.to_string()))?;
            tx.execute("UPDATE memory_chunks SET source_id=? WHERE source_type='entity_variant' AND source_id=?", params![target,idv]).map_err(|e| ApiError::internal(e.to_string()))?;
            tx.execute("DELETE FROM entity_variants WHERE id=?", [&idv])
                .map_err(|e| ApiError::internal(e.to_string()))?;
        } else {
            tx.execute(
                "UPDATE entity_variants SET family_id=? WHERE id=?",
                params![dst, idv],
            )
            .map_err(|e| ApiError::internal(e.to_string()))?;
        }
    }
    tx.execute(
        "UPDATE canon_facts SET owner_id=? WHERE owner_id=?",
        params![dst, src],
    )
    .map_err(|e| ApiError::internal(e.to_string()))?;
    // Foundation and memory ownership is resource-id based; keep those links
    // attached to the surviving family as part of the same transaction.
    tx.execute("UPDATE resource_media SET resource_id=? WHERE resource_type='entity_family' AND resource_id=?", params![dst,src]).map_err(|e| ApiError::internal(e.to_string()))?;
    tx.execute("UPDATE OR IGNORE workspace_favorites SET resource_id=? WHERE resource_type='entity_family' AND resource_id=?", params![dst,src]).map_err(|e| ApiError::internal(e.to_string()))?;
    tx.execute("UPDATE workspace_activity SET resource_id=? WHERE resource_type='entity_family' AND resource_id=?", params![dst,src]).map_err(|e| ApiError::internal(e.to_string()))?;
    tx.execute("UPDATE OR IGNORE workspace_collection_links SET resource_id=? WHERE resource_type='entity_family' AND resource_id=?", params![dst,src]).map_err(|e| ApiError::internal(e.to_string()))?;
    tx.execute("UPDATE OR IGNORE project_manifest_refs SET resource_id=? WHERE resource_type='entity_family' AND resource_id=?", params![dst,src]).map_err(|e| ApiError::internal(e.to_string()))?;
    tx.execute(
        "DELETE FROM workspace_favorites WHERE resource_type='entity_family' AND resource_id=?",
        [&src],
    )
    .map_err(|e| ApiError::internal(e.to_string()))?;
    tx.execute("DELETE FROM workspace_collection_links WHERE resource_type='entity_family' AND resource_id=?", [&src]).map_err(|e| ApiError::internal(e.to_string()))?;
    tx.execute(
        "DELETE FROM project_manifest_refs WHERE resource_type='entity_family' AND resource_id=?",
        [&src],
    )
    .map_err(|e| ApiError::internal(e.to_string()))?;
    tx.execute(
        "UPDATE memory_chunks SET source_id=? WHERE source_type='entity_family' AND source_id=?",
        params![dst, src],
    )
    .map_err(|e| ApiError::internal(e.to_string()))?;
    tx.execute("UPDATE discovery_propositions SET target_resource_id=? WHERE target_resource_type='entity_family' AND target_resource_id=?", params![dst,src]).map_err(|e| ApiError::internal(e.to_string()))?;
    tx.execute("UPDATE OR IGNORE resource_aliases SET resource_id=? WHERE resource_type='entity_family' AND resource_id=?", params![dst,src]).map_err(|e| ApiError::internal(e.to_string()))?;
    tx.execute(
        "DELETE FROM resource_aliases WHERE resource_type='entity_family' AND resource_id=?",
        [&src],
    )
    .map_err(|e| ApiError::internal(e.to_string()))?;
    tx.execute("DELETE FROM entity_families WHERE id=?", [&src])
        .map_err(|e| ApiError::internal(e.to_string()))?;
    tx.commit().map_err(|e| ApiError::internal(e.to_string()))?;
    state
        .store
        .get("entity_families", &dst)?
        .ok_or_else(|| ApiError::internal("merged family disappeared"))
}

fn quick(state: &AppState, body: &Value, preview: bool) -> ApiResult<Value> {
    let b = obj(body)?;
    let raw = text(b.get("text"));
    if raw.is_empty() {
        return Err(ApiError::bad_request("Describe what you want to create"));
    }
    let forced = text(b.get("forced_kind"));
    let mut data = parse_quick_text(&raw, (!forced.is_empty()).then_some(forced.as_str()))?;
    if let Some(name) = b
        .get("name")
        .and_then(Value::as_str)
        .filter(|v| !v.trim().is_empty())
    {
        data["name"] = json!(name.trim());
    }
    if let Some(entity_type) = b.get("entity_type").and_then(Value::as_str) {
        data["entity_type"] = json!(entity_type);
    }
    if let Some(description) = b.get("description") {
        data["description"] = description.clone();
    }
    let mut matches = Vec::new();
    if data["kind"] == "entity" {
        let name = text(data.get("name"));
        let entity_type = text(data.get("entity_type"));
        for family in state.store.list("entity_families", &[])? {
            let label = text(family.get("name"));
            if !label.is_empty()
                && (entity_type.is_empty() || family["entity_type"] == entity_type)
                && (label.eq_ignore_ascii_case(&name)
                    || label
                        .to_ascii_lowercase()
                        .contains(&name.to_ascii_lowercase())
                    || name
                        .to_ascii_lowercase()
                        .contains(&label.to_ascii_lowercase()))
            {
                matches.push(json!({"type":"entity_family","id":family["id"],"label":label,"entity_type":family["entity_type"],"score":if label.eq_ignore_ascii_case(&name){1.0}else{0.7},"alias":Value::Null}));
            }
        }
        let foundation = FoundationStore::from_store(state.store.clone());
        for alias in foundation.alias_matches(&name, 20)? {
            if alias["resource_type"] != "entity_family" {
                continue;
            }
            let resource_id = text(alias.get("resource_id"));
            if let Some(family) = state.store.get("entity_families", &resource_id)? {
                let alias_name = text(alias.get("alias"));
                let score = if alias_name.eq_ignore_ascii_case(&name) {
                    1.0
                } else {
                    0.7
                };
                if !matches.iter().any(|item| item["id"] == family["id"]) {
                    matches.push(json!({"type":"entity_family","id":family["id"],"label":family["name"],"entity_type":family["entity_type"],"score":score,"alias":alias_name}));
                }
            }
        }
    }
    data["possible_matches"] = json!(matches);
    if preview {
        return Ok(data);
    }
    let kind = text(data.get("kind"));
    let name = text(data.get("name"));
    let description = text(data.get("description"));
    let resource = match kind.as_str() {
        "project" => state.store.insert("projects", json!({"id":id("PROJ"),"name":name,"description":description}))?,
        "world" => state.store.insert("worlds", json!({"id":id("WORLD"),"project_id":"PROJ-WORLD-BIBLE","name":name,"description":description,"canon_status":"draft","inheritance_mode":"none"}))?,
        "folder" => { let project=text(b.get("project_id")); if project.is_empty(){return Err(ApiError::bad_request("A project is required to create a folder"));} state.store.insert("workspace_folders",json!({"id":id("FOLDER"),"project_id":project,"name":name,"kind":"mixed"}))? }
        "document" => { let project=text(b.get("project_id")); if project.is_empty(){return Err(ApiError::bad_request("A project is required to create a document"));} let mut doc=json!({"id":id("DOC"),"project_id":project,"title":name,"content":"","document_type":data.get("document_type").cloned().unwrap_or(json!("scene")),"status":"planned"}); for key in ["world_id","branch_id","folder_id"] { if let Some(v)=b.get(key) { doc[key]=v.clone(); } } state.store.insert("workspace_documents",doc)? }
        _ => { let family=state.store.insert("entity_families",json!({"id":id("FAM"),"project_id":"PROJ-WORLD-BIBLE","folder_id":b.get("folder_id"),"entity_type":data["entity_type"],"name":name,"description":description,"shared_core":data["shared_core"]}))?; let world=text(b.get("world_id")).if_empty(||"WORLD-BIBLE-MAIN".to_owned()); let branch=text(b.get("branch_id")); let variant=state.store.insert("entity_variants",json!({"id":id("VAR"),"family_id":family["id"],"world_id":world,"branch_id":if branch.is_empty(){Value::Null}else{json!(branch)},"display_name":name,"summary":description,"canon_status":"draft","attributes":data["attributes"]}))?; if let Some(project)=b.get("project_id").and_then(Value::as_str).filter(|v| !v.is_empty()) { if state.store.get("projects", project)?.is_some() { let _=state.store.insert("project_manifest_refs",json!({"id":id("REF"),"project_id":project,"resource_type":"entity_family","resource_id":family["id"],"label":name,"priority":1})); } } return Ok(json!({"kind":"entity","resource":family,"variant":variant,"preview":data})); }
    };
    Ok(json!({"kind":kind,"resource":resource,"preview":data}))
}

fn parse_quick_text(raw: &str, forced: Option<&str>) -> ApiResult<Value> {
    let raw = raw.split_whitespace().collect::<Vec<_>>().join(" ");
    let mut rest = raw.clone();
    let mut kind = forced.unwrap_or("").to_owned();
    let mut detected = Vec::new();
    if kind.is_empty() {
        for (candidate, prefixes) in [
            (
                "project",
                &["project ", "project:", "proyek ", "proyek:"][..],
            ),
            ("world", &["world ", "world:", "dunia ", "dunia:"][..]),
            ("folder", &["folder ", "folder:"][..]),
            (
                "document",
                &["document ", "document:", "dokumen ", "dokumen:"][..],
            ),
            ("entity", &["entity ", "entity:", "sheet ", "sheet:"][..]),
        ] {
            if let Some(prefix) = prefixes
                .iter()
                .find(|p| raw.to_ascii_lowercase().starts_with(*p))
            {
                kind = candidate.to_owned();
                rest = raw[prefix.len()..].trim().to_owned();
                detected.push(format!("explicit {candidate}"));
                break;
            }
        }
    }
    let lower = rest.to_ascii_lowercase();
    if kind.is_empty() {
        kind = if [
            "scene",
            "chapter",
            "bab",
            "outline",
            "draft",
            "note",
            "catatan",
            "lore note",
        ]
        .iter()
        .any(|h| lower.contains(h))
        {
            "document"
        } else {
            "entity"
        }
        .to_owned();
    }
    if ["project", "world", "folder"].contains(&kind.as_str()) {
        return Ok(
            json!({"kind":kind,"entity_type":Value::Null,"name":title_like(&rest),"description":"","confidence":0.99,"attributes":{},"shared_core":{},"document_type":Value::Null,"warnings":[],"detected":detected,"possible_matches":[]}),
        );
    }
    if kind == "document" {
        let document_type = if lower.contains("chapter") || lower.contains("bab") {
            "chapter"
        } else if lower.contains("outline") {
            "outline"
        } else if lower.contains("note") || lower.contains("catatan") {
            "note"
        } else {
            "scene"
        };
        detected.push(document_type.to_owned());
        return Ok(
            json!({"kind":"document","entity_type":Value::Null,"name":title_like(&rest),"description":"","confidence":0.9,"attributes":{},"shared_core":{},"document_type":document_type,"warnings":[],"detected":detected,"possible_matches":[]}),
        );
    }
    let (entity_type, confidence, cue) = if [
        "apartemen",
        "apartment",
        "rumah",
        "house",
        "forest",
        "hutan",
        "castle",
        "istana",
        "kamar",
        "room",
        "city",
        "kota",
    ]
    .iter()
    .any(|h| lower.contains(h))
    {
        ("location", 0.9, "location cues")
    } else if [
        "pedang", "sword", "blade", "item", "cincin", "ring", "book", "buku",
    ]
    .iter()
    .any(|h| lower.contains(h))
    {
        ("item", 0.86, "item cues")
    } else if [
        "guild",
        "organisasi",
        "organization",
        "faction",
        "company",
        "kingdom",
        "kerajaan",
    ]
    .iter()
    .any(|h| lower.contains(h))
    {
        ("organization", 0.84, "organization cues")
    } else if ["rule", "aturan", "hukum", "magic system", "sistem sihir"]
        .iter()
        .any(|h| lower.contains(h))
    {
        ("world_rule", 0.86, "world-rule cues")
    } else if ["character", "karakter", "tokoh", "orang", "person", "npc"]
        .iter()
        .any(|h| lower.contains(h))
    {
        ("character", 0.82, "character cues")
    } else {
        ("character", 0.58, "")
    };
    if !cue.is_empty() {
        detected.push(cue.to_owned());
    }
    let shared = if entity_type == "character" {
        json!({"identity":{"name":rest}})
    } else if entity_type == "item" {
        json!({"kind":"item"})
    } else if entity_type == "organization" {
        json!({"kind":"organization"})
    } else if entity_type == "location" {
        json!({"kind":"location"})
    } else {
        json!({})
    };
    let attributes = if entity_type == "world_rule" {
        json!({"rule":rest})
    } else {
        json!({})
    };
    Ok(
        json!({"kind":"entity","entity_type":entity_type,"name":title_like(&rest),"description":rest,"confidence":confidence,"attributes":attributes,"shared_core":shared,"document_type":Value::Null,"warnings":[],"detected":detected,"possible_matches":[]}),
    )
}

fn title_like(value: &str) -> String {
    let mut chars = value.chars();
    match chars.next() {
        Some(first) if value.chars().all(|c| c.is_lowercase() || c.is_whitespace()) => {
            first.to_uppercase().collect::<String>() + chars.as_str()
        }
        _ => value.to_owned(),
    }
}

trait EmptyExt {
    fn if_empty(self, fallback: impl FnOnce() -> String) -> String;
}
impl EmptyExt for String {
    fn if_empty(self, fallback: impl FnOnce() -> String) -> String {
        if self.is_empty() {
            fallback()
        } else {
            self
        }
    }
}

pub fn handle(
    state: &AppState,
    method: &str,
    path: &[&str],
    _query: &HashMap<String, String>,
    body: &Value,
) -> Option<ApiResult<Value>> {
    let m = method.to_ascii_uppercase();
    let result = match (m.as_str(), path) {
        ("POST", ["state-proposals"]) => state_proposals(body),
        ("POST", ["story-lab", "sheet-proposals"]) => (|| -> ApiResult<Value> {
            let b = obj(body)?;
            let p = text(b.get("prompt_text"));
            let specs = proposal_specs(&p);
            let specs = if specs.is_empty() {
                vec![
                    json!({"kind":text(b.get("kind")),"name":text(b.get("name")),"content":text(b.get("source_text")),"operation":"create"}),
                ]
            } else {
                specs
            };
            let mut items = Vec::new();
            for spec in specs {
                let mut staged = spec
                    .as_object()
                    .ok_or_else(|| ApiError::bad_request("Proposal must be an object"))?
                    .clone();
                staged.insert("workflow".into(), json!("story_lab_sheet"));
                staged.insert("source_prompt".into(), json!(p));
                for key in [
                    "document_type",
                    "entity_type",
                    "subject_name",
                    "object_name",
                    "relation_type",
                    "subject_variant_id",
                    "object_variant_id",
                ] {
                    if let Some(value) = b.get(key) {
                        staged.insert(key.to_owned(), value.clone());
                    }
                }
                items.push(stage(state, body, Value::Object(staged))?);
            }
            let mut first = items
                .first()
                .cloned()
                .ok_or_else(|| ApiError::bad_request("No sheet proposals supplied"))?;
            if let Some(o) = first.as_object_mut() {
                o.insert("items".into(), Value::Array(items));
            }
            Ok(first)
        })(),
        ("POST", ["story-lab", "sheet-proposals", id, "apply"]) => apply_one(state, id, body),
        ("POST", ["story-lab", "sheet-proposal-bundles", "apply"]) => (|| -> ApiResult<Value> {
            let b = obj(body)?;
            let action = text(b.get("action")).to_ascii_lowercase();
            if !["accept", "reject", "branch"].contains(&action.as_str()) {
                return Err(ApiError::bad_request(
                    "Action must be accept, reject, or branch",
                ));
            }
            let empty = Vec::new();
            let items = b.get("items").and_then(Value::as_array).unwrap_or(&empty);
            let mut out = Vec::new();
            let mut selected_items: Vec<&Value> = Vec::new();
            for item in items {
                let selected = item
                    .get("selected")
                    .and_then(Value::as_bool)
                    .unwrap_or(true);
                if !selected {
                    if let Some(change_id) = item.get("change_id").and_then(Value::as_str) {
                        let change = state
                            .store
                            .get("staged_changes", change_id)?
                            .ok_or_else(|| ApiError::not_found("Sheet proposal not found"))?;
                        if text(change.get("status")) != "pending" {
                            return Err(ApiError::new(
                                axum::http::StatusCode::CONFLICT,
                                "Sheet proposal is already resolved",
                            ));
                        }
                        let rejected = state.store.update(
                            "staged_changes",
                            change_id,
                            json!({"status":"rejected"}),
                        )?;
                        out.push(json!({"change":rejected,"resource":null,"branch":null}));
                    }
                    continue;
                }
                selected_items.push(item);
            }
            if action == "reject" {
                for item in selected_items {
                    let change_id = item
                        .get("change_id")
                        .and_then(Value::as_str)
                        .ok_or_else(|| ApiError::bad_request("change_id is required"))?;
                    let change = state
                        .store
                        .get("staged_changes", change_id)?
                        .ok_or_else(|| ApiError::not_found("Sheet proposal not found"))?;
                    if text(change.get("status")) != "pending" {
                        return Err(ApiError::new(
                            axum::http::StatusCode::CONFLICT,
                            "Sheet proposal is already resolved",
                        ));
                    }
                    let rejected = state.store.update(
                        "staged_changes",
                        change_id,
                        json!({"status":"rejected"}),
                    )?;
                    out.push(json!({"change":rejected,"resource":null,"branch":null}));
                }
                return Ok(json!({"results":out,"branch":null}));
            }
            let mut shared_branch = Value::Null;
            let shared_branch_id = if action == "branch" {
                let first = selected_items.first().ok_or_else(|| {
                    ApiError::bad_request("At least one selected proposal is required")
                })?;
                let change_id = first
                    .get("change_id")
                    .and_then(Value::as_str)
                    .ok_or_else(|| ApiError::bad_request("change_id is required"))?;
                let change = state
                    .store
                    .get("staged_changes", change_id)?
                    .ok_or_else(|| ApiError::not_found("Sheet proposal not found"))?;
                if text(change.get("status")) != "pending" {
                    return Err(ApiError::new(
                        axum::http::StatusCode::CONFLICT,
                        "Sheet proposal is already resolved",
                    ));
                }
                let world = text(change.get("world_id")).if_empty(|| "WORLD-BIBLE-MAIN".to_owned());
                let name = text(first.get("proposal").and_then(|v| v.get("name")))
                    .if_empty(|| "proposal".to_owned());
                let branch_name =
                    text(b.get("branch_name")).if_empty(|| format!("{} proposal", name));
                let branch_id = id("BRANCH");
                shared_branch=state.store.insert("world_branches",json!({"id":branch_id,"world_id":world,"name":branch_name,"slug":branch_name.to_ascii_lowercase().replace(' ',"-"),"kind":"sandbox","canon_status":"what_if","description":format!("Story Lab sheet proposal: {}",name)}))?;
                Some(branch_id)
            } else {
                None
            };
            for item in selected_items {
                let mut request = body.clone();
                if let Some(ro) = request.as_object_mut() {
                    if let Some(proposal) = item.get("proposal") {
                        ro.insert("proposal".into(), proposal.clone());
                    }
                    if let Some(branch_id) = &shared_branch_id {
                        ro.insert("target_branch_id".into(), json!(branch_id));
                    }
                }
                out.push(apply_one(state, &text(item.get("change_id")), &request)?);
            }
            Ok(json!({"results":out,"branch":shared_branch}))
        })(),
        ("POST", ["library", "entity-merge", "preview"]) => merge(state, body, true),
        ("POST", ["library", "entity-merge"]) => merge(state, body, false),
        ("POST", ["quick-create", "preview"]) => quick(state, body, true),
        ("POST", ["quick-create"]) => quick(state, body, false),
        ("GET", ["user-profile"]) => {
            FoundationStore::from_store(state.store.clone()).user_profile()
        }
        ("PUT", ["user-profile"]) => normalize_profile(body)
            .and_then(|p| FoundationStore::from_store(state.store.clone()).save_user_profile(&p)),
        ("POST", ["user-profile", "extract"]) => {
            Ok(extract_profile(state, &text(obj(body).ok()?.get("text"))))
        }
        ("POST", ["user-profile", "entity"]) => promote_user_entity(state, body),
        ("GET", ["presence-bindings", scope, id]) => {
            FoundationStore::from_store(state.store.clone()).presence_binding(scope, id)
        }
        ("PUT", ["presence-bindings", scope, id]) => FoundationStore::from_store(
            state.store.clone(),
        )
        .save_presence_binding(scope, id, body.get("profile").unwrap_or(body)),
        ("POST", ["conversation", "blueprint", "extract"]) => Ok(
            json!({"blueprint":FoundationStore::from_store(state.store.clone()).extract_blueprint(&text(obj(body).ok()?.get("text")),body.get("current").unwrap_or(&json!({})))}),
        ),
        ("POST", ["conversation", "promote-presence"]) => promote_presence(state, body),
        _ => return None,
    };
    Some(result)
}
