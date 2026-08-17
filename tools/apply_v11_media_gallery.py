from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Schema: resource media is cross-cutting foundation metadata. Both stores use
# the shared workspace schema version so the existing pre-migration backup gate
# protects v6 -> v7 before the additive table is created.
# ---------------------------------------------------------------------------
store_path = "src/workspace/store.py"
store = read(store_path)
store = replace_once(store, 'WORKSPACE_SCHEMA_VERSION = 6', 'WORKSPACE_SCHEMA_VERSION = 7', 'workspace schema v7')
write(store_path, store)

foundation_path = "src/workspace/foundation.py"
foundation = read(foundation_path)
foundation = replace_once(foundation, '    SCHEMA_VERSION = 6', '    SCHEMA_VERSION = 7', 'foundation schema v7')

media_table = '''

                CREATE TABLE IF NOT EXISTS resource_media (
                    id TEXT PRIMARY KEY,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    media_type TEXT NOT NULL DEFAULT 'image',
                    kind TEXT NOT NULL DEFAULT 'reference',
                    mime_type TEXT NOT NULL,
                    original_name TEXT NOT NULL DEFAULT '',
                    storage_path TEXT NOT NULL,
                    caption TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    description_source TEXT NOT NULL DEFAULT 'manual',
                    is_cover INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_resource_media_owner
                    ON resource_media(resource_type, resource_id, sort_order, created_at);
'''
foundation = replace_once(
    foundation,
    '''                CREATE INDEX IF NOT EXISTS idx_alias_lookup
                    ON resource_aliases(normalized_alias, resource_type);
''',
    '''                CREATE INDEX IF NOT EXISTS idx_alias_lookup
                    ON resource_aliases(normalized_alias, resource_type);''' + media_table + '\n',
    'resource media table',
)

media_methods = r'''
    # ------------------------------------------------------------------
    # Media / Gallery foundation
    # ------------------------------------------------------------------

    @staticmethod
    def _media_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["is_cover"] = bool(item.get("is_cover"))
        return item

    def create_media(
        self,
        resource_type: str,
        resource_id: str,
        *,
        storage_path: str,
        mime_type: str,
        original_name: str = "",
        media_type: str = "image",
        kind: str = "reference",
        caption: str = "",
        description: str = "",
        description_source: str = "manual",
        is_cover: bool = False,
        sort_order: int = 0,
    ) -> dict[str, Any]:
        media_id = make_id("MEDIA")
        now = utc_now()
        if not resource_type.strip() or not resource_id.strip():
            raise ValueError("Media must belong to a resource")
        with self._lock, self._connection() as con:
            if is_cover:
                con.execute(
                    "UPDATE resource_media SET is_cover=0,updated_at=? WHERE resource_type=? AND resource_id=?",
                    (now, resource_type, resource_id),
                )
            con.execute(
                "INSERT INTO resource_media(id,resource_type,resource_id,media_type,kind,mime_type,original_name,storage_path,caption,description,description_source,is_cover,sort_order,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    media_id, resource_type, resource_id, media_type, kind, mime_type,
                    original_name, storage_path, caption.strip(), description.strip(),
                    description_source.strip() or "manual", int(bool(is_cover)), int(sort_order), now, now,
                ),
            )
        return self.get_media(media_id)

    def get_media(self, media_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM resource_media WHERE id=?", (media_id,)).fetchone()
        if row is None:
            raise KeyError(media_id)
        return self._media_row(row)

    def list_media(
        self,
        *,
        resource_type: str | None = None,
        resource_id: str | None = None,
        cover_only: bool = False,
    ) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if resource_type:
            where.append("resource_type=?"); params.append(resource_type)
        if resource_id:
            where.append("resource_id=?"); params.append(resource_id)
        if cover_only:
            where.append("is_cover=1")
        with self._connection() as con:
            rows = con.execute(
                f"SELECT * FROM resource_media WHERE {' AND '.join(where)} ORDER BY is_cover DESC,sort_order ASC,created_at ASC",
                params,
            ).fetchall()
        return [self._media_row(row) for row in rows]

    def update_media(self, media_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {"kind", "caption", "description", "description_source", "is_cover", "sort_order"}
        current = self.get_media(media_id)
        now = utc_now()
        with self._lock, self._connection() as con:
            if changes.get("is_cover") is True:
                con.execute(
                    "UPDATE resource_media SET is_cover=0,updated_at=? WHERE resource_type=? AND resource_id=?",
                    (now, current["resource_type"], current["resource_id"]),
                )
            fields: list[str] = []
            params: list[Any] = []
            for key, value in changes.items():
                if key not in allowed or value is None:
                    continue
                if key == "is_cover":
                    value = int(bool(value))
                elif key == "sort_order":
                    value = int(value)
                fields.append(f"{key}=?"); params.append(value)
            if fields:
                fields.append("updated_at=?"); params.extend([now, media_id])
                cur = con.execute(f"UPDATE resource_media SET {', '.join(fields)} WHERE id=?", params)
                if not cur.rowcount:
                    raise KeyError(media_id)
        return self.get_media(media_id)

    def delete_media(self, media_id: str) -> None:
        item = self.get_media(media_id)
        with self._lock, self._connection() as con:
            con.execute("DELETE FROM resource_media WHERE id=?", (media_id,))
        try:
            Path(item["storage_path"]).unlink(missing_ok=True)
        except OSError:
            pass

'''
foundation = replace_once(
    foundation,
    '    # ------------------------------------------------------------------\n    # Run profiles\n    # ------------------------------------------------------------------\n',
    media_methods + '    # ------------------------------------------------------------------\n    # Run profiles\n    # ------------------------------------------------------------------\n',
    'media methods before run profiles',
)

