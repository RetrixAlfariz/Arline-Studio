//! Resource lifecycle and foundation API contracts shared by the desktop and HTTP host.
use crate::{foundation::FoundationStore, ApiError, ApiResult, AppState};
use axum::http::StatusCode;
use serde_json::{json, Value};
use std::collections::HashMap;

fn resource_table(kind: &str) -> ApiResult<&'static str> {
    Ok(match kind {
        "project" => "projects",
        "world" => "worlds",
        "branch" => "world_branches",
        "folder" => "workspace_folders",
        "document" => "workspace_documents",
        "entity_family" => "entity_families",
        "entity_variant" => "entity_variants",
        "relationship" => "relationships",
        "fact" => "canon_facts",
        "tag" => "workspace_tags",
        "snapshot" => "world_snapshots",
        "timeline" => "timeline_events",
        "session" => "sessions",
        _ => return Err(ApiError::not_found("Resource not found")),
    })
}
fn get(state: &AppState, kind: &str, id: &str) -> ApiResult<Value> {
    state
        .store
        .get(resource_table(kind)?, id)?
        .ok_or_else(|| ApiError::not_found("Resource not found"))
}
fn strval<'a>(body: &'a Value, key: &str) -> &'a str {
    body[key].as_str().unwrap_or("")
}
fn folder_visible(
    state: &AppState,
    foundation: &FoundationStore,
    document: &Value,
) -> ApiResult<bool> {
    let mut parent = document["folder_id"].as_str().map(str::to_owned);
    let mut seen = std::collections::HashSet::new();
    while let Some(id) = parent {
        if !seen.insert(id.clone()) || foundation.is_hidden("folder", &id, false, false)? {
            return Ok(false);
        }
        let Some(row) = state.store.get("workspace_folders", &id)? else {
            return Ok(false);
        };
        if row["project_id"] != document["project_id"] {
            return Ok(false);
        }
        parent = row["parent_id"].as_str().map(str::to_owned);
    }
    Ok(true)
}
fn home(state: &AppState, query: &HashMap<String, String>) -> ApiResult<Value> {
    let foundation = FoundationStore::from_store(state.store.clone());
    let project = query.get("project_id").map(String::as_str);
    let mut documents = Vec::new();
    if let Some(id) = project {
        for row in state
            .store
            .list("workspace_documents", &[("project_id", json!(id))])?
        {
            if !foundation.is_hidden("document", strval(&row, "id"), false, false)?
                && folder_visible(state, &foundation, &row)?
            {
                documents.push(row)
            }
        }
    }
    documents.sort_by(|a, b| b["updated_at"].as_str().cmp(&a["updated_at"].as_str()));
    documents.truncate(8);
    let mut sql="SELECT s.*,(SELECT COUNT(*) FROM turns t WHERE t.session_id=s.id) AS turn_count,(SELECT user_prompt FROM turns t WHERE t.session_id=s.id ORDER BY rowid DESC LIMIT 1) AS prompt_preview FROM sessions s WHERE s.archived=0".to_owned();
    let sessions = if let Some(id) = project {
        sql.push_str(" AND s.project_id=? ORDER BY s.pinned DESC,s.updated_at DESC");
        state.store.query(&sql, &[&id])?
    } else {
        sql.push_str(" ORDER BY s.pinned DESC,s.updated_at DESC");
        state.store.query(&sql, &[])?
    };
    let mut chats = Vec::new();
    for row in sessions {
        if !foundation.is_hidden("session", strval(&row, "id"), false, false)? {
            chats.push(row)
        }
        if chats.len() == 8 {
            break;
        }
    }
    let active = if let Some(id) = project {
        state
            .store
            .list("project_active_scenes", &[("project_id", json!(id))])?
            .into_iter()
            .next()
            .unwrap_or(Value::Null)
    } else {
        Value::Null
    };
    let mut issues = foundation.list_issues(project, Some("open"), 200)?;
    issues.retain(|row| {
        query
            .get("world_id")
            .is_none_or(|id| row["world_id"] == *id)
            && query
                .get("branch_id")
                .is_none_or(|id| row["branch_id"] == *id)
    });
    issues.truncate(8);
    Ok(
        json!({"active_scene":active,"recent_documents":documents,"recent_chats":chats,"issues":issues,"activity":foundation.activity(project,10)?,"feedback":crate::io_services::dataset_stats(state)?,"favorites":foundation.favorites(project)?}),
    )
}
fn checked_delete(state: &AppState, table: &str, id: &str, builtin: bool) -> ApiResult<Value> {
    let row = state
        .store
        .get(table, id)?
        .ok_or_else(|| ApiError::not_found("Resource not found"))?;
    if builtin && (row["builtin"].as_bool().unwrap_or(false) || row["builtin"].as_i64() == Some(1))
    {
        return Err(ApiError::bad_request("Built-in resources are protected"));
    }
    state
        .store
        .connection()?
        .execute(&format!("DELETE FROM {table} WHERE id=?"), [id])?;
    Ok(json!({"ok":true}))
}
pub fn forget(state: &AppState, kind: &str, id: &str) -> ApiResult<()> {
    let foundation = FoundationStore::from_store(state.store.clone());
    for media in foundation.media(Some(kind), Some(id), false)? {
        if let Some(media_id) = media["id"].as_str() {
            foundation.delete_media(media_id)?;
        }
    }
    let connection = state.store.connection()?;
    for table in [
        "resource_lifecycle",
        "resource_aliases",
        "workspace_collection_links",
        "workspace_favorites",
        "workspace_issues",
    ] {
        connection.execute(
            &format!("DELETE FROM {table} WHERE resource_type=? AND resource_id=?"),
            [kind, id],
        )?;
    }
    for mut stack in state.store.query("SELECT * FROM context_stack", &[])? {
        if let Some(refs) = stack["references"].as_array_mut() {
            let len = refs.len();
            refs.retain(|item| !(item["type"] == kind && item["id"] == id));
            if len != refs.len() {
                let stackid = stack["id"].as_str().unwrap_or("default");
                foundation.set_context(stackid, &stack)?;
            }
        }
    }
    Ok(())
}
fn permanent(state: &AppState, kind: &str, id: &str) -> ApiResult<Value> {
    let foundation = FoundationStore::from_store(state.store.clone());
    if foundation.lifecycle(kind, id)?["trashed_at"].is_null() {
        return Err(ApiError::new(
            StatusCode::CONFLICT,
            "Move the resource to Trash before deleting permanently",
        ));
    }
    get(state, kind, id)?;
    let path = match kind {
        "project" => vec!["projects", id],
        "world" => vec!["worlds", id],
        "branch" => vec!["branches", id],
        "folder" => vec!["folders", id],
        "document" => vec!["documents", id],
        "entity_family" => vec!["entities", "families", id],
        "entity_variant" => vec!["entities", "variants", id],
        "relationship" => vec!["relationships", id],
        "fact" => vec!["facts", id],
        "tag" => vec!["tags", id],
        "snapshot" => vec!["snapshots", id],
        "session" => {
            crate::generation::delete_history(state, "session", id)?;
            forget(state, kind, id)?;
            return Ok(json!({"ok":true}));
        }
        _ => {
            return Err(ApiError::bad_request(
                "Permanent delete is not supported for this resource",
            ))
        }
    };
    crate::workspace::handle(state, "DELETE", &path, &HashMap::new(), &json!({}))
        .ok_or_else(|| ApiError::internal("Delete service unavailable"))??;
    forget(state, kind, id)?;
    Ok(json!({"ok":true}))
}
pub fn handle(
    state: &AppState,
    method: &str,
    path: &[&str],
    query: &HashMap<String, String>,
    body: &Value,
) -> Option<ApiResult<Value>> {
    let foundation = FoundationStore::from_store(state.store.clone());
    let q = |key: &str| query.get(key).map(String::as_str);
    Some((||{match(method,path){
 ("GET",["home"])=>home(state,query),
 ("GET",["resources",kind,id])=>{
 let resource=get(state,kind,id)?;
 let tags=state.store.query("SELECT t.* FROM workspace_tags t JOIN workspace_tag_links l ON l.tag_id=t.id WHERE l.resource_type=? AND l.resource_id=?",&[kind,id])?;
 let collections=foundation.collections("world_bible",None)?.into_iter().filter(|row|row["links"].as_array().is_some_and(|links|links.iter().any(|link|link["resource_type"]==*kind&&link["resource_id"]==*id))).map(|row|json!({"id":row["id"],"name":row["name"]})).collect::<Vec<_>>();
 let backlinks=crate::workspace_advanced::handle(state,"GET",&["backlinks",kind,id],query,&json!({})).transpose()?.unwrap_or(json!({}));
 Ok(json!({"resource":resource,"resource_type":kind,"aliases":foundation.aliases(kind,id)?,"tags":tags,"collections":collections,"backlinks":backlinks,"lifecycle":foundation.lifecycle(kind,id)?}))},
 ("POST",["lifecycle",action])=>{
 let kind=strval(body,"resource_type");let id=strval(body,"resource_id");let resource=get(state,kind,id)?;
 match *action{"trash"=>{let result=foundation.trash(kind,id,Some(body.get("previous_state").filter(|v|v.as_object().is_some_and(|o|!o.is_empty())).unwrap_or(&resource)))?;foundation.log_activity(resource["project_id"].as_str(),"trash",Some(kind),Some(id),resource["name"].as_str().or(resource["title"].as_str()).or(resource["display_name"].as_str()).unwrap_or(""),&json!({}))?;Ok(result)},"archive"=>foundation.archive(kind,id,q("archived")!=Some("false")),"restore"=>foundation.restore(kind,id),_=>Err(ApiError::not_found("Unknown lifecycle action"))}},
 ("GET",["trash"])=>{let mut items=Vec::new();for mut item in foundation.list_trash(200)?{if let Ok(resource)=get(state,strval(&item,"resource_type"),strval(&item,"resource_id")){item["resource"]=resource;items.push(item)}}Ok(json!({"items":items}))},
 ("DELETE",["trash",kind,id])=>permanent(state,kind,id),
 ("POST",["aliases"])=>{let kind=strval(body,"resource_type");let id=strval(body,"resource_id");get(state,kind,id)?;foundation.add_alias(kind,id,strval(body,"alias"))},
 ("DELETE",["aliases",id])=>checked_delete(state,"resource_aliases",id,false),
 ("POST",["collections",id,"links"])=>{get(state,strval(body,"resource_type"),strval(body,"resource_id"))?;foundation.collection_link(id,strval(body,"resource_type"),strval(body,"resource_id"),body["sort_order"].as_i64().unwrap_or(0))},
 ("DELETE",["collections",id,"links",kind,rid])=>{state.store.connection()?.execute("DELETE FROM workspace_collection_links WHERE collection_id=? AND resource_type=? AND resource_id=?",[*id,*kind,*rid])?;Ok(json!({"ok":true}))},
 ("DELETE",["collections",id])=>checked_delete(state,"workspace_collections",id,false),
 ("DELETE",["saved-views",id])=>checked_delete(state,"saved_views",id,true),
 ("DELETE",["run-profiles",id])=>checked_delete(state,"run_profiles",id,true),
 ("POST",["run-profiles"])=>{if let Some(id)=body["id"].as_str(){if state.store.get("run_profiles",id)?.is_some_and(|row|row["builtin"].as_bool().unwrap_or(false)||row["builtin"].as_i64()==Some(1)){return Err(ApiError::bad_request("Built-in profiles are protected"))}}foundation.save_run_profile(body)},
 ("GET",["preferences"])=>foundation.preferences(q("scope_type").unwrap_or("app"),q("scope_id").unwrap_or("default")),
 ("PUT",["preferences"])=>{foundation.set_preference(body["scope_type"].as_str().unwrap_or("app"),body["scope_id"].as_str().unwrap_or("default"),strval(body,"key"),body.get("value").unwrap_or(&Value::Null))?;Ok(json!({"ok":true}))},
 ("DELETE",["favorites"])=>{foundation.unfavorite(q("project_id"),q("resource_type").unwrap_or(""),q("resource_id").unwrap_or(""))?;Ok(json!({"ok":true}))},
 ("GET",["issues"])=>{let mut rows=foundation.list_issues(q("project_id"),Some(q("status").unwrap_or("open")),200)?;rows.retain(|row|q("world_id").is_none_or(|id|row["world_id"]==id)&&q("branch_id").is_none_or(|id|row["branch_id"]==id));Ok(json!({"issues":rows}))},
 _=>Err(ApiError::not_found("unhandled foundation contract")),
 }})()).filter(|result|!matches!(result,Err(error) if error.message=="unhandled foundation contract"))
}
