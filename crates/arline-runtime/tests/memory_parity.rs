use arline_runtime::{config::RuntimeConfig, router, AppState};
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
    routing::post,
    Json as AxumJson,
};
use serde_json::{json, Value};
use tempfile::TempDir;
use tower::ServiceExt;

fn fixture() -> (TempDir, AppState) {
    let dir = tempfile::tempdir().unwrap();
    let cfg = RuntimeConfig::create_default(dir.path().join("config.toml"), dir.path()).unwrap();
    (dir, AppState::open(cfg).unwrap())
}
async fn request(state: &AppState, method: &str, uri: &str, body: Value) -> (StatusCode, Value) {
    let req = Request::builder()
        .method(method)
        .uri(uri)
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    let response = router(state.clone()).oneshot(req).await.unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 2 * 1024 * 1024)
        .await
        .unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or_else(|_| json!({})),
    )
}

#[tokio::test]
async fn retrieval_reindexes_fresh_text_and_keeps_scope_before_limit() {
    let (_dir, state) = fixture();
    let world = state.store.list("worlds", &[]).unwrap()[0]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let project = state.store.list("projects", &[]).unwrap()[0]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    state.store.insert("workspace_documents", json!({"id":"mem-a","project_id":project,"world_id":world,"title":"A","document_type":"scene","content":"amber lighthouse"})).unwrap();
    let (_, first) = request(
        &state,
        "POST",
        "/api/memory/backfill",
        json!({"project_id":project,"background":false}),
    )
    .await;
    assert_eq!(first["indexed"], 1);
    let (_, hit) = request(
        &state,
        "POST",
        "/api/memory/query",
        json!({"query":"amber","project_id":project,"limit":1}),
    )
    .await;
    assert_eq!(hit["results"].as_array().unwrap().len(), 1);
    state
        .store
        .update(
            "workspace_documents",
            "mem-a",
            json!({"content":"violet beacon"}),
        )
        .unwrap();
    request(
        &state,
        "POST",
        "/api/memory/backfill",
        json!({"project_id":project,"background":false}),
    )
    .await;
    let (_, stale) = request(
        &state,
        "POST",
        "/api/memory/query",
        json!({"query":"amber","project_id":project}),
    )
    .await;
    assert!(stale["results"].as_array().unwrap().is_empty());
    let (_, fresh) = request(
        &state,
        "POST",
        "/api/memory/query",
        json!({"query":"violet","project_id":project}),
    )
    .await;
    assert_eq!(fresh["results"].as_array().unwrap().len(), 1);
    state.store.delete("workspace_documents", "mem-a").unwrap();
    let (_, removed) = request(
        &state,
        "POST",
        "/api/memory/query",
        json!({"query":"violet","project_id":project}),
    )
    .await;
    assert!(removed["results"].as_array().unwrap().is_empty());
}

