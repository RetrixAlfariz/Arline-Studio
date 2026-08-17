from pathlib import Path

path = Path("tools/complete_v120_foundation.py")
text = path.read_text(encoding="utf-8")
start = text.index('        cfg.write_text(\n', text.index('class V120MemoryFoundationTests'))
end = text.index('        return TestClient(create_app(cfg))', start)
replacement = r'''        config_text = f"""[lmstudio]
base_url = "http://127.0.0.1:1"
model = ""
api_key = ""
timeout_seconds = 0.2
auto_load = false

[history]
database_path = "{db.as_posix()}"
dataset_root = "{(root / 'datasets').as_posix()}"
recent_limit = 100
continuity_turns = 2
continuity_chars = 12000
smart_hybrid_continuity = true

[workspace]
database_path = "{db.as_posix()}"
default_project_id = ""
context_enabled = true
mention_limit = 20
pinned_context_limit = 24
autosave_drafts = true
language_mode = "follow_prompt"

[writer]
input_mode = "smart_hybrid"
system_prompt_file = "writer_system.txt"
story_filename = "story.txt"
save_request_packet = false
post_validate = false

[reasoning_runtime]
enforce_model_capabilities = false
guard_prompt_file = "reasoning_guard.txt"

[memory]
enabled = true
fts_enabled = true
dense_enabled = false
automatic_context = true
default_lens = "scene"
chunk_chars = 700
chunk_overlap_chars = 40
max_candidates = 40
final_k = 8
max_per_source = 3
rrf_k = 60
trace_enabled = true

[memory.embedding]
enabled = false
provider = "lmstudio"
model = "intfloat/multilingual-e5-base"
dimension = 768
query_prefix = "query: "
passage_prefix = "passage: "
"""
        cfg.write_text(config_text, encoding="utf-8")
'''
path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
