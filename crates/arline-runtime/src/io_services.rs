//! Local manuscript, feedback dataset, recovery and artifact services.
use crate::{foundation::FoundationStore, ApiError, ApiResult, AppState};
use axum::{
    body::Body,
    http::{header, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use base64::Engine;
use serde_json::{json, Map, Value};
use std::{
    collections::HashMap,
    fs,
    io::Write,
    path::{Path, PathBuf},
    time::Duration,
};

fn text<'a>(value: &'a Value, key: &str, default: &'a str) -> &'a str {
    value.get(key).and_then(Value::as_str).unwrap_or(default)
}
fn q<'a>(query: &'a HashMap<String, String>, key: &str) -> Option<&'a str> {
    query.get(key).map(String::as_str)
}
fn timestamp() -> String {
    chrono::Utc::now().to_rfc3339()
}
fn good(value: Value) -> ApiResult<Response> {
    Ok(Json(value).into_response())
}
fn table(resource: &str) -> ApiResult<&'static str> {
    Ok(match resource {
        "project" => "projects",
        "world" => "worlds",
        "branch" => "world_branches",
        "document" => "workspace_documents",
        "folder" => "workspace_folders",
        "entity_family" => "entity_families",
        "entity_variant" => "entity_variants",
        "relationship" => "relationships",
        "fact" => "canon_facts",
        "tag" => "workspace_tags",
        "timeline" => "timeline_events",
        "template" => "entity_templates",
        "snapshot" => "world_snapshots",
        "session" => "sessions",
        "turn" => "turns",
        "collection" => "workspace_collections",
        "media" => "resource_media",
        _ => return Err(ApiError::bad_request("Unsupported resource type")),
    })
}
fn resource(state: &AppState, kind: &str, id: &str) -> ApiResult<Value> {
    state
        .store
        .get(table(kind)?, id)?
        .ok_or_else(|| ApiError::not_found("Resource not found"))
}
fn visible(state: &AppState, kind: &str, rows: Vec<Value>) -> ApiResult<Vec<Value>> {
    let foundation = FoundationStore::from_store(state.store.clone());
    let mut result = Vec::new();
    for row in rows {
        if let Some(id) = row["id"].as_str() {
            if foundation.is_hidden(kind, id, false, false)? {
                continue;
            }
        }
        result.push(row)
    }
    Ok(result)
}

pub fn split_manuscript(body: &Value) -> ApiResult<Vec<Value>> {
    let content = text(body, "text", "").replace("\r\n", "\n");
    let content = content.trim();
    let title = text(body, "title", "Imported manuscript");
    if !body
        .get("split_headings")
        .and_then(Value::as_bool)
        .unwrap_or(true)
    {
        return Ok(vec![
            json!({"title":title,"content":content,"document_type":text(body,"default_type","scene")}),
        ]);
    }
    if content.is_empty() {
        return Ok(Vec::new());
    }
    let mut headings = Vec::new();
    let mut offset = 0;
    for line in content.split_inclusive('\n') {
        let raw = line.trim_end_matches('\n');
        let level = raw.bytes().take_while(|b| *b == b'#').count();
        if (1..=3).contains(&level)
            && raw.get(level..).is_some_and(|rest| {
                rest.starts_with(char::is_whitespace) && !rest.trim().is_empty()
            })
        {
            headings.push((
                offset,
                offset + raw.len(),
                level,
                raw[level..].trim().to_owned(),
            ))
        }
        offset += line.len();
    }
    if headings.is_empty() {
        return Ok(vec![
            json!({"title":if title.trim().is_empty(){"Imported manuscript"}else{title.trim()},"content":content,"document_type":"scene"}),
        ]);
    }
    let mut sections = Vec::new();
    let prefix = content[..headings[0].0].trim();
    if !prefix.is_empty() {
        sections.push(json!({"title":if title.trim().is_empty(){"Imported notes"}else{title.trim()},"content":prefix,"document_type":"note"}))
    }
    for (index, (_, start, level, heading)) in headings.iter().enumerate() {
        let end = headings
            .get(index + 1)
            .map(|h| h.0)
            .unwrap_or(content.len());
        sections.push(json!({"title":heading,"content":content[*start..end].trim(),"document_type":if *level==1{"chapter"}else{"scene"}}));
    }
    Ok(sections)
}