# Permanent deletes clean media bytes and metadata.
foundation = replace_once(
    foundation,
    '''        with self._lock, self._connection() as con:
            con.execute("DELETE FROM resource_lifecycle WHERE resource_type=? AND resource_id=?", (resource_type, resource_id))
            con.execute("DELETE FROM resource_aliases WHERE resource_type=? AND resource_id=?", (resource_type, resource_id))''',
    '''        with self._lock, self._connection() as con:
            media_rows = con.execute("SELECT storage_path FROM resource_media WHERE resource_type=? AND resource_id=?", (resource_type, resource_id)).fetchall()
            for media in media_rows:
                try:
                    Path(media["storage_path"]).unlink(missing_ok=True)
                except OSError:
                    pass
            con.execute("DELETE FROM resource_media WHERE resource_type=? AND resource_id=?", (resource_type, resource_id))
            con.execute("DELETE FROM resource_lifecycle WHERE resource_type=? AND resource_id=?", (resource_type, resource_id))
            con.execute("DELETE FROM resource_aliases WHERE resource_type=? AND resource_id=?", (resource_type, resource_id))''',
    'forget resource media cleanup',
)

# Identity merge moves media to the surviving family. If the target already has
# a cover, its cover wins rather than silently creating two covers.
foundation = replace_once(
    foundation,
    '''            con.execute("DELETE FROM resource_aliases WHERE resource_type=? AND resource_id=?", (resource_type, source_id))
            # collections''',
    '''            con.execute("DELETE FROM resource_aliases WHERE resource_type=? AND resource_id=?", (resource_type, source_id))
            target_cover = con.execute("SELECT id FROM resource_media WHERE resource_type=? AND resource_id=? AND is_cover=1 LIMIT 1", (resource_type, target_id)).fetchone()
            if target_cover:
                con.execute("UPDATE resource_media SET is_cover=0,updated_at=? WHERE resource_type=? AND resource_id=? AND is_cover=1", (utc_now(), resource_type, source_id))
            con.execute("UPDATE resource_media SET resource_id=?,updated_at=? WHERE resource_type=? AND resource_id=?", (target_id, utc_now(), resource_type, source_id))
            # collections''',
    'merge resource media refs',
)
write(foundation_path, foundation)


# ---------------------------------------------------------------------------
# Inference: expose LM Studio's native vision capability and allow its native
# /api/v1/chat input array to contain image data URLs.
# ---------------------------------------------------------------------------
provider_path = "src/inference/provider.py"
provider = read(provider_path)
provider = replace_once(provider, '    streaming: bool = False\n', '    streaming: bool = False\n    vision: bool = False\n', 'provider vision capability')
write(provider_path, provider)

lm_path = "src/inference/lmstudio.py"
lm = read(lm_path)
lm = replace_once(
    lm,
    '''    def resolve_reasoning_option(self, key: str, requested: str) -> str | None:
''',
    '''    def vision_supported(self, key: str) -> bool:
        info = self.model_info(key) or {}
        return bool((info.get("capabilities") or {}).get("vision"))

    def resolve_reasoning_option(self, key: str, requested: str) -> str | None:
''',
    'vision_supported method',
)
lm = replace_once(
    lm,
    '                    "reasoning": (model.get("capabilities") or {}).get("reasoning"),\n',
    '                    "reasoning": (model.get("capabilities") or {}).get("reasoning"),\n                    "vision": bool((model.get("capabilities") or {}).get("vision")),\n',
    'check server vision',
)
lm = replace_once(
    lm,
    '''        input_text: str,
        system_prompt: str,
''',
    '''        input_text: str,
        system_prompt: str,
        images: list[str] | None = None,
''',
    'chat images signature',
)
lm = replace_once(
    lm,
    '            "input": input_text,\n',
    '''            "input": input_text if not images else [
                {"type": "message", "content": input_text},
                *[{"type": "image", "data_url": image} for image in images],
            ],
''',
    'chat multimodal input payload',
)
write(lm_path, lm)

manager_path = "src/inference/model_manager.py"
manager = read(manager_path)
manager = replace_once(
    manager,
    '"reasoning":((info or {}).get("capabilities") or {}).get("reasoning"),"format":(info or {}).get("format")}',
    '"reasoning":((info or {}).get("capabilities") or {}).get("reasoning"),"vision":bool(((info or {}).get("capabilities") or {}).get("vision")),"format":(info or {}).get("format")}',
    'manager status vision',
)
write(manager_path, manager)


# ---------------------------------------------------------------------------
# Web API: local media storage, cover metadata, and opt-in vision description.
# Vision output is returned as a proposal; it is never promoted to canon.
# ---------------------------------------------------------------------------
app_path = "src/interface/web/app.py"
app = read(app_path)
app = replace_once(app, 'import asyncio\n', 'import asyncio\nimport base64\nimport binascii\n', 'app media imports')
app = replace_once(app, 'from typing import Any\n', 'from typing import Any\nfrom uuid import uuid4\n', 'app uuid import')
app = replace_once(app, 'from src.inference import LMStudioError, LMStudioModelManager\n', 'from src.inference import LMStudioClient, LMStudioError, LMStudioModelManager\n', 'app LMStudioClient import')

app = replace_once(
    app,
    '''MODE_LABELS = {
    "smart_hybrid": "Smart Hybrid",
    "wcf": "WCF only",
    "raw": "Raw only",
    "wcf_raw": "WCF + Raw",
    "aif_core": "AIF-Core",
}
''',
    '''MODE_LABELS = {
    "smart_hybrid": "Smart Hybrid",
    "wcf": "WCF only",
    "raw": "Raw only",
    "wcf_raw": "WCF + Raw",
    "aif_core": "AIF-Core",
}

MEDIA_MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MEDIA_RESOURCE_TYPES = {"entity_family", "entity_variant", "world", "document"}
MAX_MEDIA_BYTES = 20 * 1024 * 1024
''',
    'media constants',
)

