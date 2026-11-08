-- Additive R2 schema. Historical vectors intentionally have no chunk FK:
-- deleting/replacing a source removes eligibility, not rollback history.
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS semantic_index_meta(version INTEGER PRIMARY KEY CHECK(version=1),created_at TEXT NOT NULL);
INSERT OR IGNORE INTO semantic_index_meta VALUES(1,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
CREATE TABLE IF NOT EXISTS semantic_model_generations(
 model_fingerprint TEXT PRIMARY KEY,model_id TEXT NOT NULL,backend TEXT NOT NULL,
 dimensions INTEGER NOT NULL CHECK(dimensions=384),identity_json TEXT NOT NULL CHECK(json_valid(identity_json)),
 encoding_version INTEGER NOT NULL CHECK(encoding_version=1),created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS semantic_vectors(
 chunk_id TEXT NOT NULL,model_fingerprint TEXT NOT NULL REFERENCES semantic_model_generations(model_fingerprint),
 source_revision TEXT NOT NULL,content_checksum TEXT NOT NULL,chunker_version INTEGER NOT NULL,
 dimensions INTEGER NOT NULL CHECK(dimensions=384),vector_blob BLOB NOT NULL,
 indexed_at TEXT NOT NULL,PRIMARY KEY(chunk_id,model_fingerprint),
 CHECK(typeof(vector_blob)='blob' AND length(vector_blob)=dimensions*4),
 CHECK(semantic_f32_valid_v1(vector_blob,dimensions)=1)
);
CREATE INDEX IF NOT EXISTS semantic_vectors_generation ON semantic_vectors(model_fingerprint,chunk_id);
CREATE TABLE IF NOT EXISTS semantic_pending_sources(
 source_type TEXT NOT NULL,source_id TEXT NOT NULL,dirty_version INTEGER NOT NULL DEFAULT 1,
 updated_at TEXT NOT NULL,PRIMARY KEY(source_type,source_id)
);
CREATE TABLE IF NOT EXISTS semantic_index_jobs(
 id TEXT PRIMARY KEY,model_fingerprint TEXT NOT NULL REFERENCES semantic_model_generations(model_fingerprint),
 scope_json TEXT NOT NULL CHECK(json_valid(scope_json)),scope_key TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN('queued','running','completed','partial','failed','interrupted','cancelled')),
 cursor TEXT NOT NULL DEFAULT '',indexed INTEGER NOT NULL DEFAULT 0,skipped INTEGER NOT NULL DEFAULT 0,
 failed INTEGER NOT NULL DEFAULT 0,discarded INTEGER NOT NULL DEFAULT 0,cancel_requested INTEGER NOT NULL DEFAULT 0,
 last_error TEXT NOT NULL DEFAULT '',owner TEXT,lease_until INTEGER NOT NULL DEFAULT 0,
 batches INTEGER NOT NULL DEFAULT 0,inference_ms REAL NOT NULL DEFAULT 0,validation_ms REAL NOT NULL DEFAULT 0,
 commit_ms REAL NOT NULL DEFAULT 0,duration_ms REAL NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS semantic_one_active_scope ON semantic_index_jobs(model_fingerprint,scope_key) WHERE status IN('queued','running');
CREATE TABLE IF NOT EXISTS semantic_index_items(
 chunk_id TEXT NOT NULL,model_fingerprint TEXT NOT NULL REFERENCES semantic_model_generations(model_fingerprint),
 state TEXT NOT NULL CHECK(state IN('pending','current','failed','stale')),
 source_revision TEXT,content_checksum TEXT,chunker_version INTEGER,last_error TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL,
 PRIMARY KEY(chunk_id,model_fingerprint)
);
CREATE TRIGGER IF NOT EXISTS semantic_chunk_insert AFTER INSERT ON memory_chunks BEGIN
 INSERT INTO semantic_pending_sources VALUES(NEW.source_type,NEW.source_id,1,strftime('%Y-%m-%dT%H:%M:%fZ','now'))
 ON CONFLICT(source_type,source_id) DO UPDATE SET dirty_version=dirty_version+1,updated_at=excluded.updated_at;
END;
CREATE TRIGGER IF NOT EXISTS semantic_chunk_update AFTER UPDATE OF source_revision,checksum,text,chunker_version,semantic_status,source_type,source_id,project_id,world_id,branch_id,session_id,authority,trust_level ON memory_chunks BEGIN
 INSERT INTO semantic_pending_sources VALUES(NEW.source_type,NEW.source_id,1,strftime('%Y-%m-%dT%H:%M:%fZ','now'))
 ON CONFLICT(source_type,source_id) DO UPDATE SET dirty_version=dirty_version+1,updated_at=excluded.updated_at;
END;
CREATE TRIGGER IF NOT EXISTS semantic_chunk_delete AFTER DELETE ON memory_chunks BEGIN
 INSERT INTO semantic_pending_sources VALUES(OLD.source_type,OLD.source_id,1,strftime('%Y-%m-%dT%H:%M:%fZ','now'))
 ON CONFLICT(source_type,source_id) DO UPDATE SET dirty_version=dirty_version+1,updated_at=excluded.updated_at;
END;
INSERT OR IGNORE INTO semantic_pending_sources SELECT source_type,source_id,1,strftime('%Y-%m-%dT%H:%M:%fZ','now') FROM memory_chunks GROUP BY source_type,source_id;
COMMIT;