fn import_manuscript(state: &AppState, body: &Value) -> ApiResult<Value> {
    let project = text(body, "project_id", "");
    resource(state, "project", project)?;
    let sections = split_manuscript(body)?;
    if sections.is_empty() {
        return Err(ApiError::bad_request("Import text is empty"));
    }
    let foundation = FoundationStore::from_store(state.store.clone());
    let job = foundation.create_job(
        "manuscript_import",
        Some(project),
        &json!({"count":sections.len()}),
        "Importing manuscript",
    )?;
    let job_id = job["id"].as_str().unwrap();
    let mut created = Vec::new();
    for (index, section) in sections.iter().enumerate() {
        let document_type = text(section, "document_type", "scene");
        let document_type = if ["scene", "chapter", "note", "outline", "research", "lore"]
            .contains(&document_type)
        {
            document_type
        } else {
            "scene"
        };
        let payload = json!({"project_id":project,"title":section["title"],"document_type":document_type,"content":section["content"],"folder_id":body.get("folder_id"),"status":"writing"});
        let result =
            crate::workspace::handle(state, "POST", &["documents"], &HashMap::new(), &payload)
                .ok_or_else(|| ApiError::internal("Document service is unavailable"))?;
        match result {
            Ok(document) => created.push(document),
            Err(error) => {
                state.store.update(
                    "workspace_jobs",
                    job_id,
                    json!({"status":"failed","message":error.message,"updated_at":timestamp()}),
                )?;
                return Err(error);
            }
        }
        state.store.update("workspace_jobs",job_id,json!({"status":"running","progress":(index+1) as f64/sections.len() as f64,"message":format!("Imported {}/{}",index+1,sections.len())}))?;
    }
    let ids: Vec<_> = created.iter().map(|v| v["id"].clone()).collect();
    let job=state.store.update("workspace_jobs",job_id,json!({"status":"done","progress":1.0,"message":"Import complete","result":{"document_ids":ids}}))?;
    for document in &created {
        crate::foundation::memory::refresh_document(state, document["id"].as_str().unwrap_or(""))?;
    }
    foundation.log_activity(
        Some(project),
        "manuscript_import",
        Some("project"),
        Some(project),
        &format!("Imported {} manuscript items", created.len()),
        &json!({}),
    )?;
    Ok(json!({"job":job,"documents":created}))
}

fn export_project(state: &AppState, id: &str) -> ApiResult<Value> {
    let foundation = FoundationStore::from_store(state.store.clone());
    let project = resource(state, "project", id)?;
    let mut result = json!({"format":"arline-project-bundle","version":1,"schema_version":7,"boundary":"Project files and project-local context only; Library sheets remain references.","project":project});
    for (key, table) in [
        ("folders", "workspace_folders"),
        ("documents", "workspace_documents"),
        ("tags", "workspace_tags"),
        ("manifest_refs", "project_manifest_refs"),
        ("overlays", "project_overlays"),
        ("scene_cards", "project_scene_cards"),
    ] {
        result[key] = json!(state.store.list(table, &[("project_id", json!(id))])?)
    }
    result["active_scene"] = state
        .store
        .list("project_active_scenes", &[("project_id", json!(id))])?
        .into_iter()
        .next()
        .unwrap_or(Value::Null);
    result["run_profiles"] = json!(foundation.run_profiles(Some(id))?);
    Ok(result)
}
fn export_bible(state: &AppState, query: &HashMap<String, String>) -> ApiResult<Value> {
    let foundation = FoundationStore::from_store(state.store.clone());
    let world = q(query, "world_id");
    let branch = q(query, "branch_id");
    let mut filters = Vec::new();
    if let Some(world) = world {
        filters.push(("world_id", json!(world)))
    }
    if let Some(branch) = branch {
        filters.push(("branch_id", json!(branch)))
    }
    let worlds = if let Some(id) = world {
        vec![resource(state, "world", id)?]
    } else {
        state.store.list("worlds", &[])?
    };
    let mut result = json!({"format":"arline-world-bible-bundle","version":1,"schema_version":7,
  "worlds":visible(state,"world",worlds)?,"families":visible(state,"entity_family",state.store.list("entity_families",&[])?)?,
  "variants":visible(state,"entity_variant",state.store.list("entity_variants",&filters)?)?,
  "folders":visible(state,"folder",state.store.list("workspace_folders",&[("project_id",json!("PROJ-WORLD-BIBLE"))])?)?,
  "collections":foundation.collections("world_bible",None)?,"saved_views":foundation.saved_views("world_bible",None)?});
    for (key, table, kind) in [
        ("relationships", "relationships", "relationship"),
        ("facts", "canon_facts", "fact"),
        ("timeline", "timeline_events", "timeline"),
    ] {
        result[key] = if world.is_some() {
            json!(visible(state, kind, state.store.list(table, &filters)?)?)
        } else {
            json!([])
        }
    }
    Ok(result)
}