media_payloads = '''

class MediaCreatePayload(BaseModel):
    resource_type: str
    resource_id: str
    filename: str = "image"
    data_url: str
    kind: str = "reference"
    caption: str = ""
    is_cover: bool = False
    sort_order: int = 0


class MediaPatchPayload(BaseModel):
    kind: str | None = None
    caption: str | None = None
    description: str | None = None
    description_source: str | None = None
    is_cover: bool | None = None
    sort_order: int | None = None


class MediaDescribePayload(BaseModel):
    model: str = ""
    server_url: str | None = None
    api_key: str | None = None
    prompt: str = ""
'''
app = replace_once(app, '\nclass PreferencePayload(BaseModel):', media_payloads + '\n\nclass PreferencePayload(BaseModel):', 'media request models')

app = replace_once(
    app,
    '    foundation = FoundationStore(initial_cfg.workspace.database_path)\n',
    '    foundation = FoundationStore(initial_cfg.workspace.database_path)\n    media_root = workspace_path.parent / "media"\n    media_root.mkdir(parents=True, exist_ok=True)\n',
    'media root init',
)

# Both GET /api/models and POST /api/models/query expose the same capability.
cap_anchor = '                        "sampling_controls": ["temperature", "top_p", "top_k", "min_p", "repeat_penalty"],\n'
if app.count(cap_anchor) < 2:
    raise SystemExit('expected both model capability blocks')
app = app.replace(
    cap_anchor,
    '                        "vision": bool((item.get("capabilities") or {}).get("vision")),\n' + cap_anchor,
)

media_routes = r'''
    def _public_media(item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        result.pop("storage_path", None)
        result["content_url"] = f"/api/media/{item['id']}/content"
        return result

    def _decode_media_data_url(data_url: str) -> tuple[str, bytes]:
        match = re.fullmatch(r"data:([^;,]+);base64,(.+)", data_url.strip(), flags=re.DOTALL)
        if not match:
            raise ValueError("Expected a base64 image data URL")
        mime = match.group(1).lower()
        if mime not in MEDIA_MIME_EXTENSIONS:
            raise ValueError("Supported images: PNG, JPEG, WebP, and GIF")
        encoded = re.sub(r"\s+", "", match.group(2))
        if len(encoded) > MAX_MEDIA_BYTES * 2:
            raise ValueError("Image is too large")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Invalid base64 image payload") from exc
        if not data or len(data) > MAX_MEDIA_BYTES:
            raise ValueError(f"Image must be between 1 byte and {MAX_MEDIA_BYTES // (1024 * 1024)} MiB")
        return mime, data

    @app.get("/api/media")
    def list_media(
        resource_type: str | None = Query(None),
        resource_id: str | None = Query(None),
        cover_only: bool = Query(False),
    ):
        return {"items": [_public_media(item) for item in foundation.list_media(
            resource_type=resource_type, resource_id=resource_id, cover_only=cover_only
        )]}

    @app.post("/api/media")
    def create_media(payload: MediaCreatePayload):
        if payload.resource_type not in MEDIA_RESOURCE_TYPES:
            raise HTTPException(400, "Unsupported media resource type")
        try:
            _resource_payload(payload.resource_type, payload.resource_id)
            mime, data = _decode_media_data_url(payload.data_url)
        except KeyError as exc:
            raise HTTPException(404, "Media owner not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        suffix = MEDIA_MIME_EXTENSIONS[mime]
        storage_path = (media_root / f"{uuid4().hex}{suffix}").resolve()
        storage_path.write_bytes(data)
        try:
            item = foundation.create_media(
                payload.resource_type, payload.resource_id,
                storage_path=str(storage_path), mime_type=mime,
                original_name=Path(payload.filename).name[:240], kind=payload.kind,
                caption=payload.caption, is_cover=payload.is_cover,
                sort_order=payload.sort_order,
            )
        except Exception:
            storage_path.unlink(missing_ok=True)
            raise
        foundation.log_activity(None, "media_added", payload.resource_type, payload.resource_id, label=payload.filename)
        return _public_media(item)

    @app.get("/api/media/{media_id}/content")
    def media_content(media_id: str):
        try:
            item = foundation.get_media(media_id)
        except KeyError as exc:
            raise HTTPException(404, "Media not found") from exc
        path = Path(item["storage_path"])
        if not path.exists() or not path.is_file():
            raise HTTPException(404, "Media file is missing")
        return FileResponse(path, media_type=item["mime_type"], filename=item.get("original_name") or path.name)

    @app.patch("/api/media/{media_id}")
    def patch_media(media_id: str, payload: MediaPatchPayload):
        try:
            item = foundation.update_media(media_id, **payload.model_dump(exclude_none=True))
        except KeyError as exc:
            raise HTTPException(404, "Media not found") from exc
        return _public_media(item)

    @app.delete("/api/media/{media_id}")
    def delete_media(media_id: str):
        try:
            item = foundation.get_media(media_id)
            foundation.delete_media(media_id)
        except KeyError as exc:
            raise HTTPException(404, "Media not found") from exc
        foundation.log_activity(None, "media_deleted", item["resource_type"], item["resource_id"], label=item.get("original_name") or media_id)
        return {"deleted": True, "id": media_id}

    @app.post("/api/media/{media_id}/describe")
    def describe_media(media_id: str, payload: MediaDescribePayload):
        try:
            item = foundation.get_media(media_id)
        except KeyError as exc:
            raise HTTPException(404, "Media not found") from exc
        path = Path(item["storage_path"])
        if not path.exists() or not path.is_file():
            raise HTTPException(404, "Media file is missing")
        cfg = RuntimeConfig.load(config_path)
        if payload.server_url:
            cfg.lmstudio.base_url = RuntimeConfig.normalize_server_url(payload.server_url)
        if payload.api_key is not None:
            cfg.lmstudio.api_key = payload.api_key
        if payload.model:
            cfg.lmstudio.model = payload.model
        if not cfg.lmstudio.model:
            raise HTTPException(400, "Select a model first")
        client = LMStudioClient(
            base_url=cfg.lmstudio.base_url,
            api_key=cfg.lmstudio.api_key,
            timeout_seconds=cfg.lmstudio.timeout_seconds,
        )
        try:
            if not client.vision_supported(cfg.lmstudio.model):
                raise HTTPException(400, "The selected model does not report vision support in LM Studio")
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            data_url = f"data:{item['mime_type']};base64,{encoded}"
            reasoning_cfg = client.reasoning_config(cfg.lmstudio.model)
            reasoning = "off" if "off" in reasoning_cfg.get("allowed_options", []) else None
            prompt = payload.prompt.strip() or (
                "Describe this image precisely for a fiction/worldbuilding reference library. "
                "Only describe visually observable details. Separate uncertain impressions from facts. "
                "Do not invent identity, backstory, measurements, relationships, or hidden anatomy."
            )
            result = client.chat(
                model=cfg.lmstudio.model,
                input_text=prompt,
                system_prompt=(
                    "You are Arline's visual reference describer. Return a concise, concrete visual description. "
                    "This output is a reviewable media-description proposal, not canon."
                ),
                images=[data_url],
                temperature=0.2,
                top_p=0.9,
                top_k=20,
                min_p=0.0,
                max_tokens=1200,
                repeat_penalty=1.02,
                reasoning=reasoning,
                context_length=min(int(cfg.model_load.context_length), 16384),
            )
        except LMStudioError as exc:
            raise HTTPException(503, str(exc)) from exc
        return {
            "media_id": media_id,
            "model": cfg.lmstudio.model,
            "description": result.text,
            "stats": result.stats,
            "proposal": True,
            "saved": False,
            "canon_changed": False,
        }

'''
app = replace_once(app, '\n    return app\n\n\ndef launch_ui', '\n' + media_routes + '    return app\n\n\ndef launch_ui', 'media routes before return app')
write(app_path, app)


