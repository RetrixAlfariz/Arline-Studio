//! Workspace route handlers.  These handlers preserve the existing JSON
//! resource contract while keeping SQL and validation in the Store boundary.

use crate::{ApiError, ApiResult, AppState};
use axum::http::StatusCode;
use serde_json::{json, Map, Value};
use std::collections::HashMap;

pub fn handle(
    state: &AppState,
    method: &str,
    path: &[&str],
    query: &HashMap<String, String>,
    body: &Value,
) -> Option<ApiResult<Value>> {
    if let Some(result) = crate::workspace_advanced::handle(state, method, path, query, body) {
        return Some(result);
    }
    let method = method.to_ascii_uppercase();
    let head = *path.first()?;
    if !owned_head(head) {
        return None;
    }
    let result = match (method.as_str(), head) {
        ("GET", "projects") if path.get(2) == Some(&"tree") => tree(state, path, query),
        ("POST", "projects") if path.get(1) == Some(&"world-link") => {
            link_project_world(state, body)
        }
        ("GET", "worlds") if path.get(1) == Some(&"compare") => unsupported("world comparison"),
        ("GET", "branches") if path.get(1) == Some(&"compare") => unsupported("branch comparison"),
        ("POST", "branches") if path.get(2) == Some(&"merge") => unsupported("branch merge"),
        ("GET", "entities") if path.get(2) == Some(&"compare") => unsupported("variant comparison"),
        ("GET", "projects") if path.len() == 1 => list_projects(state, query),
        ("POST", "projects") if path.len() == 1 => create(state, "projects", body),
        ("GET", "worlds") if path.len() == 1 => {
            list(state, "worlds", query, &[("project_id", "project_id")])
        }
        ("POST", "worlds") if path.len() == 1 => create(state, "worlds", body),
        ("GET", "branches") if path.len() == 1 => {
            list(state, "world_branches", query, &[("world_id", "world_id")])
        }
        ("POST", "branches") if path.len() == 1 => create(state, "world_branches", body),
        ("GET", "folders") if path.len() == 1 => list(
            state,
            "workspace_folders",
            query,
            &[
                ("project_id", "project_id"),
                ("world_id", "world_id"),
                ("branch_id", "branch_id"),
            ],
        ),
        ("POST", "folders") if path.len() == 1 => create(state, "workspace_folders", body),
        ("GET", "documents") if path.len() == 1 => list(
            state,
            "workspace_documents",
            query,
            &[
                ("project_id", "project_id"),
                ("world_id", "world_id"),
                ("branch_id", "branch_id"),
            ],
        ),
        ("POST", "documents") if path.len() == 1 => create(state, "workspace_documents", body),
        ("GET", "relationships") if path.len() == 1 => list(
            state,
            "relationships",
            query,
            &[("world_id", "world_id"), ("branch_id", "branch_id")],
        ),
        ("POST", "relationships") if path.len() == 1 => create(state, "relationships", body),
        ("GET", "tags") if path.len() == 1 => list(
            state,
            "workspace_tags",
            query,
            &[("project_id", "project_id")],
        ),
        ("POST", "tags") if path.len() == 1 => create(state, "workspace_tags", body),
        ("GET", "facts") if path.len() == 1 => list(
            state,
            "canon_facts",
            query,
            &[
                ("project_id", "project_id"),
                ("world_id", "world_id"),
                ("branch_id", "branch_id"),
            ],
        ),
        ("POST", "facts") if path.len() == 1 => create(state, "canon_facts", body),
        ("GET", "snapshots") if path.len() == 1 => {
            list(state, "world_snapshots", query, &[("world_id", "world_id")])
        }
        ("POST", "snapshots") if path.len() == 1 => create(state, "world_snapshots", body),
        ("GET", "templates") if path.len() == 1 => list(
            state,
            "entity_templates",
            query,
            &[("project_id", "project_id")],
        ),
        ("POST", "templates") if path.len() == 1 => create(state, "entity_templates", body),
        ("GET", "conflicts") if path.len() == 1 => list(
            state,
            "workspace_conflicts",
            query,
            &[
                ("project_id", "project_id"),
                ("world_id", "world_id"),
                ("branch_id", "branch_id"),
                ("status", "status"),
            ],
        ),
        ("POST", "conflicts") if path.len() == 1 => create(state, "workspace_conflicts", body),
        ("GET", "timeline") if path.len() == 1 => list(
            state,
            "timeline_events",
            query,
            &[("world_id", "world_id"), ("branch_id", "branch_id")],
        ),
        ("POST", "timeline") if path.len() == 1 => create(state, "timeline_events", body),
        ("GET", "context") if path.get(1) == Some(&"recipes") => list(
            state,
            "context_recipes",
            query,
            &[("project_id", "project_id")],
        ),
        ("POST", "context") if path.get(1) == Some(&"recipes") => {
            create(state, "context_recipes", body)
        }
        ("GET", "revisions") => list_revisions(state, path, query),
        ("POST", "revisions") if path.get(2) == Some(&"restore") => {
            restore_revision(state, path.get(1).copied().unwrap_or(""), body)
        }
        ("GET", "mentions") => mentions(state, query),
        ("GET", "world-bible") => world_bible(state, query),
        ("GET", "workspace") if path.get(1) == Some(&"bootstrap") => bootstrap(state, query),
        ("POST", "canon") if path.get(1) == Some(&"promote") => promote(state, body),
        ("POST", "retcon") if path.get(1) == Some(&"apply") => retcon(state, body),
        ("POST", "quick-create") if path.get(1) == Some(&"preview") => {
            quick_create_preview(state, body)
        }
        ("POST", "quick-create") => quick_create(state, body),
        _ => route_by_table(state, &method, path, query, body),
    };
    Some(result)
}

fn owned_head(head: &str) -> bool {
    matches!(
        head,
        "projects"
            | "worlds"
            | "branches"
            | "folders"
            | "documents"
            | "relationships"
            | "tags"
            | "facts"
            | "snapshots"
            | "templates"
            | "context"
            | "revisions"
            | "mentions"
            | "world-bible"
            | "workspace"
            | "canon"
            | "retcon"
            | "quick-create"
            | "entities"
            | "scenes"
            | "staged-changes"
            | "overlays"
            | "timeline"
            | "recipes"
            | "conflicts"
    )
}

fn unsupported(feature: &str) -> ApiResult<Value> {
    Err(ApiError::new(
        StatusCode::NOT_IMPLEMENTED,
        format!(
            "{} is not implemented by the Rust workspace runtime",
            feature
        ),
    ))
}