fn final_story(turn: &Value) -> &str {
    if text(turn, "feedback_status", "") == "edited_accept"
        && !text(turn, "edited_story", "").is_empty()
    {
        text(turn, "edited_story", "")
    } else {
        text(turn, "story", "")
    }
}
pub(crate) fn dataset_stats(state: &AppState) -> ApiResult<Value> {
    let mut counts = json!({"total":0,"unreviewed":0,"accepted":0,"edited_accept":0,"rejected":0,"sft_ready":0,"preference_ready":0});
    for row in state.store.query(
        "SELECT feedback_status,COUNT(*) AS n FROM turns GROUP BY feedback_status",
        &[],
    )? {
        let key = text(&row, "feedback_status", "");
        let n = row["n"].as_i64().unwrap_or(0);
        counts["total"] = json!(counts["total"].as_i64().unwrap_or(0) + n);
        counts[key] = json!(n)
    }
    counts["sft_ready"] = json!(
        counts["accepted"].as_i64().unwrap_or(0) + counts["edited_accept"].as_i64().unwrap_or(0)
    );
    counts["preference_ready"] = counts["edited_accept"].clone();
    Ok(counts)
}
fn feedback_queue(state: &AppState, query: &HashMap<String, String>) -> ApiResult<Value> {
    let status = q(query, "status").unwrap_or("unreviewed");
    let limit = q(query, "limit")
        .and_then(|v| v.parse::<i64>().ok())
        .unwrap_or(100)
        .clamp(1, 500);
    let mut sql="SELECT t.*,s.title AS session_title,s.project_id,s.world_id,s.branch_id,s.parent_session_id,s.forked_from_turn_id FROM turns t JOIN sessions s ON s.id=t.session_id WHERE t.feedback_status=? AND s.archived=0".to_owned();
    let project = q(query, "project_id");
    if project.is_some() {
        sql.push_str(" AND s.project_id=?")
    }
    sql.push_str(" ORDER BY t.updated_at DESC,t.created_at DESC LIMIT ?");
    let rows = if let Some(project) = project {
        state.store.query(&sql, &[&status, &project, &limit])?
    } else {
        state.store.query(&sql, &[&status, &limit])?
    };
    Ok(
        json!({"items":rows.into_iter().map(|mut row|{row["final_story"]=json!(final_story(&row));row}).collect::<Vec<_>>()}),
    )
}
fn preference_pairs(state: &AppState, query: &HashMap<String, String>) -> ApiResult<Value> {
    let limit = q(query, "limit")
        .and_then(|v| v.parse::<usize>().ok())
        .unwrap_or(100)
        .clamp(1, 300);
    let mut groups: HashMap<(String, String), Vec<Value>> = HashMap::new();
    for row in state.store.query("SELECT * FROM sessions WHERE parent_session_id IS NOT NULL AND forked_from_turn_id IS NOT NULL AND archived=0 ORDER BY updated_at DESC",&[])?{
  if q(query,"project_id").is_some_and(|id|row["project_id"].as_str()!=Some(id)){continue}
  groups.entry((text(&row,"parent_session_id","").into(),text(&row,"forked_from_turn_id","").into())).or_default().push(row);
 }
    let mut pairs = Vec::new();
    for ((parent_id, turn_id), siblings) in groups {
        let parent = resource(state, "turn", &turn_id)?;
        let mut candidates = Vec::new();
        if let Some(next)=state.store.query("SELECT * FROM turns WHERE session_id=? AND rowid>(SELECT rowid FROM turns WHERE id=?) ORDER BY rowid LIMIT 1",&[&parent_id,&turn_id])?.into_iter().next(){candidates.push(json!({"session_id":parent_id,"turn_id":next["id"],"story":next["story"],"label":"Original"}))}
        for sibling in siblings {
            let session_id = text(&sibling, "id", "");
            if let Some(first) = state
                .store
                .query(
                    "SELECT * FROM turns WHERE session_id=? ORDER BY rowid LIMIT 1",
                    &[&session_id],
                )?
                .into_iter()
                .next()
            {
                candidates.push(json!({"session_id":session_id,"turn_id":first["id"],"story":first["story"],"label":sibling["title"]}))
            }
        }
        if candidates.len() >= 2 {
            pairs.push(json!({"parent_session_id":parent_id,"forked_from_turn_id":turn_id,"prompt":parent["user_prompt"],"context_story":parent["story"],"candidates":candidates}))
        }
    }
    pairs.truncate(limit);
    Ok(json!({"items":pairs}))
}
fn export_dataset(state: &AppState, kind: &str) -> ApiResult<Value> {
    if !["master", "sft", "preference", "eval"].contains(&kind) {
        return Err(ApiError::bad_request(
            "dataset kind must be master, sft, preference, or eval",
        ));
    }
    let config = state.runtime_config()?;
    let root = config.resolve(&config.str("history.dataset_root", "data/datasets"));
    fs::create_dir_all(&root)?;
    let name = format!(
        "arline-{kind}-v0.1-{}.jsonl",
        chrono::Utc::now().format("%Y%m%dT%H%M%S%fZ")
    );
    let path = root.join(&name);
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)?;
    let mut count = 0;
    for turn in state.store.query("SELECT t.*,s.title AS session_title FROM turns t JOIN sessions s ON s.id=t.session_id ORDER BY t.created_at,t.rowid",&[])?{
  let status=text(&turn,"feedback_status","unreviewed");if (kind=="sft"&&!matches!(status,"accepted"|"edited_accept"))||(kind=="preference"&&(status!="edited_accept"||text(&turn,"edited_story","").is_empty()))||(kind=="eval"&&status!="rejected"&&turn["feedback_issues"].as_array().is_none_or(Vec::is_empty)){continue}
  let mut record=json!({"dataset_schema":"arline-feedback-0.1","session_id":turn["session_id"],"session_title":turn["session_title"],"turn_id":turn["id"],"run_id":turn["run_id"],"created_at":turn["created_at"],"prompt":turn["user_prompt"],"wcf":turn["wcf"],"aif_core":turn["aif_core"],"session_context":turn["session_context"],"workspace_context":turn["workspace_context"],"workspace_scope":turn["workspace_scope"],"workspace_refs":turn["workspace_refs"],"lineage":turn["lineage"],"model":turn["model"],"mode":turn["mode"],"reasoning":turn["reasoning"],"reasoning_trace":turn["reasoning_text"],"projection_mode":turn["projection_mode"],"generated":turn["story"],"feedback":{"status":status,"issues":turn["feedback_issues"],"note":turn["feedback_note"]},"validator":turn["post_validation"],"stats":turn["stats"]});
  match kind{"master"=>record["final_text"]=json!(final_story(&turn)),"sft"=>record["target"]=json!(final_story(&turn)),"preference"=>{record["chosen"]=turn["edited_story"].clone();record["rejected"]=turn["story"].clone()},"eval"=>record["expected_status"]=json!(status),_=>unreachable!()}
  serde_json::to_writer(&mut file,&record).map_err(|e|ApiError::internal(e.to_string()))?;file.write_all(b"\n")?;count+=1;
 }
    file.sync_all()?;
    Ok(
        json!({"ok":true,"kind":kind,"rows":count,"filename":name,"download_url":format!("/dataset-downloads/{name}")}),
    )
}