# ---------------------------------------------------------------------------
# HTML / CSS: Gallery is a Library presentation mode, not a new navigation
# domain. Media management lives on the resource sheet.
# ---------------------------------------------------------------------------
html_path = "src/interface/web/static/index.html"
html = read(html_path)
html = replace_once(
    html,
    '<label class="search-field"><span>⌕</span><input id="worldSearch" placeholder="Search the Library…" /></label>',
    '<label class="search-field"><span>⌕</span><input id="worldSearch" placeholder="Search the Library…" /></label><div id="libraryViewControls" class="library-view-controls" aria-label="Library view"><button data-library-view="list" title="List view">☷</button><button class="active" data-library-view="grid" title="Grid view">▦</button><button data-library-view="gallery" title="Gallery view">▧</button></div>',
    'library view controls',
)
html = html.replace('arline.css?v=1.1.2-polish', 'arline.css?v=1.1.3-media')
html = html.replace('stream.js?v=1.1.2-polish', 'stream.js?v=1.1.3-media')
html = html.replace('arline.js?v=1.1.2-polish', 'arline.js?v=1.1.3-media')
write(html_path, html)

css_path = "src/interface/web/static/arline.css"
css = read(css_path)
css += r'''

/* v1.1 final media/gallery foundation ------------------------------------ */
.library-view-controls{display:flex;gap:2px;border:1px solid var(--border);background:#252825;border-radius:9px;padding:2px;flex:none}.library-view-controls button{width:28px;height:27px;border:0;background:transparent;color:var(--muted);border-radius:6px;font-size:12px}.library-view-controls button:hover{background:rgba(255,255,255,.05);color:#fff}.library-view-controls button.active{background:var(--accent-soft);color:#bce5d9}
.world-card-cover{display:none;overflow:hidden;background:#222522;border-radius:10px;position:relative}.world-card-cover img{width:100%;height:100%;object-fit:cover;display:block}.world-card-cover.placeholder{align-items:center;justify-content:center;color:#738078;font-size:30px;background:linear-gradient(145deg,#303530,#242724)}
.world-grid.view-gallery{grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:11px}.world-grid.view-gallery .world-card{min-height:0;padding:7px}.world-grid.view-gallery .world-card-cover{display:flex;aspect-ratio:4/5;margin-bottom:8px}.world-grid.view-gallery .world-card-head{position:absolute;top:13px;left:13px;right:13px;z-index:2;pointer-events:none}.world-grid.view-gallery .world-card-icon{display:none}.world-grid.view-gallery .canon-badge{margin-left:auto;background:rgba(24,27,25,.8);backdrop-filter:blur(7px)}.world-grid.view-gallery .world-card h3{font-size:11px;margin:6px 4px 2px}.world-grid.view-gallery .world-card p{display:none}.world-grid.view-gallery .world-card-meta{margin:3px 4px 4px}.world-grid.view-gallery .world-select-toggle{top:13px;right:13px;z-index:4}
.world-grid.view-list{display:flex;flex-direction:column;gap:5px}.world-grid.view-list .world-card{min-height:0;display:grid;grid-template-columns:38px minmax(150px,.8fr) minmax(180px,1.6fr) auto;align-items:center;gap:10px;padding:8px 10px}.world-grid.view-list .world-card-head{display:block}.world-grid.view-list .world-card-icon{width:30px;height:30px}.world-grid.view-list .world-card .canon-badge{display:none}.world-grid.view-list .world-card h3{margin:0;font-size:10.5px}.world-grid.view-list .world-card p{margin:0;-webkit-line-clamp:1}.world-grid.view-list .world-card-meta{margin:0;justify-content:flex-end}.world-grid.view-list .world-select-toggle{position:static;grid-column:5;grid-row:1}

.entity-media-section .sheet-section-head{gap:10px}.entity-media-actions{display:flex;gap:5px;flex-wrap:wrap}.entity-media-note{color:var(--muted);font-size:8.5px;margin:0 0 9px}.entity-media-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:7px}.entity-media-card{border:1px solid var(--border);background:#242724;border-radius:11px;overflow:hidden;min-width:0}.entity-media-thumb{aspect-ratio:4/5;background:#1d201e;position:relative}.entity-media-thumb img{width:100%;height:100%;object-fit:cover;display:block}.entity-media-badge{position:absolute;top:6px;left:6px;border:1px solid rgba(255,255,255,.12);background:rgba(20,22,21,.78);backdrop-filter:blur(7px);border-radius:999px;padding:3px 6px;font-size:7px;color:#d6dcd8}.entity-media-badge.cover{color:#a9e0cf;border-color:rgba(78,193,156,.25)}.entity-media-body{padding:7px}.entity-media-body b{display:block;font-size:8.8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.entity-media-body p{color:var(--muted);font-size:7.8px;line-height:1.4;margin:4px 0;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}.entity-media-body small{display:block;color:var(--muted-2);font-size:7px;margin-bottom:5px}.entity-media-card-actions{display:flex;gap:3px;flex-wrap:wrap}.entity-media-card-actions button{font-size:7.5px;padding:4px 5px}.vision-unavailable{opacity:.45;cursor:not-allowed!important}.gallery-empty-media{border:1px dashed var(--border);border-radius:10px;padding:15px;color:var(--muted-2);font-size:8.5px;text-align:center;grid-column:1/-1}
@media(max-width:680px){.world-filter-row{flex-wrap:wrap}.library-view-controls{order:3}.world-grid.view-list .world-card{grid-template-columns:34px minmax(0,1fr) auto}.world-grid.view-list .world-card p,.world-grid.view-list .world-card-meta{display:none}.entity-media-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
'''
write(css_path, css)