fn link_project_world(state: &AppState, body: &Value) -> ApiResult<Value> {
    let project_id = body
        .get("project_id")
        .and_then(Value::as_str)
        .ok_or_else(|| ApiError::bad_request("project_id is required"))?;
    let world_id = body
        .get("world_id")
        .and_then(Value::as_str)
        .ok_or_else(|| ApiError::bad_request("world_id is required"))?;
    if state.store.get("projects", project_id)?.is_none()
        || state.store.get("worlds", world_id)?.is_none()
    {
        return Err(ApiError::bad_request("project or world does not exist"));
    }
    let role = body
        .get("role")
        .and_then(Value::as_str)
        .unwrap_or("reference");
    state.store.execute(
        "INSERT OR REPLACE INTO project_world_links(project_id,world_id,role,created_at) VALUES(?,?,?,?)",
        &[&project_id, &world_id, &role, &chrono::Utc::now().to_rfc3339()],
    )?;
    Ok(json!({"project_id":project_id,"world_id":world_id,"role":role}))
}

fn quick_create_preview(state: &AppState, body: &Value) -> ApiResult<Value> {
    let text = body
        .get("text")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim();
    if text.is_empty() {
        return Err(ApiError::bad_request("Describe what you want to create"));
    }
    let forced = body.get("forced_kind").and_then(Value::as_str);
    let mut raw = text.to_owned();
    let mut detected = Vec::new();
    let mut kind = forced.unwrap_or("").to_owned();
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
        if kind.is_empty() {
            if let Some(prefix) = prefixes
                .iter()
                .find(|prefix| raw.to_ascii_lowercase().starts_with(**prefix))
            {
                raw = raw[prefix.len()..]
                    .trim_start_matches([' ', ':', '-'])
                    .to_owned();
                kind = candidate.to_owned();
                detected.push(format!("explicit {}", candidate));
                break;
            }
        }
    }
    let lower = raw.to_ascii_lowercase();
    let document_words = [
        "scene",
        "chapter",
        "bab",
        "outline",
        "draft",
        "note",
        "catatan",
        "lore note",
    ];
    let (entity_type, confidence) =
        if kind == "document" || document_words.iter().any(|word| lower.contains(word)) {
            kind = "document".into();
            (None, if forced.is_some() { 0.90 } else { 0.78 })
        } else {
            if kind.is_empty() {
                kind = "entity".into();
            }
            let cues = [
                (
                    "location",
                    &[
                        "apartemen",
                        "apartment",
                        "lantai",
                        "floor",
                        "unit",
                        "kamar",
                        "room",
                        "rumah",
                        "house",
                        "gedung",
                        "building",
                        "jalan",
                        "street",
                        "city",
                        "kota",
                        "forest",
                        "hutan",
                    ][..],
                ),
                (
                    "item",
                    &[
                        "pedang", "sword", "blade", "weapon", "senjata", "cincin", "ring", "buku",
                        "book", "armor", "potion", "artifact", "artefak",
                    ][..],
                ),
                (
                    "organization",
                    &[
                        "organization",
                        "organisasi",
                        "guild",
                        "ordo",
                        "faction",
                        "faksi",
                        "company",
                        "perusahaan",
                        "kingdom",
                        "kerajaan",
                        "academy",
                        "akademi",
                    ][..],
                ),
                (
                    "world_rule",
                    &[
                        "rule",
                        "aturan",
                        "hukum",
                        "magic system",
                        "sistem sihir",
                        "mekanisme dunia",
                    ][..],
                ),
                (
                    "character",
                    &["character", "karakter", "tokoh", "orang", "person", "npc"][..],
                ),
            ];
            let found = cues
                .iter()
                .find(|(_, words)| words.iter().any(|word| lower.contains(word)));
            match found {
                Some((kind, _)) => (
                    Some((*kind).to_owned()),
                    if *kind == "location" { 0.90 } else { 0.84 },
                ),
                None if raw.split_whitespace().count() <= 4
                    && !raw.chars().any(|c| c.is_ascii_digit()) =>
                {
                    (Some("character".into()), 0.58)
                }
                None => (Some("lore".into()), 0.55),
            }
        };
    let name_override = body
        .get("name")
        .and_then(Value::as_str)
        .filter(|v| !v.trim().is_empty());
    let name = name_override.unwrap_or(raw.as_str()).to_owned();
    let doc_type = if kind == "document" {
        Some(if lower.contains("chapter") || lower.contains("bab") {
            "chapter"
        } else if lower.contains("outline") {
            "outline"
        } else if lower.contains("note") || lower.contains("catatan") {
            "note"
        } else {
            "scene"
        })
    } else {
        None
    };
    let mut attributes = Map::new();
    let mut shared = Map::new();
    let mut warnings: Vec<String> = Vec::new();
    if let Some(entity_type) = entity_type.as_deref() {
        if entity_type == "character" {
            shared.insert("identity".into(), json!({"name": raw}));
        }
        if entity_type == "item" {
            shared.insert("kind".into(), json!("item"));
        }
        if entity_type == "organization" {
            shared.insert("kind".into(), json!("organization"));
        }
        if entity_type == "world_rule" {
            shared.insert("domain".into(), Value::Null);
            attributes.insert("rule".into(), json!(raw));
        }
        if entity_type == "location" {
            shared.insert("kind".into(), json!("location"));
            for marker in ["floor", "lantai"] {
                if let Some(value) = lower
                    .split(marker)
                    .nth(1)
                    .and_then(|tail| tail.trim_matches([' ', ':', '-']).split_whitespace().next())
                {
                    attributes.insert(
                        "floor".into(),
                        value
                            .parse::<i64>()
                            .map(Value::from)
                            .unwrap_or_else(|_| json!(value)),
                    );
                    detected.push(format!("floor {}", value));
                    break;
                }
            }
        }
        if entity_type == "lore" {
            warnings
                .push("Arline could not confidently infer the sheet type; guessed Lore.".into());
        }
    }
    let mut out = json!({
        "kind": if kind == "document" { "document" } else if ["project","world","folder"].contains(&kind.as_str()) { kind.as_str() } else { "entity" },
        "entity_type": entity_type.clone(),
        "name": name,
        "description": if kind == "entity" { raw.clone() } else { String::new() },
        "confidence": confidence,
        "attributes": attributes,
        "shared_core": shared,
        "document_type": doc_type,
        "warnings": warnings,
        "detected": detected,
        "possible_matches": [],
    });
    if out["kind"] == "entity" {
        let candidate_type = body
            .get("entity_type")
            .and_then(Value::as_str)
            .or(entity_type.as_deref());
        let mut matches = Vec::new();
        for family in state.store.list("entity_families", &[])? {
            if candidate_type.is_some()
                && family.get("entity_type").and_then(Value::as_str) != candidate_type
            {
                continue;
            }
            let label = family.get("name").and_then(Value::as_str).unwrap_or("");
            let score = similarity(&name, label);
            if score >= 0.68 {
                matches.push(json!({"type":"entity_family","id":family["id"],"label":label,"entity_type":family["entity_type"],"score":((score * 1000.0).round() / 1000.0),"alias":null}));
            }
        }
        matches.sort_by(|a, b| {
            b["score"]
                .as_f64()
                .partial_cmp(&a["score"].as_f64())
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        out["possible_matches"] = Value::Array(matches.into_iter().take(5).collect());
    }
    Ok(out)
}

fn similarity(left: &str, right: &str) -> f64 {
    let a: Vec<char> = left.to_ascii_lowercase().chars().collect();
    let b: Vec<char> = right.to_ascii_lowercase().chars().collect();
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let mut row: Vec<usize> = (0..=b.len()).collect();
    for (i, ca) in a.iter().enumerate() {
        let mut next = vec![i + 1; b.len() + 1];
        for (j, cb) in b.iter().enumerate() {
            next[j + 1] = if ca == cb {
                row[j]
            } else {
                1 + row[j].min(row[j + 1]).min(next[j])
            };
        }
        row = next;
    }
    1.0 - row[b.len()] as f64 / a.len().max(b.len()) as f64
}

fn route_by_table(
    state: &AppState,
    method: &str,
    path: &[&str],
    query: &HashMap<String, String>,
    body: &Value,
) -> ApiResult<Value> {
    if path.first() == Some(&"projects") && path.len() > 2 {
        return nested_project(state, method, path, query, body);
    }
    let (table, id_index) = match path.first().copied() {
        Some("entities") if path.get(1) == Some(&"families") => ("entity_families", 2),
        Some("entities") if path.get(1) == Some(&"variants") => ("entity_variants", 2),
        Some("projects") => ("projects", 1),
        Some("worlds") => ("worlds", 1),
        Some("branches") => ("world_branches", 1),
        Some("folders") => ("workspace_folders", 1),
        Some("documents") => ("workspace_documents", 1),
        Some("relationships") => ("relationships", 1),
        Some("tags") => ("workspace_tags", 1),
        Some("facts") => ("canon_facts", 1),
        Some("snapshots") => ("world_snapshots", 1),
        Some("templates") => ("entity_templates", 1),
        Some("scenes") if path.get(1) == Some(&"dependencies") => ("scene_dependencies", 2),
        Some("staged-changes") => ("staged_changes", 1),
        Some("overlays") => ("project_overlays", 1),
        _ => return Err(ApiError::not_found("workspace route not implemented")),
    };
    let id = path.get(id_index).copied();
    match (method, id) {
        ("GET", Some(id)) => state
            .store
            .get(table, id)
            .and_then(|v| v.ok_or_else(|| ApiError::not_found("resource not found"))),
        ("GET", None) => list(state, table, query, &[]),
        ("POST", None) => create(state, table, body),
        ("PATCH", Some(id)) | ("PUT", Some(id)) if table == "workspace_folders" => {
            state.store.update_folder(id, body)
        }
        ("PATCH", Some(id)) | ("PUT", Some(id)) => update(state, table, id, body),
        ("DELETE", Some(id)) => {
            if table == "workspace_folders" {
                return Ok(json!({"ok": state.store.delete_folder(id)?}));
            }
            Ok(json!({"ok": state.store.delete(table, id)?}))
        }
        _ => Err(ApiError::bad_request("method/path combination is invalid")),
    }
}

fn nested_project(
    state: &AppState,
    method: &str,
    path: &[&str],
    query: &HashMap<String, String>,
    body: &Value,
) -> ApiResult<Value> {
    let project_id = path
        .get(1)
        .ok_or_else(|| ApiError::bad_request("project id is required"))?;
    match (method, path.get(2).copied(), path.get(3).copied()) {
        ("GET", Some("manifest"), None) => Ok(Value::Array(state.store.list(
            "project_manifest_refs",
            &[("project_id", json!(project_id))],
        )?)),
        ("GET", Some("active-scene"), None) => active_scene(state, project_id),
        ("GET", Some("scene-cards"), None) => Ok(Value::Array(
            state
                .store
                .list("project_scene_cards", &[("project_id", json!(project_id))])?,
        )),
        ("GET", Some("staged-changes"), None) => Ok(Value::Array(
            state
                .store
                .list("staged_changes", &[("project_id", json!(project_id))])?,
        )),
        ("GET", Some("overlays"), None) => Ok(Value::Array(
            state
                .store
                .list("project_overlays", &[("project_id", json!(project_id))])?,
        )),
        ("POST", Some("context-recipes"), None) => {
            let mut payload = body.clone();
            payload
                .as_object_mut()
                .ok_or_else(|| ApiError::bad_request("payload must be an object"))?
                .insert("project_id".into(), json!(project_id));
            create(state, "context_recipes", &payload)
        }
        ("POST", Some("overlays"), None) => {
            let mut payload = body.clone();
            payload
                .as_object_mut()
                .ok_or_else(|| ApiError::bad_request("payload must be an object"))?
                .insert("project_id".into(), json!(project_id));
            create(state, "project_overlays", &payload)
        }
        ("GET", Some("continuity"), None) => unsupported("project continuity"),
        ("PUT", Some("active-scene"), None) => set_active_scene(state, project_id, body),
        ("PUT", Some("scene-cards"), Some(_)) => unsupported("scene-card mutation"),
        ("POST", Some("staged-changes"), None) => unsupported("staged-change mutation"),
        ("POST", Some("manifest"), Some("refs")) => unsupported("manifest mutation"),
        _ => {
            let _ = query;
            unsupported("project nested route")
        }
    }
}

fn active_scene(state: &AppState, project_id: &str) -> ApiResult<Value> {
    let active = state
        .store
        .list(
            "project_active_scenes",
            &[("project_id", json!(project_id))],
        )?
        .into_iter()
        .next();
    let document = match active.as_ref().and_then(|row| row["document_id"].as_str()) {
        Some(id) => state.store.get("workspace_documents", id)?,
        None => None,
    };
    Ok(json!({"active_scene":active,"document":document}))
}

fn set_active_scene(state: &AppState, project_id: &str, body: &Value) -> ApiResult<Value> {
    if state.store.get("projects", project_id)?.is_none() {
        return Err(ApiError::not_found("Project not found"));
    }
    let document = body.get("document_id").and_then(Value::as_str);
    let world = body.get("world_id").and_then(Value::as_str);
    let branch = body.get("branch_id").and_then(Value::as_str);
    if let Some(id) = document {
        let row = state
            .store
            .get("workspace_documents", id)?
            .ok_or_else(|| ApiError::not_found("Document not found"))?;
        if row["project_id"].as_str() != Some(project_id) {
            return Err(ApiError::bad_request(
                "Active scene document must belong to the project",
            ));
        }
        if row["world_id"].as_str().is_some_and(|id| Some(id) != world)
            || row["branch_id"]
                .as_str()
                .is_some_and(|id| Some(id) != branch)
        {
            return Err(ApiError::bad_request(
                "Active scene document does not match the selected world or branch",
            ));
        }
    }
    if let Some(id) = world {
        let owner = state
            .store
            .get("worlds", id)?
            .ok_or_else(|| ApiError::not_found("World not found"))?;
        if owner["project_id"].as_str() != Some(project_id)
            && state
                .store
                .list(
                    "project_world_links",
                    &[("project_id", json!(project_id)), ("world_id", json!(id))],
                )?
                .is_empty()
        {
            return Err(ApiError::bad_request("World is not linked to the project"));
        }
    }
    if let Some(id) = branch {
        let row = state
            .store
            .get("world_branches", id)?
            .ok_or_else(|| ApiError::not_found("Branch not found"))?;
        if row["world_id"].as_str() != world {
            return Err(ApiError::bad_request(
                "Branch does not belong to the selected world",
            ));
        }
    }
    let participants = body.get("participants").cloned().unwrap_or(json!([]));
    let pov = body.get("pov_variant_id").and_then(Value::as_str);
    let location = body.get("location_variant_id").and_then(Value::as_str);
    let people = participants
        .as_array()
        .ok_or_else(|| ApiError::bad_request("Participants must be an array"))?;
    for id in pov
        .into_iter()
        .chain(location)
        .chain(people.iter().filter_map(Value::as_str))
    {
        let row = state
            .store
            .get("entity_variants", id)?
            .ok_or_else(|| ApiError::not_found("Scene participant not found"))?;
        if row["world_id"].as_str() != world
            || row["branch_id"]
                .as_str()
                .is_some_and(|id| Some(id) != branch)
        {
            return Err(ApiError::bad_request(
                "Scene participant does not match the selected scope",
            ));
        }
    }
    state.store.connection()?.execute("INSERT INTO project_active_scenes(project_id,document_id,world_id,branch_id,pov_variant_id,location_variant_id,participants_json,narrative_time,notes,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET document_id=excluded.document_id,world_id=excluded.world_id,branch_id=excluded.branch_id,pov_variant_id=excluded.pov_variant_id,location_variant_id=excluded.location_variant_id,participants_json=excluded.participants_json,narrative_time=excluded.narrative_time,notes=excluded.notes,updated_at=excluded.updated_at",
        rusqlite::params![project_id,document,world,branch,pov,location,participants.to_string(),body.get("narrative_time").and_then(Value::as_str).unwrap_or(""),body.get("notes").and_then(Value::as_str).unwrap_or(""),chrono::Utc::now().to_rfc3339()])?;
    Ok(state
        .store
        .list(
            "project_active_scenes",
            &[("project_id", json!(project_id))],
        )?
        .remove(0))
}

fn create(state: &AppState, table: &str, body: &Value) -> ApiResult<Value> {
    let obj = body
        .as_object()
        .ok_or_else(|| ApiError::bad_request("payload must be an object"))?;
    scope_gate(state, obj)?;
    let created = state.store.insert(table, body.clone())?;
    if table == "workspace_documents" {
        if let Some(document_id) = created.get("id").and_then(Value::as_str) {
            state.store.insert(
                "workspace_revisions",
                json!({
                    "resource_type": "document",
                    "resource_id": document_id,
                    "version": 1,
                    "content": created.get("content").cloned().unwrap_or(Value::String(String::new())),
                    "note": "initial"
                }),
            )?;
        }
    }
    if table == "projects" {
        if let Some(project_id) = created.get("id").and_then(Value::as_str) {
            let now = chrono::Utc::now().to_rfc3339();
            state.store.execute(
                "UPDATE projects SET default_world_id=? WHERE id=?",
                &[&"WORLD-BIBLE-MAIN", &project_id],
            )?;
            state.store.execute(
                "INSERT OR IGNORE INTO project_world_links(project_id,world_id,role,created_at) VALUES(?,?,?,?)",
                &[&project_id, &"WORLD-BIBLE-MAIN", &"primary", &now],
            )?;
            return state
                .store
                .get("projects", project_id)
                .map(|row| row.unwrap_or(created));
        }
    }
    Ok(created)
}

fn list_projects(state: &AppState, query: &HashMap<String, String>) -> ApiResult<Value> {
    let needle = query.get("search").map(|value| value.to_ascii_lowercase());
    let include_archived = query
        .get("include_archived")
        .is_some_and(|value| value == "1" || value.eq_ignore_ascii_case("true"));
    let hidden = hidden_project_ids(state)?;
    let rows = state
        .store
        .list("projects", &[])?
        .into_iter()
        .filter(|row| {
            row.get("id").and_then(Value::as_str) != Some("PROJ-WORLD-BIBLE")
                && row.get("slug").and_then(Value::as_str) != Some("__world-bible__")
                && !hidden.contains(row.get("id").and_then(Value::as_str).unwrap_or_default())
                && (include_archived
                    || !row
                        .get("archived")
                        .and_then(Value::as_bool)
                        .unwrap_or(false))
        })
        .filter(|row| {
            needle.as_deref().is_none_or(|needle| {
                row.get("name")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_ascii_lowercase()
                    .contains(needle)
            })
        })
        .map(|mut row| {
            row["lifecycle"] = json!({"archived_at":null,"trashed_at":null});
            if !row.get("settings").map(Value::is_object).unwrap_or(false) {
                row["settings"] = json!({});
            }
            if let Some(settings) = row.get_mut("settings").and_then(Value::as_object_mut) {
                settings
                    .entry("preferred_model")
                    .or_insert_with(|| json!("qwen3.5-4b-uncensored-hauhaucs-aggressive"));
                settings.entry("reasoning").or_insert_with(|| json!("off"));
                settings
                    .entry("projection_mode")
                    .or_insert_with(|| json!("balanced"));
                settings
                    .entry("language")
                    .or_insert_with(|| json!("follow_prompt"));
            }
            row
        })
        .collect::<Vec<_>>();
    Ok(json!({"projects": rows}))
}

fn update(state: &AppState, table: &str, id: &str, body: &Value) -> ApiResult<Value> {
    let obj = body
        .as_object()
        .ok_or_else(|| ApiError::bad_request("payload must be an object"))?;
    scope_gate(state, obj)?;
    state.store.update(table, id, body.clone())
}

fn list(
    state: &AppState,
    table: &str,
    query: &HashMap<String, String>,
    allowed: &[(&str, &str)],
) -> ApiResult<Value> {
    let filters: Vec<(&str, Value)> = allowed
        .iter()
        .filter_map(|(q, col)| query.get(*q).map(|v| (*col, Value::String(v.clone()))))
        .collect();
    Ok(Value::Array(state.store.list(table, &filters)?))
}

fn scope_gate(state: &AppState, payload: &Map<String, Value>) -> ApiResult<()> {
    if let Some(project_id) = payload.get("project_id").and_then(Value::as_str) {
        if state.store.get("projects", project_id)?.is_none() {
            return Err(ApiError::bad_request("project_id does not exist"));
        }
    }
    if let Some(world_id) = payload.get("world_id").and_then(Value::as_str) {
        if state.store.get("worlds", world_id)?.is_none() {
            return Err(ApiError::bad_request("world_id does not exist"));
        }
    }
    if let Some(branch_id) = payload.get("branch_id").and_then(Value::as_str) {
        if state.store.get("world_branches", branch_id)?.is_none() {
            return Err(ApiError::bad_request("branch_id does not exist"));
        }
    }
    Ok(())
}

fn list_revisions(
    state: &AppState,
    path: &[&str],
    query: &HashMap<String, String>,
) -> ApiResult<Value> {
    let resource_type = path
        .get(1)
        .copied()
        .or_else(|| query.get("resource_type").map(String::as_str))
        .ok_or_else(|| ApiError::bad_request("resource_type is required"))?;
    let resource_id = path
        .get(2)
        .copied()
        .or_else(|| query.get("resource_id").map(String::as_str))
        .ok_or_else(|| ApiError::bad_request("resource_id is required"))?;
    Ok(json!({"revisions": state.store.list(
        "workspace_revisions",
        &[
            ("resource_type", json!(resource_type)),
            ("resource_id", json!(resource_id)),
        ],
    )?}))
}

fn restore_revision(state: &AppState, revision_id: &str, body: &Value) -> ApiResult<Value> {
    if revision_id.is_empty() {
        return Err(ApiError::bad_request("revision id is required"));
    }
    let mut con = state.store.connection()?;
    let tx = con
        .transaction()
        .map_err(|error| ApiError::internal(error.to_string()))?;
    let (resource_type, resource_id, content, _version): (String, String, String, i64) = tx
        .query_row(
            "SELECT resource_type,resource_id,content_json,version FROM workspace_revisions WHERE id=?",
            [revision_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
        )
        .map_err(|_| ApiError::not_found("revision not found"))?;
    let table = match resource_type.as_str() {
        "document" => "workspace_documents",
        "entity_family" => "entity_families",
        _ => return Err(ApiError::bad_request("resource type cannot be restored")),
    };
    let exists: i64 = tx
        .query_row(
            &format!("SELECT COUNT(*) FROM {} WHERE id=?", table),
            [&resource_id],
            |row| row.get(0),
        )
        .map_err(|error| ApiError::internal(error.to_string()))?;
    if exists == 0 {
        return Err(ApiError::not_found("revision resource not found"));
    }
    let note = body
        .get("note")
        .and_then(Value::as_str)
        .unwrap_or("restored")
        .to_owned();
    let now = chrono::Utc::now().to_rfc3339();
    let new_version: i64 = tx
        .query_row(
            "SELECT COALESCE(MAX(version),0)+1 FROM workspace_revisions WHERE resource_type=? AND resource_id=?",
            [&resource_type, &resource_id],
            |row| row.get(0),
        )
        .map_err(|error| ApiError::internal(error.to_string()))?;
    let column = if table == "workspace_documents" {
        "content"
    } else {
        "description"
    };
    tx.execute(
        &format!("UPDATE {} SET {}=?,updated_at=? WHERE id=?", table, column),
        rusqlite::params![content, now, resource_id],
    )
    .map_err(|error| ApiError::internal(error.to_string()))?;
    let new_id = format!("revision-{}", uuid::Uuid::new_v4());
    tx.execute(
        "INSERT INTO workspace_revisions(id,resource_type,resource_id,version,content_json,note,created_at) VALUES(?,?,?,?,?,?,?)",
        rusqlite::params![new_id, resource_type, resource_id, new_version, content, note, now],
    )
    .map_err(|error| ApiError::internal(error.to_string()))?;
    tx.commit()
        .map_err(|error| ApiError::internal(error.to_string()))?;
    state
        .store
        .get(table, &resource_id)
        .and_then(|value| value.ok_or_else(|| ApiError::not_found("restored resource not found")))
}

fn mentions(state: &AppState, query: &HashMap<String, String>) -> ApiResult<Value> {
    let needle = query
        .get("q")
        .cloned()
        .unwrap_or_default()
        .to_ascii_lowercase();
    let rows = state.store.list("workspace_documents", &[])?;
    let results: Vec<Value> = rows
        .into_iter()
        .filter(|v| v.to_string().to_ascii_lowercase().contains(&needle))
        .collect();
    Ok(json!({"results": results}))
}

fn bootstrap(state: &AppState, query: &HashMap<String, String>) -> ApiResult<Value> {
    let project_id = query.get("project_id").cloned();
    let mut projects = match project_id.as_deref() {
        Some(id) => state.store.list("projects", &[("id", json!(id))])?,
        None => state.store.list("projects", &[])?,
    };
    let hidden = hidden_project_ids(state)?;
    projects.retain(|row| {
        row.get("id").and_then(Value::as_str) != Some("PROJ-WORLD-BIBLE")
            && row.get("slug").and_then(Value::as_str) != Some("__world-bible__")
            && !hidden.contains(row.get("id").and_then(Value::as_str).unwrap_or_default())
            && !row
                .get("archived")
                .and_then(Value::as_bool)
                .unwrap_or(false)
    });
    for row in &mut projects {
        row["lifecycle"] = json!({"archived_at":null,"trashed_at":null});
        if !row.get("settings").map(Value::is_object).unwrap_or(false) {
            row["settings"] = json!({});
        }
        let settings = row
            .get_mut("settings")
            .and_then(Value::as_object_mut)
            .expect("settings object");
        settings
            .entry("preferred_model")
            .or_insert_with(|| json!("qwen3.5-4b-uncensored-hauhaucs-aggressive"));
        settings.entry("reasoning").or_insert_with(|| json!("off"));
        settings
            .entry("projection_mode")
            .or_insert_with(|| json!("balanced"));
        settings
            .entry("language")
            .or_insert_with(|| json!("follow_prompt"));
    }
    if projects.is_empty() {
        let mut default_project = create(
            state,
            "projects",
            &json!({
                "name": "My Stories",
                "description": "Default Arline workspace",
                "settings": {"language": "follow_prompt"}
            }),
        )?;
        default_project["lifecycle"] = json!({"archived_at":null,"trashed_at":null});
        default_project["settings"] = json!({
            "preferred_model": "qwen3.5-4b-uncensored-hauhaucs-aggressive",
            "reasoning": "off",
            "projection_mode": "balanced",
            "language": "follow_prompt"
        });
        projects.push(default_project);
    }
    let mut worlds = state.store.list("worlds", &[])?;
    for world in &mut worlds {
        if let Some(id) = world.get("id").and_then(Value::as_str) {
            let mut branches = state
                .store
                .list("world_branches", &[("world_id", json!(id))])?;
            for branch in &mut branches {
                branch["lifecycle"] = json!({"archived_at":null,"trashed_at":null});
            }
            world["branches"] = json!(branches);
        }
        world["lifecycle"] = json!({"archived_at":null,"trashed_at":null});
    }
    let saved_stack = query
        .get("stack_id")
        .and_then(|id| state.store.list("context_stack", &[("id", json!(id))]).ok())
        .and_then(|rows| rows.into_iter().next());
    let selected_project = saved_stack
        .as_ref()
        .and_then(|v| v.get("project_id"))
        .and_then(Value::as_str);
    let selected_world = saved_stack
        .as_ref()
        .and_then(|v| v.get("world_id"))
        .and_then(Value::as_str);
    let selected_branch = saved_stack
        .as_ref()
        .and_then(|v| v.get("branch_id"))
        .and_then(Value::as_str);
    let active_project = projects
        .iter()
        .find(|v| v.get("id").and_then(Value::as_str) == selected_project)
        .cloned()
        .or_else(|| projects.first().cloned())
        .unwrap_or(Value::Null);
    let active_world = worlds
        .iter()
        .find(|v| v.get("id").and_then(Value::as_str) == selected_world)
        .cloned()
        .or_else(|| {
            worlds
                .iter()
                .find(|v| {
                    v.get("id").and_then(Value::as_str)
                        == active_project
                            .get("default_world_id")
                            .and_then(Value::as_str)
                })
                .cloned()
        })
        .or_else(|| worlds.first().cloned())
        .unwrap_or(Value::Null);
    let branches = active_world
        .get("branches")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let active_branch = branches
        .iter()
        .find(|v| v.get("id").and_then(Value::as_str) == selected_branch)
        .cloned()
        .or_else(|| {
            branches
                .iter()
                .find(|v| v.get("kind").and_then(Value::as_str) == Some("main"))
                .cloned()
        })
        .or_else(|| branches.first().cloned())
        .unwrap_or(Value::Null);
    Ok(json!({
        "projects": projects,
        "worlds": worlds,
        "active": {"project": active_project, "world": active_world, "branch": active_branch},
        "context_stack": saved_stack.unwrap_or(Value::Null),
        "run_profiles": [],
        "favorites": [],
        "canon_statuses": ["canon", "draft", "what_if", "deprecated", "provisional", "retconned"],
        "entity_types": ["character", "location", "item", "organization", "world_rule", "lore"],
        "document_types": ["scene", "chapter", "outline", "note"],
        "branch_kinds": ["main", "fork", "sandbox"],
        "world_bible": {"backing_project_id": "PROJ-WORLD-BIBLE", "default_world_id": "WORLD-BIBLE-MAIN", "default_branch_id": "BRANCH-BIBLE-MAIN"},
        "schema_version": 7
    }))
}

fn hidden_project_ids(state: &AppState) -> ApiResult<std::collections::HashSet<String>> {
    Ok(state
        .store
        .query(
            "SELECT resource_id FROM resource_lifecycle WHERE resource_type='project' AND (archived_at IS NOT NULL OR trashed_at IS NOT NULL)",
            &[],
        )?
        .into_iter()
        .filter_map(|row| row.get("resource_id").and_then(Value::as_str).map(str::to_owned))
        .collect())
}

fn world_bible(state: &AppState, query: &HashMap<String, String>) -> ApiResult<Value> {
    let bible_project = query
        .get("project_id")
        .map(String::as_str)
        .unwrap_or("PROJ-WORLD-BIBLE");
    let folder_filters = vec![("project_id", json!(bible_project))];
    let folders = state.store.list("workspace_folders", &folder_filters)?;
    let mut worlds = state.store.list("worlds", &[])?;
    for world in &mut worlds {
        if let Some(id) = world.get("id").and_then(Value::as_str) {
            let mut branches = state
                .store
                .list("world_branches", &[("world_id", json!(id))])?;
            for branch in &mut branches {
                branch["lifecycle"] = json!({"archived_at":null,"trashed_at":null});
            }
            world["branches"] = json!(branches);
        }
        world["lifecycle"] = json!({"archived_at":null,"trashed_at":null});
    }
    let mut out = Map::new();
    out.insert(
        "projects".into(),
        Value::Array(state.store.list("projects", &[])?),
    );
    out.insert("worlds".into(), Value::Array(worlds));
    out.insert(
        "families".into(),
        Value::Array(state.store.list("entity_families", &[])?),
    );
    out.insert(
        "documents".into(),
        Value::Array(
            state
                .store
                .list("workspace_documents", &query_filter(query, "project_id"))?,
        ),
    );
    out.insert(
        "variants".into(),
        Value::Array(state.store.list(
            "entity_variants",
            &query_filters(
                query,
                &[("world_id", "world_id"), ("branch_id", "branch_id")],
            ),
        )?),
    );
    out.insert(
        "relationships".into(),
        Value::Array(state.store.list(
            "relationships",
            &query_filters(
                query,
                &[("world_id", "world_id"), ("branch_id", "branch_id")],
            ),
        )?),
    );
    out.insert(
        "branches".into(),
        Value::Array(
            state
                .store
                .list("world_branches", &query_filter(query, "world_id"))?,
        ),
    );
    out.insert(
        "timeline".into(),
        Value::Array(state.store.list(
            "timeline_events",
            &query_filters(
                query,
                &[("world_id", "world_id"), ("branch_id", "branch_id")],
            ),
        )?),
    );
    out.insert(
        "recipes".into(),
        Value::Array(
            state
                .store
                .list("context_recipes", &[("project_id", json!(bible_project))])?,
        ),
    );
    out.insert("folders".into(), Value::Array(folders.clone()));
    out.insert("folder_tree".into(), folder_tree(&folders));
    out.insert(
        "collections".into(),
        Value::Array(state.store.list(
            "workspace_collections",
            &[("scope_type", json!("world_bible"))],
        )?),
    );
    out.insert(
        "saved_views".into(),
        Value::Array(
            state
                .store
                .list("saved_views", &[("scope_type", json!("world_bible"))])?,
        ),
    );
    out.insert(
        "meta".into(),
        json!({"backing_project_id":"PROJ-WORLD-BIBLE", "default_world_id":"WORLD-BIBLE-MAIN", "default_branch_id":"BRANCH-BIBLE-MAIN"}),
    );
    Ok(Value::Object(out))
}

fn folder_tree(rows: &[Value]) -> Value {
    fn children(rows: &[Value], parent: Option<&str>) -> Vec<Value> {
        rows.iter()
            .filter(|row| row.get("parent_id").and_then(Value::as_str) == parent)
            .map(|row| {
                let mut node = row.clone();
                node["children"] =
                    Value::Array(children(rows, row.get("id").and_then(Value::as_str)));
                node
            })
            .collect()
    }
    Value::Array(children(rows, None))
}

fn tree(state: &AppState, path: &[&str], query: &HashMap<String, String>) -> ApiResult<Value> {
    let id = path
        .get(1)
        .ok_or_else(|| ApiError::bad_request("project id is required"))?;
    let mut filters = vec![("project_id", json!(id))];
    if let Some(v) = query.get("world_id") {
        filters.push(("world_id", json!(v)));
    }
    let folders = state
        .store
        .list("workspace_folders", &[("project_id", json!(id))])?;
    let documents = state.store.list("workspace_documents", &filters)?;
    let linked_world_ids = state
        .store
        .list("project_world_links", &[("project_id", json!(id))])?
        .into_iter()
        .filter_map(|link| {
            link.get("world_id")
                .and_then(Value::as_str)
                .map(str::to_owned)
        })
        .collect::<Vec<_>>();
    let worlds = state
        .store
        .list("worlds", &[])?
        .into_iter()
        .filter(|world| {
            world
                .get("project_id")
                .and_then(Value::as_str)
                .is_some_and(|owner| owner == *id)
                || world
                    .get("id")
                    .and_then(Value::as_str)
                    .is_some_and(|world_id| {
                        linked_world_ids.iter().any(|linked| linked == world_id)
                    })
        })
        .collect::<Vec<_>>();
    let tags = state
        .store
        .list("workspace_tags", &[("project_id", json!(id))])?;
    Ok(json!({
        "project": state.store.get("projects", id)?.unwrap_or(Value::Null),
        "worlds": worlds,
        "folders": folders,
        "folder_tree": folder_tree(&folders),
        "documents": documents,
        "tags": tags,
        "templates": state.store.list("entity_templates", &[("project_id", json!(id))])?,
        "manifest_refs": state.store.list("project_manifest_refs", &[("project_id", json!(id))])?,
        "active_scene": state.store.list("project_active_scenes", &[("project_id", json!(id))])?.into_iter().next().unwrap_or(Value::Null),
        "scene_cards": state.store.list("project_scene_cards", &[("project_id", json!(id))])?,
        "overlays": state.store.list("project_overlays", &[("project_id", json!(id))])?,
        "conflicts": state.store.list("workspace_conflicts", &[("project_id", json!(id))])?,
        "issues": state.store.list("workspace_issues", &[("project_id", json!(id))])?,
        "activity": state.store.list("workspace_activity", &[("project_id", json!(id))])?,
        "favorites": state.store.list("workspace_favorites", &[("project_id", json!(id))])?,
        "run_profiles": state.store.list("run_profiles", &[("project_id", json!(id))])?,
        "families": state.store.list("entity_families", &[("project_id", json!(id))])?
    }))
}

fn promote(state: &AppState, body: &Value) -> ApiResult<Value> {
    let id = body
        .get("fact_id")
        .and_then(Value::as_str)
        .or_else(|| body.get("id").and_then(Value::as_str))
        .ok_or_else(|| ApiError::bad_request("fact_id is required"))?;
    state.store.update(
        "canon_facts",
        id,
        json!({"status":"canon","authority":"user_explicit"}),
    )
}

fn retcon(state: &AppState, body: &Value) -> ApiResult<Value> {
    let id = body
        .get("fact_id")
        .and_then(Value::as_str)
        .ok_or_else(|| ApiError::bad_request("fact_id is required"))?;
    let value = body
        .get("new_value")
        .cloned()
        .ok_or_else(|| ApiError::bad_request("new_value is required"))?;
    state.store.update(
        "canon_facts",
        id,
        json!({"value": value.clone(), "value_json": value, "status":"canon"}),
    )
}

fn quick_create(state: &AppState, body: &Value) -> ApiResult<Value> {
    let obj = body
        .as_object()
        .ok_or_else(|| ApiError::bad_request("payload must be an object"))?;
    if obj.get("project_id").is_some() {
        scope_gate(state, obj)?;
    }
    state.store.insert("workspace_documents", json!({"project_id": obj.get("project_id").cloned().unwrap_or(Value::String("".into())), "world_id": obj.get("world_id").cloned().unwrap_or(Value::Null), "branch_id": obj.get("branch_id").cloned().unwrap_or(Value::Null), "title": obj.get("title").cloned().unwrap_or_else(|| json!("Untitled")), "content": obj.get("content").cloned().unwrap_or_else(|| json!("")), "document_type":"scene", "status":"planned"}))
}

fn query_filter(query: &HashMap<String, String>, key: &'static str) -> Vec<(&'static str, Value)> {
    query
        .get(key)
        .map(|v| vec![(key, Value::String(v.clone()))])
        .unwrap_or_default()
}

fn query_filters(
    query: &HashMap<String, String>,
    keys: &[(&'static str, &'static str)],
) -> Vec<(&'static str, Value)> {
    keys.iter()
        .filter_map(|(query_key, column)| {
            query
                .get(*query_key)
                .map(|value| (*column, Value::String(value.clone())))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::{handle, owned_head};
    use crate::config::RuntimeConfig;
    use crate::AppState;
    use serde_json::json;
    use std::collections::HashMap;

    #[test]
    fn unowned_runtime_heads_are_left_for_other_handlers() {
        for head in [
            "commands",
            "sessions",
            "home",
            "profile",
            "preferences",
            "run-profiles",
            "memory",
        ] {
            assert!(!owned_head(head), "{head} must fall through");
        }
        for head in [
            "projects",
            "worlds",
            "workspace",
            "world-bible",
            "quick-create",
        ] {
            assert!(owned_head(head), "{head} belongs to workspace");
        }
    }

    #[tokio::test]
    async fn bootstrap_attaches_branches_and_honors_context_selection() {
        let temp = tempfile::tempdir().expect("temp");
        let config = RuntimeConfig::create_default(temp.path().join("config.toml"), temp.path())
            .expect("config");
        let state = AppState::open(config).expect("state");
        state
            .store
            .insert(
                "projects",
                json!({"id":"P-BOOT","name":"Boot","slug":"boot"}),
            )
            .expect("project");
        state
            .store
            .insert(
                "worlds",
                json!({"id":"W-BOOT","project_id":"P-BOOT","name":"World","slug":"world"}),
            )
            .expect("world");
        state
            .store
            .insert(
                "world_branches",
                json!({"id":"B-BOOT","world_id":"W-BOOT","name":"Main","slug":"main"}),
            )
            .expect("branch");
        state.store.insert("context_stack", json!({"id":"default","project_id":"P-BOOT","world_id":"W-BOOT","branch_id":"B-BOOT"})).expect("context");
        let mut query = HashMap::new();
        query.insert("stack_id".into(), "default".into());
        let result = handle(
            &state,
            "GET",
            &["workspace", "bootstrap"],
            &query,
            &json!({}),
        )
        .expect("route")
        .expect("ok");
        assert_eq!(result["active"]["branch"]["id"], "B-BOOT");
        let selected_world = result["worlds"]
            .as_array()
            .unwrap()
            .iter()
            .find(|world| world["id"] == "W-BOOT")
            .unwrap();
        assert_eq!(selected_world["branches"][0]["id"], "B-BOOT");
    }

    #[tokio::test]
    async fn fresh_bootstrap_creates_visible_writing_project() {
        let temp = tempfile::tempdir().expect("temp");
        let config = RuntimeConfig::create_default(temp.path().join("config.toml"), temp.path())
            .expect("config");
        let state = AppState::open(config).expect("state");
        let result = handle(
            &state,
            "GET",
            &["workspace", "bootstrap"],
            &HashMap::new(),
            &json!({}),
        )
        .expect("route")
        .expect("ok");
        let projects = result["projects"].as_array().expect("projects");
        assert_eq!(projects.len(), 1);
        assert_eq!(projects[0]["name"], "My Stories");
        assert_ne!(projects[0]["id"], "PROJ-WORLD-BIBLE");
        let listed = handle(&state, "GET", &["projects"], &HashMap::new(), &json!({}))
            .expect("route")
            .expect("ok");
        assert_eq!(listed["projects"].as_array().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn world_bible_returns_shared_world_and_branches_for_writing_project() {
        let temp = tempfile::tempdir().expect("temp");
        let config = RuntimeConfig::create_default(temp.path().join("config.toml"), temp.path())
            .expect("config");
        let state = AppState::open(config).expect("state");
        let project = handle(
            &state,
            "POST",
            &["projects"],
            &HashMap::new(),
            &json!({"name":"Native writing"}),
        )
        .expect("route")
        .expect("project");
        let project_id = project["id"].as_str().unwrap();
        let bible = handle(
            &state,
            "GET",
            &["world-bible"],
            &HashMap::from([(String::from("project_id"), project_id.to_owned())]),
            &json!({}),
        )
        .expect("route")
        .expect("bible");
        let world = bible["worlds"]
            .as_array()
            .unwrap()
            .iter()
            .find(|world| world["id"] == "WORLD-BIBLE-MAIN")
            .expect("shared world");
        assert_eq!(world["name"], "Main");
        assert_eq!(world["branches"][0]["name"], "Main");
    }

    #[tokio::test]
    async fn revision_restore_keeps_history_and_restores_document_content() {
        let temp = tempfile::tempdir().expect("temp");
        let config = RuntimeConfig::create_default(temp.path().join("config.toml"), temp.path())
            .expect("config");
        let state = AppState::open(config).expect("state");
        state
            .store
            .insert(
                "projects",
                json!({"id":"P-REV","name":"Revision","slug":"revision"}),
            )
            .expect("project");
        let empty = HashMap::new();
        let document = handle(
            &state,
            "POST",
            &["documents"],
            &empty,
            &json!({"project_id":"P-REV","title":"Draft","content":"first"}),
        )
        .expect("route")
        .expect("create");
        let document_id = document["id"].as_str().unwrap();
        handle(
            &state,
            "PATCH",
            &["documents", document_id],
            &empty,
            &json!({"content":"second"}),
        )
        .expect("route")
        .expect("update");
        let revisions = handle(
            &state,
            "GET",
            &["revisions", "document", document_id],
            &empty,
            &json!({}),
        )
        .expect("route")
        .expect("list");
        let revision_id = revisions["revisions"][0]["id"].as_str().unwrap();
        let restored = handle(
            &state,
            "POST",
            &["revisions", revision_id, "restore"],
            &empty,
            &json!({"note":"undo"}),
        )
        .expect("route")
        .expect("restore");
        assert_eq!(restored["content"], "first");
        let revisions_after = state
            .store
            .list(
                "workspace_revisions",
                &[("resource_id", json!(document_id))],
            )
            .expect("history");
        assert_eq!(revisions_after.len(), 2);
    }
}