fn save_run(state: &AppState, run_id: &str) -> ApiResult<Value> {
    if run_id.is_empty()
        || !run_id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '+'))
    {
        return Err(ApiError::bad_request("Invalid run ID"));
    }
    let turn = state
        .store
        .query(
            "SELECT * FROM turns WHERE run_id=? ORDER BY rowid DESC LIMIT 1",
            &[&run_id],
        )?
        .into_iter()
        .next()
        .ok_or_else(|| {
            ApiError::not_found("Run is no longer in memory. Generate it again before saving.")
        })?;
    let config = state.runtime_config()?;
    let root = config.resolve(&config.str("artifacts.saved_root", "output/saved"));
    fs::create_dir_all(&root)?;
    let mut actual = run_id.to_owned();
    let mut directory = root.join(&actual);
    let mut suffix = 2;
    loop {
        match fs::create_dir(&directory) {
            Ok(()) => break,
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                actual = format!("{run_id}-{suffix:02}");
                directory = root.join(&actual);
                suffix += 1
            }
            Err(e) => return Err(e.into()),
        }
    }
    let analysis = crate::analysis::cached(state, run_id)?.unwrap_or(json!({}));
    let mut files = Map::new();
    let mut entries = Vec::new();
    let mut add = |kind: &str, extension: &str, data: Vec<u8>| -> ApiResult<()> {
        let name = format!("{kind}-{actual}.{extension}");
        fs::write(directory.join(&name), &data)?;
        files.insert(kind.into(), json!(name));
        entries.push((name, data));
        Ok(())
    };
    for (key, value, extension) in [
        ("story", text(&turn, "story", ""), "txt"),
        ("wcf", text(&turn, "wcf", ""), "wcf"),
        ("aif-core", text(&turn, "aif_core", ""), "txt"),
    ] {
        add(
            key,
            extension,
            format!("{}\n", value.trim_end()).into_bytes(),
        )?
    }
    if !text(&turn, "reasoning_text", "").is_empty() {
        add(
            "reasoning",
            "txt",
            format!("{}\n", text(&turn, "reasoning_text", "").trim_end()).into_bytes(),
        )?
    }
    let payloads = [
        ("stats", turn["stats"].clone()),
        ("post-validation", turn["post_validation"].clone()),
        ("wcf-validation", turn["wcf_validation"].clone()),
        (
            "writer-context",
            analysis
                .get("writer_context")
                .cloned()
                .unwrap_or(Value::Null),
        ),
        ("projections", turn["projections"].clone()),
        (
            "semantic-core",
            analysis
                .get("semantic_core")
                .cloned()
                .unwrap_or(Value::Null),
        ),
        (
            "world-runtime",
            analysis
                .get("world_runtime")
                .cloned()
                .unwrap_or(Value::Null),
        ),
        (
            "narrative-runtime",
            analysis
                .get("narrative_runtime")
                .cloned()
                .unwrap_or(Value::Null),
        ),
        (
            "writer-request",
            json!({"run_id":actual,"mode":turn["mode"],"reasoning":turn["reasoning"],"projection_mode":turn["projection_mode"],"model":turn["model"],"model_input":analysis.get("model_input")}),
        ),
        (
            "lmstudio-response",
            analysis.get("raw_response").cloned().unwrap_or(Value::Null),
        ),
        (
            "extracted-state",
            analysis
                .get("extracted_state")
                .cloned()
                .unwrap_or(Value::Null),
        ),
        (
            "events",
            analysis.get("events").cloned().unwrap_or(Value::Null),
        ),
        ("analysis", analysis.clone()),
    ];
    for (kind, value) in payloads {
        add(
            kind,
            "json",
            serde_json::to_vec_pretty(&value).map_err(|e| ApiError::internal(e.to_string()))?,
        )?
    }
    let manifest = json!({"run_id":actual,"mode":turn["mode"],"reasoning":turn["reasoning"],"projection_mode":turn["projection_mode"],"model":turn["model"],"files":files});
    let name = format!("manifest-{actual}.json");
    let bytes =
        serde_json::to_vec_pretty(&manifest).map_err(|e| ApiError::internal(e.to_string()))?;
    fs::write(directory.join(&name), &bytes)?;
    files.insert("manifest".into(), json!(name));
    entries.push((format!("manifest-{actual}.json"), bytes));
    let archive_name = format!("Arline-{actual}.zip");
    let file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(root.join(&archive_name))?;
    let mut archive = zip::ZipWriter::new(file);
    for (name, bytes) in entries {
        archive
            .start_file(
                name,
                zip::write::SimpleFileOptions::default()
                    .compression_method(zip::CompressionMethod::Stored),
            )
            .map_err(|e| ApiError::internal(e.to_string()))?;
        archive.write_all(&bytes)?;
    }
    archive
        .finish()
        .map_err(|e| ApiError::internal(e.to_string()))?;
    Ok(
        json!({"ok":true,"run_id":actual,"directory":directory,"archive_name":archive_name,"download_url":format!("/downloads/{archive_name}"),"files":files}),
    )
}