# ---------------------------------------------------------------------------
# Frontend behavior: media covers feed Gallery, descriptions are explicitly
# reviewed, and Saved Views remember their Library layout.
# ---------------------------------------------------------------------------
js_path = "src/interface/web/static/arline.js"
js = read(js_path)
js = replace_once(
    js,
    '  worldSelection: new Set(),\n  conversationRenderLimit: 80,\n',
    '  worldSelection: new Set(),\n  mediaCovers: [],\n  libraryViewMode: "grid",\n  conversationRenderLimit: 80,\n',
    'frontend media state',
)

# Remove the accidental duplicate Home Review binding from the previous polish.
dup = '''  $$(\'[data-home-review]\',byId("homeView")).forEach((b)=>b.addEventListener("click",()=>{openInspector("review");loadFeedbackLab();}));
  $$(\'[data-home-review]\',byId("homeView")).forEach((b)=>b.addEventListener("click",()=>{openInspector("review");loadFeedbackLab();}));'''
if dup in js:
    js = js.replace(dup, dup.split('\n')[0], 1)

js = replace_once(
    js,
    '  state.layoutPrefs = prefs;\n  document.body.classList.toggle("sidebar-collapsed", Boolean(prefs.sidebarCollapsed));',
    '  state.layoutPrefs = prefs;\n  state.libraryViewMode = ["list","grid","gallery"].includes(prefs.libraryViewMode) ? prefs.libraryViewMode : "grid";\n  document.body.classList.toggle("sidebar-collapsed", Boolean(prefs.sidebarCollapsed));',
    'restore library view preference',
)

# loadProjectData: cover-only media is lightweight and enough to render cards.
js = replace_once(
    js,
    '  const [tree, bible, facts, snapshots, staged, continuity] = await Promise.all([',
    '  const [tree, bible, facts, snapshots, staged, continuity, media] = await Promise.all([',
    'load project media destructure',
)
js = replace_once(
    js,
    '    api(`/api/projects/${state.activeProject.id}/continuity?${qTree}`),\n  ]);',
    '    api(`/api/projects/${state.activeProject.id}/continuity?${qTree}`),\n    api("/api/media?cover_only=true"),\n  ]);',
    'load project media request',
)
js = replace_once(
    js,
    '  state.continuity = continuity || null;\n',
    '  state.continuity = continuity || null;\n  state.mediaCovers = media.items || [];\n',
    'assign media covers',
)