#[tokio::test]
async fn discovery_capture_and_review_persist_decisions() {
    let (_dir, state) = fixture();
    state
        .store
        .insert("sessions", json!({"id":"session-1","title":"Test"}))
        .unwrap();
    state.store.connection().unwrap().execute("INSERT INTO turns(id,session_id,user_prompt,story,created_at,updated_at) VALUES(?,?,?,?,?,?)", rusqlite::params!["turn-1","session-1","Mara is a patient archivist","",chrono::Utc::now().to_rfc3339(),chrono::Utc::now().to_rfc3339()]).unwrap();
    let (status, captured) = request(
        &state,
        "POST",
        "/api/memory/discoveries/capture-turn/turn-1",
        json!({"source_kind":"user_prompt","text":"Mara entered the archive"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{captured}");
    let direct = arline_runtime::foundation::memory::capture_turn(&state, "turn-1").unwrap();
    let id = direct["proposition_ids"][0].as_str().unwrap();
    let project = state.store.list("projects", &[]).unwrap()[0]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let world = state.store.list("worlds", &[]).unwrap()[0]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let (status, canon) = request(
        &state,
        "POST",
        &format!("/api/memory/discoveries/{id}/canon"),
        json!({"note":"reviewed","project_id":project,"world_id":world}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{canon}");
    assert_eq!(canon["authority_state"], "canon");
    let decisions: i64 = state
        .store
        .connection()
        .unwrap()
        .query_row(
            "SELECT COUNT(*) FROM discovery_decisions WHERE proposition_id=?",
            [id],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(decisions, 1);
}

#[tokio::test]
async fn refresh_persists_temporal_projection_and_backfill_job() {
    let (_dir, state) = fixture();
    let world = state.store.list("worlds", &[]).unwrap()[0]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let project = state.store.list("projects", &[]).unwrap()[0]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    state.store.insert("workspace_documents", json!({"id":"timeline-doc","project_id":project,"world_id":world,"title":"T","document_type":"scene","content":"timeline evidence"})).unwrap();
    state.store.insert("canon_facts", json!({"id":"timeline-fact","project_id":project,"world_id":world,"owner_type":"document","owner_id":"timeline-doc","path":"status","value_json":"{\"value\":\"active\"}","status":"canon","authority":"user_promoted","source_type":"test","source_id":"timeline-doc"})).unwrap();
    state.store.insert("timeline_events", json!({"id":"timeline-event","world_id":world,"owner_type":"document","owner_id":"timeline-doc","time_label":"1","order_key":1.0,"event_type":"state","summary":"document became active","state_patch_json":"{\"status\":\"active\"}","status":"canon","source_type":"test","source_id":"timeline-doc"})).unwrap();
    request(
        &state,
        "POST",
        "/api/memory/backfill",
        json!({"project_id":project,"background":false}),
    )
    .await;
    let (status, timeline) = request(
        &state,
        "POST",
        "/api/memory/refresh",
        json!({"world_id":world}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(timeline["timeline_state"]["world_id"], world);
    let n: i64 = state
        .store
        .connection()
        .unwrap()
        .query_row(
            "SELECT COUNT(*) FROM current_state_projection WHERE world_id=?",
            [&world],
            |r| r.get(0),
        )
        .unwrap();
    assert!(n >= 1, "timeline event should materialize current state");
    let (status, job) = request(
        &state,
        "POST",
        "/api/memory/jobs",
        json!({"project_id":project,"background":false}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(job["queued"], true);
    assert_eq!(job["job"]["status"], "done");
}

#[tokio::test]
async fn world_time_and_pov_filters_block_future_and_other_pov() {
    let (_dir, state) = fixture();
    let now = chrono::Utc::now().to_rfc3339();
    let c = state.store.connection().unwrap();
    for (id, source, time, order, text) in [
        ("past", "pov-a", "2020", 1.0, "past fact"),
        ("future", "pov-a", "2090", 9.0, "future fact"),
        ("other", "pov-b", "2020", 1.0, "other fact"),
    ] {
        c.execute("INSERT INTO memory_chunks(id,source_type,source_id,text,world_time_json,story_order,semantic_class,checksum,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", rusqlite::params![id,"external_note",source,text,format!("\"{}\"",time),order,if id=="other"{"private"}else{"evidence"},id,now,now]).unwrap();
    }
    let (_, past) = request(
        &state,
        "POST",
        "/api/memory/query",
        json!({"query":"fact","story_order":5.0,"pov_variant_id":"pov-a"}),
    )
    .await;
    let ids: Vec<_> = past["results"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|x| x["id"].as_str())
        .collect();
    assert!(ids.contains(&"past"));
    assert!(!ids.contains(&"future"));
    assert!(!ids.contains(&"other"));
}

#[tokio::test]
async fn dense_provider_enriches_and_fails_open() {
    let (_dir, state) = fixture();
    let app = axum::Router::new()
        .route(
            "/v1/embeddings",
            post(|| async { AxumJson(json!({"data":[{"embedding":[0.1,0.2]}]})) }),
        )
        .route(
            "/v1/rerank",
            post(|| async { AxumJson(json!({"results":[{"index":0,"relevance_score":0.9}]})) }),
        );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    {
        let mut cfg = state.config.write().unwrap();
        cfg.set("memory.embedding.enabled", toml::Value::Boolean(true))
            .unwrap();
        cfg.set("memory.reranker.enabled", toml::Value::Boolean(true))
            .unwrap();
        cfg.set(
            "memory.embedding.model",
            toml::Value::String("mock-embedding".into()),
        )
        .unwrap();
        cfg.set(
            "lmstudio.base_url",
            toml::Value::String(format!("http://{}", addr)),
        )
        .unwrap();
    }
    let n = chrono::Utc::now().to_rfc3339();
    state.store.connection().unwrap().execute("INSERT INTO memory_chunks(id,source_type,source_id,text,checksum,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",rusqlite::params!["semantic","external_note","semantic-turn","feline evidence","semantic",n,n]).unwrap();
    let (_, response) = request(
        &state,
        "POST",
        "/api/memory/query",
        json!({"query":"missing lexical result"}),
    )
    .await;
    assert_eq!(response["dense_embeddings"], true);
    assert_eq!(response["reranked"], true);
    assert_eq!(response["results"][0]["id"], "semantic");
    assert_eq!(response["selected"][0]["id"], "semantic");
    assert!(response["packed_text"]
        .as_str()
        .unwrap()
        .contains("feline evidence"));
}

#[tokio::test]
async fn natural_questions_retrieve_actual_structured_lanes_and_obey_budget() {
    let (_dir, state) = fixture();
    let world = state.store.list("worlds", &[]).unwrap()[0]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let now = chrono::Utc::now().to_rfc3339();
    let c = state.store.connection().unwrap();
    c.execute("INSERT INTO current_state_projection(world_id,owner_type,owner_id,state_key,value_json,source_type,authority,updated_at) VALUES(?,'entity_variant','Mara','mood','\"calm\"','manual','canon',?)",rusqlite::params![world,now]).unwrap();
    c.execute("INSERT INTO epistemic_intervals(id,world_id,character_variant_id,topic_type,topic_id,state_type,value_json,source_type,status,created_at) VALUES('ep-mara',?,'Mara','event','mystery','knows','true','manual','accepted',?)",rusqlite::params![world,now]).unwrap();
    c.execute("INSERT INTO story_threads(id,world_id,thread_type,title,description,status,created_at,updated_at) VALUES('thread-mara',?,'plot','Mara mystery','Find the sealed letter','open',?,?)",rusqlite::params![world,now,now]).unwrap();
    c.execute("INSERT INTO spatial_edges(id,world_id,subject_type,subject_id,relation,object_type,object_id,created_at,updated_at) VALUES('sp-mara',?,'entity_variant','Mara','inside','location','greenhouse',?,?)",rusqlite::params![world,now,now]).unwrap();
    let query = json!({"query":"What does Mara know about her current mood, where is she, and what mystery is unresolved?","world_id":world});
    let (status, result) = request(&state, "POST", "/api/memory/query", query.clone()).await;
    assert_eq!(status, StatusCode::OK, "{result}");
    assert_eq!(result["lane_counts"]["structured"], 2, "{result}");
    assert_eq!(result["lane_counts"]["thread"], 1);
    assert_eq!(result["lane_counts"]["spatial"], 1);
    assert!(result["packed_text"].as_str().unwrap().contains("calm"));
    assert!(result["packed_text"]
        .as_str()
        .unwrap()
        .contains("greenhouse"));
    let mut bounded = query;
    bounded["token_budget"] = json!(1);
    let (_, result) = request(&state, "POST", "/api/memory/query", bounded).await;
    assert!(result["selected"].as_array().unwrap().is_empty());
    assert!(result["excluded"].as_array().unwrap().len() >= 4);
    assert_eq!(result["abstain"], true);
}

#[tokio::test]
async fn memory_settings_disable_retrieval_and_preserve_status_contract() {
    let (_dir, state) = fixture();
    let (_, status) = request(&state, "GET", "/api/memory/status", json!({})).await;
    assert_eq!(status["schema_version"], 2);
    assert!(status["chunks"].is_number());
    assert_eq!(status["enabled"], true);
    let fixtures: Value =
        serde_json::from_str(include_str!("fixtures/python-contracts.json")).unwrap();
    let expected = fixtures
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["path"] == "/api/memory/status")
        .unwrap();
    assert_eq!(status["config"], expected["response"]["config"]);
    state
        .config
        .write()
        .unwrap()
        .set("memory.enabled", toml::Value::Boolean(false))
        .unwrap();
    let (_, disabled) = request(
        &state,
        "POST",
        "/api/memory/query",
        json!({"query":"remember"}),
    )
    .await;
    assert_eq!(disabled["abstain"], true);
    assert!(disabled["selected"].as_array().unwrap().is_empty());
    let (_, backfill) = request(
        &state,
        "POST",
        "/api/memory/backfill",
        json!({"background":false}),
    )
    .await;
    assert_eq!(backfill["disabled"], true);
}

#[tokio::test]
async fn background_backfill_chunks_long_manuscripts_and_links_sources() {
    let (_dir, state) = fixture();
    let project = state.store.list("projects", &[]).unwrap()[0]["id"].clone();
    let content = (0..45)
        .map(|i| format!("Paragraph {i}: the amber lighthouse catches a fresh tide. "))
        .collect::<String>();
    state.store.insert("workspace_documents",json!({"id":"long-doc","project_id":project,"title":"Long manuscript","content":content})).unwrap();
    let (status, queued) = request(
        &state,
        "POST",
        "/api/memory/backfill",
        json!({"project_id":project}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{queued}");
    assert_eq!(queued["queued"], true);
    let id = queued["job"]["id"].as_str().unwrap();
    let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(5);
    loop {
        let (_, job) = request(&state, "GET", &format!("/api/memory/jobs/{id}"), json!({})).await;
        if job["status"] == "done" {
            break;
        }
        assert_ne!(job["status"], "failed", "{job}");
        assert!(tokio::time::Instant::now() < deadline, "{job}");
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }
    let (_, chunks) = request(
        &state,
        "GET",
        "/api/memory/chunks?resource_type=document&resource_id=long-doc",
        json!({}),
    )
    .await;
    let items = chunks["items"].as_array().unwrap();
    assert!(items.len() > 1, "{chunks}");
    assert!(items
        .iter()
        .all(|chunk| chunk["text"].as_str().unwrap().chars().count() <= 1800));
    let (_, hit) = request(
        &state,
        "POST",
        "/api/memory/query",
        json!({"query":"amber","project_id":project}),
    )
    .await;
    assert!(
        hit["selected"].as_array().unwrap().len() <= 2,
        "per-source diversity must apply after chunking"
    );
    assert!(!hit["selected"].as_array().unwrap().is_empty());
    let (_, generations) = request(
        &state,
        "GET",
        "/api/memory/index-generations?limit=1",
        json!({}),
    )
    .await;
    assert!(generations["active"].is_object());
}

#[tokio::test]
async fn reranked_dense_evidence_reaches_packed_context_and_saved_trace() {
    use std::sync::{Arc, Mutex};
    let docs = Arc::new(Mutex::new(Vec::<Value>::new()));
    let captured = docs.clone();
    let app=axum::Router::new().route("/v1/embeddings",post(||async{AxumJson(json!({"data":[{"embedding":[0.1,0.2]}]}))}))
        .route("/v1/rerank",post(move|AxumJson(body):AxumJson<Value>|{let captured=captured.clone();async move{*captured.lock().unwrap()=body["documents"].as_array().unwrap().clone();AxumJson(json!({"results":[{"index":1,"relevance_score":0.9},{"index":0,"relevance_score":0.1}]}))}}));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    let (_dir, state) = fixture();
    {
        let mut cfg = state.config.write().unwrap();
        cfg.set("memory.embedding.enabled", toml::Value::Boolean(true))
            .unwrap();
        cfg.set("memory.reranker.enabled", toml::Value::Boolean(true))
            .unwrap();
        cfg.set(
            "lmstudio.base_url",
            toml::Value::String(format!("http://{addr}")),
        )
        .unwrap();
    }
    let project = state.store.list("projects", &[]).unwrap()[0]["id"].clone();
    for (id, text) in [
        ("dense-one", "amber first evidence"),
        ("dense-two", "amber second evidence"),
    ] {
        state
            .store
            .insert(
                "workspace_documents",
                json!({"id":id,"project_id":project,"title":id,"content":text}),
            )
            .unwrap();
        arline_runtime::foundation::memory::refresh_source(&state, "document", id).unwrap();
    }
    let (_, result) = request(
        &state,
        "POST",
        "/api/memory/query",
        json!({"query":"amber","project_id":project}),
    )
    .await;
    let sent = docs.lock().unwrap().clone();
    assert_eq!(sent.len(), 2, "{result}");
    assert_eq!(result["reranked"], true);
    assert_eq!(result["selected"][0]["text"], sent[1]);
    assert!(result["packed_text"]
        .as_str()
        .unwrap()
        .starts_with(sent[1].as_str().unwrap()));
    let cached = state
        .store
        .query(
            "SELECT result_json AS payload FROM memory_retrieval_runs WHERE id=?",
            &[&result["run_id"].as_str().unwrap()],
        )
        .unwrap();
    let saved: Value = serde_json::from_str(cached[0]["payload"].as_str().unwrap()).unwrap();
    assert_eq!(saved["selected"], result["selected"]);
    assert_eq!(saved["packed_text"], result["packed_text"]);
    let (_, bounded) = request(
        &state,
        "POST",
        "/api/memory/query",
        json!({"query":"amber","project_id":project,"token_budget":1}),
    )
    .await;
    assert!(bounded["selected"].as_array().unwrap().is_empty());
    assert_eq!(bounded["packed_tokens"], 0);
    task.abort();
    state
        .config
        .write()
        .unwrap()
        .set(
            "lmstudio.base_url",
            toml::Value::String("http://127.0.0.1:1".into()),
        )
        .unwrap();
    let (_, fallback) = request(
        &state,
        "POST",
        "/api/memory/query",
        json!({"query":"amber","project_id":project}),
    )
    .await;
    assert_eq!(fallback["dense_embeddings"], false);
    assert_eq!(fallback["selected"].as_array().unwrap().len(), 2);
}

#[tokio::test]
async fn copied_python_history_db_opens_with_native_memory_schema() {
    let dir = tempfile::tempdir().unwrap();
    let copy = dir.path().join("arline_history.db");
    let source =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../data/arline_history.db");
    std::fs::copy(source, &copy).unwrap();
    let cfg_path = dir.path().join("config.toml");
    let mut cfg = RuntimeConfig::create_default(&cfg_path, dir.path()).unwrap();
    cfg.set(
        "workspace.database_path",
        toml::Value::String(copy.to_string_lossy().into_owned()),
    )
    .unwrap();
    let state = AppState::open(cfg).unwrap();
    let status=state.store.query("SELECT generation_id,provider,embedding_dimension FROM memory_index_generations LIMIT 1",&[]).unwrap();
    assert!(status.is_empty() || status[0].get("generation_id").is_some());
    let chunks = state
        .store
        .query("SELECT COUNT(*) AS count FROM memory_chunks", &[])
        .unwrap();
    assert!(chunks[0]["count"].as_i64().unwrap() >= 24);
    let (status, body) = request(&state, "GET", "/api/memory/status", json!({})).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let (status, _) = request(&state, "GET", "/api/memory/index-generations", json!({})).await;
    assert_eq!(status, StatusCode::OK);
    let (status, backfill) = request(
        &state,
        "POST",
        "/api/memory/backfill",
        json!({"background":false}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert!(backfill.get("indexed").is_some());
    let (status, query) =
        request(&state, "POST", "/api/memory/query", json!({"query":"the"})).await;
    assert_eq!(status, StatusCode::OK);
    let run = query["run_id"].as_str().unwrap();
    let (status, _) = request(
        &state,
        "GET",
        &format!("/api/memory/retrieval/{run}"),
        json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let (status, _) = request(&state, "GET", "/api/memory/discoveries", json!({})).await;
    assert_eq!(status, StatusCode::OK);
    let (status, _) = request(
        &state,
        "POST",
        "/api/memory/discoveries/capture-turn/legacy-turn",
        json!({"text":"legacy captured fact"}),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let world = state
        .store
        .list("worlds", &[])
        .unwrap()
        .first()
        .and_then(|x| x["id"].as_str())
        .unwrap_or("")
        .to_owned();
    if !world.is_empty() {
        let (status, _) = request(
            &state,
            "POST",
            "/api/memory/refresh",
            json!({"world_id":world}),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
    }
}