pub fn download(state: &AppState, kind: &str, name: &str) -> ApiResult<Response> {
    if name.is_empty()
        || Path::new(name).file_name().and_then(|n| n.to_str()) != Some(name)
        || name.contains(['\\', '/'])
    {
        return Err(ApiError::bad_request("Invalid filename"));
    }
    let config = state.runtime_config()?;
    let (key, default, mime) = match kind {
        "downloads" => ("artifacts.saved_root", "output/saved", "application/zip"),
        "dataset-downloads" => (
            "history.dataset_root",
            "data/datasets",
            "application/x-ndjson",
        ),
        _ => return Err(ApiError::not_found("Download not found")),
    };
    let root = config
        .resolve(&config.str(key, default))
        .canonicalize()
        .map_err(|_| ApiError::not_found("Download not found"))?;
    let path = root
        .join(name)
        .canonicalize()
        .map_err(|_| ApiError::not_found("Download not found"))?;
    if !path.starts_with(root) || !path.is_file() {
        return Err(ApiError::not_found("Download not found"));
    }
    Response::builder()
        .header(header::CONTENT_TYPE, mime)
        .header(
            header::CONTENT_DISPOSITION,
            format!("attachment; filename=\"{name}\""),
        )
        .header(header::X_CONTENT_TYPE_OPTIONS, "nosniff")
        .body(Body::from(fs::read(path)?))
        .map_err(|e| ApiError::internal(e.to_string()))
}