view_helpers = r'''
function setLibraryViewMode(mode, { persist = true, rerender = false } = {}) {
  mode = ["list", "grid", "gallery"].includes(mode) ? mode : "grid";
  state.libraryViewMode = mode;
  const grid = byId("worldGrid");
  if (grid) {
    grid.classList.remove("view-list", "view-grid", "view-gallery");
    grid.classList.add(`view-${mode}`);
  }
  $$('[data-library-view]').forEach((button) => button.classList.toggle("active", button.dataset.libraryView === mode));
  if (persist) saveLocalPrefs({ libraryViewMode: mode });
  if (rerender && state.activeView === "world") renderWorldGrid();
}

function coverForWorldCard(item) {
  if (item.type === "entity") {
    return state.mediaCovers.find((media) => media.resource_type === "entity_variant" && media.resource_id === item.variant?.id)
      || state.mediaCovers.find((media) => media.resource_type === "entity_family" && media.resource_id === item.family?.id)
      || null;
  }
  if (item.type === "world") return state.mediaCovers.find((media) => media.resource_type === "world" && media.resource_id === item.id) || null;
  return null;
}

function galleryCoverHTML(item) {
  const media = coverForWorldCard(item);
  if (media) return `<div class="world-card-cover"><img loading="lazy" src="${escapeHTML(media.content_url)}" alt="${escapeHTML(media.caption || item.label || "Library image")}"></div>`;
  const iconType = item.type === "entity" ? item.family?.entity_type : item.type;
  return `<div class="world-card-cover placeholder"><span>${escapeHTML(ENTITY_ICONS[iconType] || "◇")}</span></div>`;
}

function selectedModelHasVision() {
  const model = state.modelMap.get(byId("modelSelect")?.value || "");
  return Boolean(model?.capabilities?.vision);
}

function fileToDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("Could not read image"));
    reader.readAsDataURL(file);
  });
}

async function chooseAndUploadMedia(resourceType, resourceId, { refresh, makeCover = false } = {}) {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/png,image/jpeg,image/webp,image/gif";
  input.multiple = true;
  input.addEventListener("change", async () => {
    const files = [...(input.files || [])];
    if (!files.length) return;
    loading(true, "Adding visual references…", `${files.length} image${files.length === 1 ? "" : "s"}`);
    try {
      let first = true;
      for (const file of files) {
        if (file.size > 20 * 1024 * 1024) throw new Error(`${file.name} is larger than 20 MiB`);
        const dataUrl = await fileToDataURL(file);
        await api("/api/media", { method: "POST", body: {
          resource_type: resourceType, resource_id: resourceId, filename: file.name,
          data_url: dataUrl, kind: "reference", caption: "",
          is_cover: Boolean(makeCover && first), sort_order: 0,
        }});
        first = false;
      }
      await loadProjectData();
      if (refresh) await refresh();
      toast(`Added ${files.length} visual reference${files.length === 1 ? "" : "s"}`);
    } catch (error) { toast(`Image upload failed: ${error.message}`, 6000); }
    finally { loading(false); }
  }, { once: true });
  input.click();
}

async function reviewVisionDescription(media, refresh) {
  if (!selectedModelHasVision()) return toast("The selected LM Studio model does not report vision support");
  loading(true, "Describing image…", "Using the selected local vision model");
  try {
    const apiKey = byId("apiKey")?.value.trim() || null;
    const result = await api(`/api/media/${encodeURIComponent(media.id)}/describe`, { method: "POST", body: {
      model: byId("modelSelect")?.value || "",
      server_url: byId("serverUrl")?.value.trim() || null,
      api_key: apiKey,
      prompt: "",
    }});
    loading(false);
    openForm({
      title: "Review visual description",
      eyebrow: "Vision proposal · not canon",
      description: "Arline described only the image. Saving keeps this as media metadata; it does not modify entity canon.",
      fields: [
        { name: "caption", label: "Caption", value: media.caption || "", full: true },
        { name: "description", label: "Visual description", type: "textarea", rows: 10, value: result.description || "", full: true },
      ],
      submit: "Save media description",
      onSubmit: async (values) => {
        await api(`/api/media/${encodeURIComponent(media.id)}`, { method: "PATCH", body: {
          caption: values.caption, description: values.description,
          description_source: `vision:${result.model}`,
        }});
        await loadProjectData();
        if (refresh) await refresh();
      },
    });
  } catch (error) { loading(false); toast(`Vision description failed: ${error.message}`, 6000); }
}

function editMediaMetadata(media, refresh) {
  openForm({
    title: "Edit visual reference",
    eyebrow: "Media metadata",
    description: "Media descriptions are reference metadata. Canon remains unchanged unless you explicitly stage a canon fact elsewhere.",
    fields: [
      { name: "kind", label: "Kind", type: "select", options: ["reference","portrait","outfit","concept","map","diagram"].map((x)=>({value:x,label:x})), value: media.kind || "reference" },
      { name: "caption", label: "Caption", value: media.caption || "", full: true },
      { name: "description", label: "Description", type: "textarea", rows: 8, value: media.description || "", full: true },
      { name: "sort_order", label: "Order", type: "number", value: Number(media.sort_order || 0) },
    ],
    onSubmit: async (values) => {
      await api(`/api/media/${encodeURIComponent(media.id)}`, { method: "PATCH", body: {
        kind: values.kind, caption: values.caption, description: values.description,
        description_source: "manual", sort_order: Number(values.sort_order || 0),
      }});
      await loadProjectData(); if (refresh) await refresh();
    },
  });
}

function mediaCardsHTML(items, scopeLabel) {
  if (!items.length) return `<div class="gallery-empty-media">No ${escapeHTML(scopeLabel.toLowerCase())} images yet.</div>`;
  const vision = selectedModelHasVision();
  return items.map((media) => `<article class="entity-media-card" data-media-id="${escapeHTML(media.id)}"><div class="entity-media-thumb"><img loading="lazy" src="${escapeHTML(media.content_url)}" alt="${escapeHTML(media.caption || media.original_name || "Visual reference")}"><span class="entity-media-badge ${media.is_cover ? "cover" : ""}">${media.is_cover ? "Cover" : escapeHTML(scopeLabel)}</span></div><div class="entity-media-body"><b>${escapeHTML(media.caption || media.original_name || media.kind || "Image")}</b><small>${escapeHTML(media.kind || "reference")}${media.description_source?.startsWith("vision:") ? " · vision reviewed" : ""}</small>${media.description ? `<p>${escapeHTML(media.description)}</p>` : ""}<div class="entity-media-card-actions"><button class="tiny-btn media-cover" ${media.is_cover ? "disabled" : ""}>Cover</button><button class="tiny-btn media-describe ${vision ? "" : "vision-unavailable"}" ${vision ? "" : "disabled"} title="${vision ? "Describe with selected local model" : "Selected model has no reported vision support"}">Describe</button><button class="tiny-btn media-edit">Edit</button><button class="tiny-danger-btn media-delete">Delete</button></div></div></article>`).join("");
}

async function renderEntityMediaSheet(family, variant) {
  const familyResult = await api(`/api/media?${new URLSearchParams({resource_type:"entity_family",resource_id:family.id})}`);
  const variantResult = variant ? await api(`/api/media?${new URLSearchParams({resource_type:"entity_variant",resource_id:variant.id})}`) : {items:[]};
  const familyMedia = familyResult.items || [], variantMedia = variantResult.items || [];
  const host = document.createElement("section");
  host.className = "sheet-section entity-media-section";
  const refresh = () => openEntitySheet(family.id, variant?.id || null);
  host.innerHTML = `<div class="sheet-section-head"><h3>Gallery & visual references</h3><div class="entity-media-actions"><button class="tiny-btn add-family-media">＋ Shared image</button>${variant ? `<button class="tiny-btn add-variant-media">＋ Variant image</button>` : ""}</div></div><p class="entity-media-note">Cover images power Gallery view. Vision descriptions stay reviewable media metadata and never become canon automatically.</p>${familyMedia.length ? `<div class="section-label">Shared identity</div><div class="entity-media-grid family-media-grid">${mediaCardsHTML(familyMedia,"Shared")}</div>` : `<div class="entity-media-grid family-media-grid">${mediaCardsHTML([],"Shared")}</div>`}${variant ? `<div class="section-label gap">Current variant</div><div class="entity-media-grid variant-media-grid">${mediaCardsHTML(variantMedia,"Variant")}</div>` : ""}`;
  byId("sheetBody").prepend(host);
  $(".add-family-media", host)?.addEventListener("click", () => chooseAndUploadMedia("entity_family", family.id, { refresh, makeCover: !familyMedia.some((x)=>x.is_cover) && !variantMedia.some((x)=>x.is_cover) }));
  $(".add-variant-media", host)?.addEventListener("click", () => chooseAndUploadMedia("entity_variant", variant.id, { refresh, makeCover: !variantMedia.some((x)=>x.is_cover) }));
  for (const card of $$("[data-media-id]", host)) {
    const media = [...familyMedia, ...variantMedia].find((x)=>x.id===card.dataset.mediaId); if (!media) continue;
    $(".media-cover", card)?.addEventListener("click", async()=>{await api(`/api/media/${encodeURIComponent(media.id)}`,{method:"PATCH",body:{is_cover:true}});await loadProjectData();await refresh();});
    $(".media-describe", card)?.addEventListener("click",()=>reviewVisionDescription(media,refresh));
    $(".media-edit", card)?.addEventListener("click",()=>editMediaMetadata(media,refresh));
    $(".media-delete", card)?.addEventListener("click",async()=>{if(!confirm("Delete this image from Arline media storage?"))return;await api(`/api/media/${encodeURIComponent(media.id)}`,{method:"DELETE"});await loadProjectData();await refresh();});
  }
}

'''
js = replace_once(js, '\nfunction worldCardHTML(item, index) {', '\n' + view_helpers + 'function worldCardHTML(item, index) {', 'gallery and media helpers')