pub async fn handle(
    state: &AppState,
    method: &str,
    path: &[&str],
    query: &HashMap<String, String>,
    body: &Value,
) -> Option<ApiResult<Response>> {
    let result=match(method,path){
 ("POST",["import","manuscript","preview"])=>split_manuscript(body).map(|sections|json!({"destination":"project_manuscript","count":sections.len(),"sections":sections.into_iter().map(|s|json!({"title":s["title"],"document_type":s["document_type"],"chars":text(&s,"content","").chars().count(),"words":text(&s,"content","").split_whitespace().count()})).collect::<Vec<_>>()})),
 ("POST",["import","manuscript"])=>import_manuscript(state,body),
 ("GET",["export","project",id])=>export_project(state,id),
 ("GET",["export","world-bible"])=>export_bible(state,query),
 ("GET",["dataset","stats"])=>dataset_stats(state),
 ("POST",["dataset","export",kind])=>export_dataset(state,kind),
 ("GET",["feedback","queue"])=>feedback_queue(state,query),
 ("GET",["feedback","comparisons"])=>preference_pairs(state,query),
 ("POST",["save"])=>save_run(state,text(body,"run_id","")),
 ("GET",["backups"])=>backups(state),
 ("POST",["storage","reset"])=>return Some(reset_storage(state,body).await.and_then(good)),
 ("POST",["media",id,"describe"])=>return Some(describe_media(state,id,body).await.and_then(good)),
 _=>return None,
 };
    Some(result.and_then(good))
}