# Add cover markup to every card; CSS shows it only in Gallery mode.
needle = '>${familyId ? `<button class="world-select-toggle" title="Select for bulk organization">${selected ? "✓" : ""}</button>` : ""}<div class="world-card-head">'
replacement = '>${galleryCoverHTML(item)}${familyId ? `<button class="world-select-toggle" title="Select for bulk organization">${selected ? "✓" : ""}</button>` : ""}<div class="world-card-head">'
js = replace_once(js, needle, replacement, 'world card cover markup')

js = replace_once(
    js,
    '  byId("worldGrid").innerHTML = cards.map(worldCardHTML).join("");\n',
    '  byId("worldGrid").innerHTML = cards.map(worldCardHTML).join("");\n  setLibraryViewMode(state.libraryViewMode, {persist:false, rerender:false});\n',
    'apply library view after render',
)

# Saved Views remember their presentation mode.
js = replace_once(
    js,
    'onSubmit: async (values) => { await api("/api/saved-views", { method:"POST", body:{ ...values, scope_type:"world_bible", query:{} } }); await loadProjectData(); }',
    'onSubmit: async (values) => { await api("/api/saved-views", { method:"POST", body:{ ...values, scope_type:"world_bible", query:{layout:state.libraryViewMode} } }); await loadProjectData(); }',
    'saved view stores layout',
)
js = replace_once(
    js,
    '  state.activeSavedViewId = viewId; state.activeWorldFolderId = null; state.activeCollectionId = null;\n',
    '  state.activeSavedViewId = viewId; state.activeWorldFolderId = null; state.activeCollectionId = null;\n  if (view.query?.layout) setLibraryViewMode(view.query.layout, {persist:false, rerender:false});\n',
    'saved view restores layout',
)

# Model detail makes vision capability visible to the user.
js = replace_once(
    js,
    'Reasoning: ${escapeHTML(allowed.join(", "))}`;',
    'Reasoning: ${escapeHTML(allowed.join(", "))}<br>Vision: ${model.capabilities?.vision ? "yes" : "no"}`;',
    'model info vision row',
)