fn backups(state: &AppState) -> ApiResult<Value> {
    let path = &state.store.path;
    let dir = path.parent().unwrap().join("backups");
    let mut rows = Vec::new();
    if dir.is_dir() {
        for entry in fs::read_dir(dir)? {
            let entry = entry?;
            let metadata = entry.metadata()?;
            if metadata.is_file() {
                let time: chrono::DateTime<chrono::Utc> = metadata.modified()?.into();
                rows.push(json!({"name":entry.file_name().to_string_lossy(),"bytes":metadata.len(),"modified_at":time.to_rfc3339()}))
            }
        }
    }
    rows.sort_by(|a, b| b["modified_at"].as_str().cmp(&a["modified_at"].as_str()));
    Ok(
        json!({"database_name":path.file_name().unwrap().to_string_lossy(),"database_bytes":fs::metadata(path)?.len(),"backups":rows}),
    )
}
async fn reset_storage(state: &AppState, body: &Value) -> ApiResult<Value> {
    let mode = text(body, "mode", "");
    let expected = match mode {
        "database" => "RESET DATABASE",
        "complete" => "DELETE EVERYTHING",
        _ => {
            return Err(ApiError::bad_request(
                "Reset mode must be 'database' or 'complete'",
            ))
        }
    };
    if text(body, "confirmation", "").trim() != expected {
        return Err(ApiError::bad_request(format!(
            "Type {expected} exactly to confirm"
        )));
    }
    let _exclusive = state.storage_gate.clone().write_owned().await;
    let path = state.store.path.canonicalize()?;
    let base = path.parent().unwrap();
    let config = state.runtime_config()?;
    let mut removed = Vec::new();
    let mut candidates = vec![base.join("media"), base.join("backups")];
    for (key, default) in [
        ("history.dataset_root", "data/datasets"),
        ("artifacts.output_root", "output"),
        ("artifacts.saved_root", "output/saved"),
    ] {
        candidates.push(config.resolve(&config.str(key, default)))
    }
    if mode == "complete" {
        for candidate in &candidates {
            if candidate.exists() {
                let resolved = candidate.canonicalize()?;
                let managed_root = config.root.canonicalize()?;
                if !resolved.starts_with(&managed_root)
                    || resolved == managed_root
                    || resolved == base
                {
                    return Err(ApiError::bad_request(
                        "Refusing to reset a directory outside managed app storage",
                    ));
                }
            }
        }
    }
    let mut recovery = Vec::new();
    if mode == "database" {
        let dir = base.join("backups");
        fs::create_dir_all(&dir)?;
        let backup = dir.join(format!(
            "{}.before-reset-{}.db",
            path.file_stem().unwrap().to_string_lossy(),
            uuid::Uuid::new_v4()
        ));
        let source = state.store.connection()?;
        let mut target = rusqlite::Connection::open(&backup)?;
        let copy = rusqlite::backup::Backup::new(&source, &mut target)?;
        copy.run_to_completion(128, Duration::from_millis(10), None)?;
        recovery.push(backup);
    }
    for candidate in [
        &path,
        &PathBuf::from(format!("{}-wal", path.display())),
        &PathBuf::from(format!("{}-shm", path.display())),
    ] {
        if candidate.exists() {
            fs::remove_file(candidate)?
        }
    }
    crate::AppState::open(config)?;
    if mode == "complete" {
        candidates.sort_by_key(|p| p.components().count());
        let mut deleted = Vec::<PathBuf>::new();
        for candidate in candidates {
            if candidate.exists() {
                let resolved = candidate.canonicalize()?;
                if deleted.iter().any(|p| resolved.starts_with(p)) {
                    continue;
                }
                fs::remove_dir_all(&resolved)?;
                deleted.push(resolved.clone());
                removed.push(resolved);
            }
        }
    }
    Ok(
        json!({"ok":true,"mode":mode,"databases":[path],"backups":recovery,"removed_directories":removed,"restart_required":false}),
    )
}