# Inject media section into the normal entity sheet without rewriting the sheet.
start = js.find('async function openEntitySheet(')
end = js.find('\nfunction entityVariantSections', start)
if start < 0 or end < 0:
    raise SystemExit('openEntitySheet block not found')
block = js[start:end]
if 'await renderEntityMediaSheet(family, variant);' not in block:
    if '  openSheet();\n}' not in block:
        raise SystemExit('openEntitySheet final openSheet anchor missing')
    block = block.replace('  openSheet();\n}', '  await renderEntityMediaSheet(family, variant);\n  openSheet();\n}', 1)
    js = js[:start] + block + js[end:]

# Bind view-mode buttons and initialize their state.
js = replace_once(
    js,
    '  on("worldSearch", "input", renderWorldGrid);\n',
    '  on("worldSearch", "input", renderWorldGrid);\n  $$(\'[data-library-view]\').forEach((button)=>button.addEventListener("click",()=>setLibraryViewMode(button.dataset.libraryView,{persist:true,rerender:false})));\n',
    'library view event binding',
)
js = replace_once(
    js,
    '  refreshPromptHighlight(); updateScratchUI(); updateNavigationButtons(); updateComposerSessionMode(); resizeComposerInput();\n',
    '  setLibraryViewMode(state.libraryViewMode, {persist:false, rerender:false}); refreshPromptHighlight(); updateScratchUI(); updateNavigationButtons(); updateComposerSessionMode(); resizeComposerInput();\n',
    'initialize library view mode',
)
write(js_path, js)


# ---------------------------------------------------------------------------
# Regression tests for the final multimodal/gallery plumbing.
# ---------------------------------------------------------------------------
test_path = ROOT / "tests/test_v11_media_gallery.py"
test_path.write_text(r'''from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from src.inference.lmstudio import LMStudioClient
from src.workspace.foundation import FoundationStore
from src.workspace.store import WORKSPACE_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]


class V11MediaGalleryTests(unittest.TestCase):
    def test_schema_and_media_cover_lifecycle(self):
        self.assertEqual(WORKSPACE_SCHEMA_VERSION, 7)
        self.assertEqual(FoundationStore.SCHEMA_VERSION, 7)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = FoundationStore(root / "workspace.db")
            first_file = root / "first.png"; first_file.write_bytes(b"first")
            second_file = root / "second.png"; second_file.write_bytes(b"second")
            first = store.create_media("entity_family", "FAM-A", storage_path=str(first_file), mime_type="image/png", is_cover=True)
            second = store.create_media("entity_family", "FAM-A", storage_path=str(second_file), mime_type="image/png", is_cover=True)
            items = store.list_media(resource_type="entity_family", resource_id="FAM-A")
            covers = [item for item in items if item["is_cover"]]
            self.assertEqual([item["id"] for item in covers], [second["id"]])
            self.assertFalse(store.get_media(first["id"])["is_cover"])
            store.merge_resource_refs("entity_family", "FAM-A", "FAM-B")
            moved = store.list_media(resource_type="entity_family", resource_id="FAM-B")
            self.assertEqual(len(moved), 2)
            store.delete_media(first["id"])
            self.assertFalse(first_file.exists())

    def test_lmstudio_native_chat_accepts_image_data_urls(self):
        client = LMStudioClient(base_url="http://127.0.0.1:1234")
        fake = {"output": [{"type": "message", "content": "A black dress."}], "stats": {}}
        with patch.object(client, "_request", return_value=fake) as request:
            result = client.chat(
                model="vision-model", input_text="Describe this", system_prompt="visual",
                images=["data:image/png;base64,AA=="], reasoning=None, max_tokens=64,
            )
        payload = request.call_args.kwargs["payload"]
        self.assertEqual(payload["input"][0]["type"], "message")
        self.assertEqual(payload["input"][1]["type"], "image")
        self.assertEqual(payload["input"][1]["data_url"], "data:image/png;base64,AA==")
        self.assertEqual(result.text, "A black dress.")

    def test_ui_and_api_expose_gallery_and_reviewable_vision(self):
        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")
        css = (ROOT / "src/interface/web/static/arline.css").read_text(encoding="utf-8")
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        app = (ROOT / "src/interface/web/app.py").read_text(encoding="utf-8")
        provider = (ROOT / "src/inference/provider.py").read_text(encoding="utf-8")
        self.assertIn('data-library-view="gallery"', html)
        self.assertIn('arline.css?v=1.1.3-media', html)
        self.assertIn('.world-grid.view-gallery', css)
        self.assertIn('renderEntityMediaSheet', js)
        self.assertIn('reviewVisionDescription', js)
        self.assertIn('description_source: `vision:${result.model}`', js)
        self.assertIn('@app.post("/api/media/{media_id}/describe")', app)
        self.assertIn('"canon_changed": False', app)
        self.assertIn('"vision": bool((item.get("capabilities") or {}).get("vision"))', app)
        self.assertIn('vision: bool = False', provider)

    def test_home_review_handler_is_not_double_bound(self):
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        binding = '$$(\'[data-home-review]\',byId("homeView")).forEach'
        self.assertEqual(js.count(binding), 1)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

# Update older asset-generation test to the final generation.
settings_test = ROOT / "tests/test_settings_stack_layout.py"
text = settings_test.read_text(encoding="utf-8")
text = text.replace("arline.css?v=1.1.2-polish", "arline.css?v=1.1.3-media")
text = text.replace("stream.js?v=1.1.2-polish", "stream.js?v=1.1.3-media")
text = text.replace("arline.js?v=1.1.2-polish", "arline.js?v=1.1.3-media")
settings_test.write_text(text, encoding="utf-8")

print("V11_MEDIA_GALLERY_APPLIED")