async fn describe_media(state: &AppState, id: &str, body: &Value) -> ApiResult<Value> {
    let foundation = FoundationStore::from_store(state.store.clone());
    let (bytes, mime) = foundation.media_content(id)?;
    let config = state.runtime_config()?;
    let models = crate::models::query_models(state, body).await?;
    let model = text(body, "model", "");
    let model = if model.is_empty() {
        config.str("lmstudio.model", "")
    } else {
        model.to_owned()
    };
    let metadata = models["models"]
        .as_array()
        .and_then(|items| {
            items
                .iter()
                .find(|item| item["key"].as_str() == Some(&model))
        })
        .ok_or_else(|| ApiError::bad_request("Select a model first"))?;
    if metadata
        .pointer("/capabilities/vision")
        .and_then(Value::as_bool)
        != Some(true)
    {
        return Err(ApiError::bad_request(
            "The selected model does not report vision support in LM Studio",
        ));
    }
    let reasoning = metadata
        .pointer("/reasoning/allowed_options")
        .and_then(Value::as_array)
        .is_some_and(|options| options.iter().any(|item| item == "off"));
    let prompt = text(body, "prompt", "");
    let prompt = if prompt.trim().is_empty() {
        "Describe this image precisely for a fiction/worldbuilding reference library. Only describe visually observable details. Separate uncertain impressions from facts. Do not invent identity, backstory, measurements, relationships, or hidden anatomy."
    } else {
        prompt.trim()
    };
    let mut payload = json!({"model":model,"input":[{"type":"message","content":prompt},{"type":"image","data_url":format!("data:{mime};base64,{}",base64::engine::general_purpose::STANDARD.encode(bytes))}],"system_prompt":"You are Arline's visual reference describer. Return a concise, concrete visual description. This output is a reviewable media-description proposal, not canon.","stream":false,"temperature":0.2,"top_p":0.9,"top_k":20,"min_p":0.0,"max_output_tokens":1200,"repeat_penalty":1.02,"context_length":config.u64("model_load.context_length",32768).min(16384)});
    if reasoning {
        payload["reasoning"] = json!("off")
    }
    let server = text(body, "server_url", "");
    let server = if server.is_empty() {
        config.str("lmstudio.base_url", "http://127.0.0.1:1234")
    } else {
        server.to_owned()
    };
    let mut request = state
        .client
        .post(format!("{}/api/v1/chat", server.trim_end_matches('/')))
        .json(&payload);
    let key = text(body, "api_key", "");
    let key = if key.is_empty() {
        config.str("lmstudio.api_key", "")
    } else {
        key.to_owned()
    };
    if !key.is_empty() {
        request = request.bearer_auth(key)
    }
    let response = request
        .send()
        .await
        .map_err(|e| ApiError::new(StatusCode::SERVICE_UNAVAILABLE, e.to_string()))?;
    if !response.status().is_success() {
        return Err(ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            response.text().await.unwrap_or_default(),
        ));
    }
    let result: Value = response
        .json()
        .await
        .map_err(|e| ApiError::internal(e.to_string()))?;
    let description = result["output"]
        .as_array()
        .map(|items| {
            items
                .iter()
                .filter(|item| item["type"] == "message")
                .filter_map(|item| item["content"].as_str())
                .collect::<Vec<_>>()
                .join("\n")
        })
        .unwrap_or_default();
    if description.trim().is_empty() {
        return Err(ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "LM Studio returned no image description",
        ));
    }
    Ok(
        json!({"media_id":id,"model":model,"description":description,"stats":result["stats"],"proposal":true,"saved":false,"canon_changed":false}),
    )
}
