from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def read(rel): return (ROOT / rel).read_text(encoding='utf-8')
def write(rel, text): (ROOT / rel).write_text(text, encoding='utf-8')
def once(text, old, new, label):
    if old not in text: raise SystemExit(f'missing {label}')
    return text.replace(old, new, 1)

def skip_string(text,i,q):
    i+=1
    while i<len(text):
        if text[i]=='\\': i+=2; continue
        if text[i]==q: return i+1
        i+=1
    return i

def skip_comment(text,i):
    if text.startswith('//',i):
        j=text.find('\n',i+2); return len(text) if j<0 else j+1
    j=text.find('*/',i+2); return len(text) if j<0 else j+2

def function_range(text,name):
    m=re.search(rf'(?m)^(?:async\s+)?function\s+{re.escape(name)}\s*\(',text)
    if not m: raise SystemExit(f'function not found {name}')
    i=m.end(); paren=1; bracket=0
    while i<len(text):
        if text.startswith('//',i) or text.startswith('/*',i): i=skip_comment(text,i); continue
        if text[i] in "'\"`": i=skip_string(text,i,text[i]); continue
        ch=text[i]
        if ch=='(': paren+=1
        elif ch==')': paren=max(0,paren-1)
        elif ch=='[': bracket+=1
        elif ch==']': bracket=max(0,bracket-1)
        elif ch=='{' and paren==0 and bracket==0: body=i; break
        i+=1
    else: raise SystemExit(f'body missing {name}')
    depth=0; i=body
    while i<len(text):
        if text.startswith('//',i) or text.startswith('/*',i): i=skip_comment(text,i); continue
        if text[i] in "'\"`": i=skip_string(text,i,text[i]); continue
        if text[i]=='{': depth+=1
        elif text[i]=='}':
            depth-=1
            if depth==0: return m.start(),i+1
        i+=1
    raise SystemExit(f'unbalanced {name}')

def replace_function(text,name,repl):
    a,b=function_range(text,name); return text[:a]+repl.rstrip()+text[b:]

# Workspace: conservative identity merge only when variant scopes do not collide.
store=read('src/workspace/store.py')
merge_methods=r'''    def preview_entity_family_merge(self, source_family_id: str, target_family_id: str) -> dict[str, Any]:
        if source_family_id == target_family_id:
            raise ValueError("Source and target identity must be different")
        source = self.get_entity_family(source_family_id)
        target = self.get_entity_family(target_family_id)
        if source["entity_type"] != target["entity_type"]:
            raise ValueError("Only entity families of the same type can be merged")
        source_scopes = {(v["world_id"], v.get("branch_id")): v for v in source.get("variants", [])}
        target_scopes = {(v["world_id"], v.get("branch_id")): v for v in target.get("variants", [])}
        collisions = []
        for scope, left in source_scopes.items():
            right = target_scopes.get(scope)
            if right:
                collisions.append({"world_id": scope[0], "branch_id": scope[1], "source_variant_id": left["id"], "target_variant_id": right["id"]})
        return {
            "source": source,
            "target": target,
            "collisions": collisions,
            "safe": not collisions,
            "moved_variants": len(source_scopes),
        }

    def merge_entity_families(self, source_family_id: str, target_family_id: str) -> dict[str, Any]:
        preview = self.preview_entity_family_merge(source_family_id, target_family_id)
        if preview["collisions"]:
            raise ValueError("Automatic merge blocked: both identities have a variant in the same world/branch. Compare those variants explicitly before merging.")
        source, target = preview["source"], preview["target"]
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                source_core = dict(source.get("shared_core") or {})
                target_core = dict(target.get("shared_core") or {})
                merged_core = {**source_core, **target_core}
                description = target.get("description") or source.get("description") or ""
                con.execute("UPDATE entity_families SET description=?,shared_core_json=?,updated_at=? WHERE id=?", (description, _dumps(merged_core), now, target_family_id))
                con.execute("UPDATE entity_variants SET family_id=?,updated_at=? WHERE family_id=?", (target_family_id, now, source_family_id))

                # Polymorphic references that can be retargeted without semantic arbitration.
                for table, type_col, id_col in (
                    ("canon_facts", "owner_type", "owner_id"),
                    ("project_overlays", "owner_type", "owner_id"),
                    ("staged_changes", "owner_type", "owner_id"),
                    ("timeline_events", "owner_type", "owner_id"),
                    ("workspace_conflicts", "owner_type", "owner_id"),
                ):
                    con.execute(f"UPDATE {table} SET {id_col}=? WHERE {type_col}='entity_family' AND {id_col}=?", (target_family_id, source_family_id))
                con.execute("UPDATE scene_dependencies SET target_id=? WHERE target_type='entity_family' AND target_id=?", (target_family_id, source_family_id))

                # Many-to-many references: copy, then discard the source link.
                con.execute("INSERT OR IGNORE INTO workspace_tag_links(tag_id,resource_type,resource_id) SELECT tag_id,'entity_family',? FROM workspace_tag_links WHERE resource_type='entity_family' AND resource_id=?", (target_family_id, source_family_id))
                con.execute("DELETE FROM workspace_tag_links WHERE resource_type='entity_family' AND resource_id=?", (source_family_id,))
                con.execute("INSERT OR IGNORE INTO context_pins(id,project_id,world_id,branch_id,resource_type,resource_id,scope,priority,created_at) SELECT id||'-MERGED',project_id,world_id,branch_id,'entity_family',?,scope,priority,created_at FROM context_pins WHERE resource_type='entity_family' AND resource_id=?", (target_family_id, source_family_id))
                con.execute("DELETE FROM context_pins WHERE resource_type='entity_family' AND resource_id=?", (source_family_id,))

                manifest_rows = con.execute("SELECT project_id,label,priority,created_at FROM project_manifest_refs WHERE resource_type='entity_family' AND resource_id=?", (source_family_id,)).fetchall()
                for row in manifest_rows:
                    existing = con.execute("SELECT priority FROM project_manifest_refs WHERE project_id=? AND resource_type='entity_family' AND resource_id=?", (row["project_id"], target_family_id)).fetchone()
                    if existing:
                        con.execute("UPDATE project_manifest_refs SET priority=? WHERE project_id=? AND resource_type='entity_family' AND resource_id=?", (max(int(existing["priority"]), int(row["priority"])), row["project_id"], target_family_id))
                    else:
                        con.execute("INSERT INTO project_manifest_refs(project_id,resource_type,resource_id,label,priority,created_at) VALUES(?, 'entity_family', ?, ?, ?, ?)", (row["project_id"], target_family_id, target["name"], row["priority"], row["created_at"]))
                con.execute("DELETE FROM project_manifest_refs WHERE resource_type='entity_family' AND resource_id=?", (source_family_id,))

                self._purge_resource_refs_tx(con, "entity_family", source_family_id, purge_owned_facts=False)
                con.execute("DELETE FROM entity_families WHERE id=?", (source_family_id,))
                row = con.execute("SELECT * FROM entity_families WHERE id=?", (target_family_id,)).fetchone()
                self._add_revision_tx(con, "entity_family", target_family_id, self._family_row(row), f"merged identity {source.get('name')}")
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        result = self.get_entity_family(target_family_id)
        result["merged_from"] = {"id": source_family_id, "name": source.get("name")}
        return result

'''
store=once(store,'    def _create_variant_tx(\n',merge_methods+'    def _create_variant_tx(\n','merge insertion')
write('src/workspace/store.py',store)

# Foundation: move organizational references alongside a safe identity merge.
foundation=read('src/workspace/foundation.py')
foundation_method=r'''    def merge_resource_refs(self, resource_type: str, source_id: str, target_id: str) -> None:
        if source_id == target_id:
            return
        with self._lock, self._connection() as con:
            # aliases
            aliases = con.execute("SELECT alias,normalized_alias,created_at FROM resource_aliases WHERE resource_type=? AND resource_id=?", (resource_type, source_id)).fetchall()
            for row in aliases:
                con.execute("INSERT OR IGNORE INTO resource_aliases(id,resource_type,resource_id,alias,normalized_alias,created_at) VALUES(?,?,?,?,?,?)", (make_id("ALIAS"), resource_type, target_id, row["alias"], row["normalized_alias"], row["created_at"]))
            con.execute("DELETE FROM resource_aliases WHERE resource_type=? AND resource_id=?", (resource_type, source_id))
            # collections
            links = con.execute("SELECT collection_id,sort_order,added_at FROM workspace_collection_links WHERE resource_type=? AND resource_id=?", (resource_type, source_id)).fetchall()
            for row in links:
                con.execute("INSERT OR IGNORE INTO workspace_collection_links(collection_id,resource_type,resource_id,sort_order,added_at) VALUES(?,?,?,?,?)", (row["collection_id"], resource_type, target_id, row["sort_order"], row["added_at"]))
            con.execute("DELETE FROM workspace_collection_links WHERE resource_type=? AND resource_id=?", (resource_type, source_id))
            # favorites/issues point to the surviving identity.
            favorites = con.execute("SELECT project_id,label,created_at FROM workspace_favorites WHERE resource_type=? AND resource_id=?", (resource_type, source_id)).fetchall()
            for row in favorites:
                con.execute("INSERT OR IGNORE INTO workspace_favorites(id,project_id,resource_type,resource_id,label,created_at) VALUES(?,?,?,?,?,?)", (make_id("FAV"), row["project_id"], resource_type, target_id, row["label"], row["created_at"]))
            con.execute("DELETE FROM workspace_favorites WHERE resource_type=? AND resource_id=?", (resource_type, source_id))
            con.execute("UPDATE workspace_issues SET resource_id=?,updated_at=? WHERE resource_type=? AND resource_id=?", (target_id, utc_now(), resource_type, source_id))
            # context stacks are JSON, so retarget and deduplicate explicit refs.
            rows = con.execute("SELECT id,references_json FROM context_stack").fetchall()
            for row in rows:
                refs = _loads(row["references_json"], [])
                changed = False; seen = set(); out = []
                for ref in refs:
                    item = dict(ref)
                    if item.get("type") == resource_type and item.get("id") == source_id:
                        item["id"] = target_id; changed = True
                    key = (item.get("type"), item.get("id"), item.get("mode"))
                    if key in seen: continue
                    seen.add(key); out.append(item)
                if changed:
                    con.execute("UPDATE context_stack SET references_json=?,updated_at=? WHERE id=?", (_dumps(out), utc_now(), row["id"]))
            con.execute("DELETE FROM resource_lifecycle WHERE resource_type=? AND resource_id=?", (resource_type, source_id))

'''
foundation=once(foundation,'    # ------------------------------------------------------------------\n    # Identity / aliases\n',foundation_method+'    # ------------------------------------------------------------------\n    # Identity / aliases\n','foundation merge refs')
write('src/workspace/foundation.py',foundation)

# App payload + conservative merge endpoints.
app=read('src/interface/web/app.py')
payload='''class EntityFamilyMergePayload(BaseModel):\n    source_family_id: str\n    target_family_id: str\n\n\n'''
app=once(app,'class EntityFamilyPayload(BaseModel):\n',payload+'class EntityFamilyPayload(BaseModel):\n','merge payload')
merge_endpoints=r'''    @app.post("/api/library/entity-merge/preview")
    def entity_merge_preview(payload: EntityFamilyMergePayload):
        try:
            return workspace.preview_entity_family_merge(payload.source_family_id, payload.target_family_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/library/entity-merge")
    def entity_merge(payload: EntityFamilyMergePayload):
        try:
            source = workspace.get_entity_family(payload.source_family_id)
            source_aliases = foundation.list_aliases("entity_family", payload.source_family_id)
            result = workspace.merge_entity_families(payload.source_family_id, payload.target_family_id)
            foundation.merge_resource_refs("entity_family", payload.source_family_id, payload.target_family_id)
            try:
                foundation.add_alias("entity_family", payload.target_family_id, source["name"])
                for alias in source_aliases:
                    foundation.add_alias("entity_family", payload.target_family_id, alias["alias"])
            except ValueError:
                pass
            foundation.log_activity(None, "identity_merge", "entity_family", payload.target_family_id, label=result["name"], detail={"merged_from": payload.source_family_id})
            return result
        except (KeyError, ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(400, str(exc)) from exc

'''
app=once(app,'    @app.post("/api/quick-create/preview")\n',merge_endpoints+'    @app.post("/api/quick-create/preview")\n','merge endpoints')
write('src/interface/web/app.py',app)

# HTML: Library bulk toolbar.
html=read('src/interface/web/static/index.html')
html=once(html,'          <div id="worldTagFilters" class="tag-list compact"></div>\n        </div>\n        <div id="worldGrid"', '          <div id="worldTagFilters" class="tag-list compact"></div>\n          <div id="worldBulkBar" class="world-bulk-bar hidden"><b id="worldBulkCount">0 selected</b><button id="bulkMoveBtn" class="tiny-btn">Move</button><button id="bulkCollectionBtn" class="tiny-btn">Collection</button><button id="bulkArchiveBtn" class="tiny-btn">Archive</button><button id="bulkClearBtn" class="tiny-btn">Clear</button></div>\n        </div>\n        <div id="worldGrid"','world bulk toolbar')
write('src/interface/web/static/index.html',html)

css=read('src/interface/web/static/arline.css')
css += r'''
.world-bulk-bar{display:flex;align-items:center;gap:5px;margin-left:auto;border:1px solid var(--border);background:#272a27;border-radius:10px;padding:4px 6px}.world-bulk-bar b{font-size:8.5px;color:#cbd0cc;margin-right:3px}.world-card{position:relative}.world-select-toggle{position:absolute;top:8px;right:8px;width:20px;height:20px;border-radius:6px;border:1px solid var(--border);background:rgba(25,27,25,.88);color:transparent;display:flex;align-items:center;justify-content:center;z-index:2}.world-select-toggle:hover{border-color:rgba(78,193,156,.45)}.world-card.selected{outline:1px solid rgba(78,193,156,.46);background:rgba(47,155,129,.06)}.world-card.selected .world-select-toggle{background:var(--accent);color:#fff;border-color:var(--accent)}.turn-branches{border:1px solid rgba(163,139,226,.18)!important;color:#aaa0c8!important}.composer-draft-restored{color:#85b8a9;font-size:8.5px}
'''
write('src/interface/web/static/arline.css',css)

js=read('src/interface/web/static/arline.js')
js=once(js,'  liveRun: null,\n};','  liveRun: null,\n  worldSelection: new Set(),\n};','selection state')

helpers=r'''function composerDraftKey(sessionId = state.activeSession?.id || null) {
  if (sessionId) return `arline:composer:${sessionId}`;
  return `arline:composer:scope:${state.activeProject?.id || "none"}:${state.activeWorld?.id || "none"}:${state.activeBranch?.id || "none"}`;
}
function saveComposerDraft() {
  const input = byId("promptInput"); if (!input) return;
  const key = composerDraftKey();
  if (input.value) localStorage.setItem(key, input.value); else localStorage.removeItem(key);
}
function restoreComposerDraft() {
  const input = byId("promptInput"); if (!input) return;
  const value = localStorage.getItem(composerDraftKey()) || "";
  input.value = value; refreshPromptHighlight(); updateBudgetUI();
}
function clearComposerDraftKey(key) { if (key) localStorage.removeItem(key); }
function turnForks(turnId) { return (state.forkGraph?.sessions || []).filter((session) => session.forked_from_turn_id === turnId); }

function updateWorldBulkBar() {
  const bar = byId("worldBulkBar"); if (!bar) return;
  const count = state.worldSelection.size;
  bar.classList.toggle("hidden", !count); byId("worldBulkCount").textContent = `${count} selected`;
  $$(".world-card").forEach((card) => { const id=card.dataset.familyId; card.classList.toggle("selected", Boolean(id && state.worldSelection.has(id))); });
}
function clearWorldSelection() { state.worldSelection.clear(); updateWorldBulkBar(); }
async function bulkMoveSelected() {
  const ids=[...state.worldSelection]; if(!ids.length)return;
  const folders=flattenFolders(state.worldBibleFolderTree || state.worldBibleFolders || []);
  openForm({title:`Move ${ids.length} Library sheets`,eyebrow:"Bulk organize",fields:[{name:"folder_id",label:"Folder",type:"select",options:[{value:"",label:"No folder"},...folders.map((f)=>({value:f.id,label:f.path||f.name}))],full:true}],onSubmit:async(values)=>{for(const id of ids)await api(`/api/entities/families/${id}`,{method:"PATCH",body:{folder_id:values.folder_id||"",note:"bulk move"}});clearWorldSelection();await loadProjectData();toast(`Moved ${ids.length} sheets`);}});
}
async function bulkAddCollection() {
  const ids=[...state.worldSelection]; if(!ids.length)return;
  if(!state.worldCollections.length)return toast("Create a Library collection first");
  openForm({title:`Add ${ids.length} sheets to collection`,eyebrow:"Bulk organize",fields:[{name:"collection_id",label:"Collection",type:"select",options:state.worldCollections.map((c)=>({value:c.id,label:c.name})),full:true}],onSubmit:async(values)=>{for(const id of ids)await api(`/api/collections/${values.collection_id}/links`,{method:"POST",body:{resource_type:"entity_family",resource_id:id}});clearWorldSelection();await loadProjectData();toast(`Added ${ids.length} sheets to collection`);}});
}
async function bulkArchiveSelected() {
  const ids=[...state.worldSelection]; if(!ids.length||!confirm(`Archive ${ids.length} selected Library sheets?`))return;
  for(const id of ids)await api("/api/lifecycle/archive?archived=true",{method:"POST",body:{resource_type:"entity_family",resource_id:id}});
  clearWorldSelection();await loadProjectData();toast(`Archived ${ids.length} sheets`);
}

function openEntityMergeForm(family) {
  const candidates=state.families.filter((item)=>item.id!==family.id&&item.entity_type===family.entity_type);
  if(!candidates.length)return toast("No same-type identity is available to merge into");
  openForm({title:`Merge duplicate “${family.name}”`,eyebrow:"Library identity",description:"Safe merge preserves organizational references and moves variants only when target scopes do not collide. Overlapping variants require manual comparison.",fields:[{name:"target_id",label:"Merge into",type:"select",options:candidates.map((item)=>({value:item.id,label:item.name})),full:true}],submit:"Preview merge",onSubmit:async(values)=>{
    const preview=await api("/api/library/entity-merge/preview",{method:"POST",body:{source_family_id:family.id,target_family_id:values.target_id}});
    if(preview.collisions?.length){byId("compareTitle").textContent="Merge needs manual variant review";byId("compareBody").innerHTML=`<p class="compare-note">Arline will not guess which overlapping world/branch state should win.</p>${preview.collisions.map((c)=>`<div class="backlink-row"><b>${escapeHTML(worldName(c.world_id))}</b><small>${escapeHTML(c.branch_id||"main")} · source ${escapeHTML(c.source_variant_id)} ↔ target ${escapeHTML(c.target_variant_id)}</small></div>`).join("")}`;byId("compareDialog").showModal();return;}
    if(!confirm(`Merge “${family.name}” into “${preview.target.name}”? The source identity becomes an alias and its non-overlapping variants move to the target.`))return;
    const result=await api("/api/library/entity-merge",{method:"POST",body:{source_family_id:family.id,target_family_id:values.target_id}});closeSheet();clearWorldSelection();await loadProjectData();await openEntitySheet(result.id);toast(`Merged duplicate into “${result.name}”`);
  }});
}

'''
idx=js.index('function attachEvents()')
js=js[:idx]+helpers+js[idx:]

# newChat saves old draft and restores scope draft.
old_newchat=function_range(js,'newChat'); a,b=old_newchat
newchat=js[a:b]
newchat=newchat.replace('function newChat() {','function newChat() {\n  saveComposerDraft();',1)
newchat=newchat.replace('  setView("chat");','  setView("chat");\n  restoreComposerDraft();',1)
js=js[:a]+newchat+js[b:]

# openSession saves previous draft before switching and restores selected chat draft after render.
a,b=function_range(js,'openSession'); block=js[a:b]
block=block.replace('async function openSession(id) {','async function openSession(id) {\n  saveComposerDraft();',1)
block=block.replace('    renderConversation(session.turns || []); setView("chat"); renderSessions();','    renderConversation(session.turns || []); setView("chat"); renderSessions(); restoreComposerDraft();',1)
js=js[:a]+block+js[b:]

# world card selection affordance.
world_card=r'''function worldCardHTML(item, index) {
  const iconType = item.type === "entity" ? item.family.entity_type : item.type;
  const familyId = item.type === "entity" ? item.family.id : "";
  const selected = familyId && state.worldSelection.has(familyId);
  return `<article class="world-card ${selected ? "selected" : ""}" data-index="${index}" ${familyId ? `data-family-id="${familyId}"` : ""}>${familyId ? `<button class="world-select-toggle" title="Select for bulk organization">${selected ? "✓" : ""}</button>` : ""}<div class="world-card-head"><span class="world-card-icon">${escapeHTML(ENTITY_ICONS[iconType] || "◇")}</span><span class="canon-badge ${escapeHTML(item.status)}">${escapeHTML(item.status)}</span></div><h3>${escapeHTML(item.label)}</h3><p>${escapeHTML(item.summary || "No description")}</p><div class="world-card-meta"><span>${escapeHTML(iconType.replaceAll("_", " "))}</span>${item.variant ? `<span>${escapeHTML(worldName(item.variant.world_id))}</span>` : ""}</div></article>`;
}'''
js=replace_function(js,'worldCardHTML',world_card)

# Turn branch indicator using already-loaded fork graph.
a,b=function_range(js,'turnHTML'); block=js[a:b]
block=block.replace('  const runStatus = stats.run_status || "completed";','  const runStatus = stats.run_status || "completed";\n  const branches = turnForks(turn.id);',1)
block=block.replace('${qualityChip}</div><div class="assistant-actions">','${qualityChip}${branches.length ? `<button class="tiny-btn turn-branches">↗ ${branches.length} branch${branches.length===1?"":"es"}</button>` : ""}</div><div class="assistant-actions">',1)
js=js[:a]+block+js[b:]

# Bind branch switcher plus existing actions.
a,b=function_range(js,'bindTurnActions'); block=js[a:b]
anchor='    $(".quality-turn", node)?.addEventListener("click", () => turn && showQualityReport(turn));'
replace=anchor+'\n    $(".turn-branches", node)?.addEventListener("click", (event) => { const branches=turnForks(turnId); contextMenu(event.clientX,event.clientY,branches.map((session)=>({label:session.title||"Chat branch",action:()=>openSession(session.id)}))); });'
if anchor not in block: raise SystemExit('turn branch action anchor missing')
block=block.replace(anchor,replace,1); js=js[:a]+block+js[b:]

# Add merge button to entity sheet footer/binding.
footer_anchor='<button id="whereUsedEntityBtn" class="secondary-btn">Where used</button>'
js=once(js,footer_anchor,'<button id="mergeEntityBtn" class="secondary-btn">Merge duplicate…</button>'+footer_anchor,'entity merge footer')
js=once(js,'  byId("deleteFamilyBtn").addEventListener("click", () => deleteEntityFamily(family));','  byId("deleteFamilyBtn").addEventListener("click", () => deleteEntityFamily(family));\n  byId("mergeEntityBtn")?.addEventListener("click", () => openEntityMergeForm(family));','entity merge bind')

# Hook bulk selection after world cards render. Use capture listener on grid so card open logic remains unchanged.
attach_anchor='  on("worldSearch", "input", renderWorldGrid);'
attach_new='''  on("worldSearch", "input", renderWorldGrid);
  on("worldGrid", "click", (event) => {
    const toggle=event.target.closest(".world-select-toggle"); if(!toggle)return;
    event.preventDefault(); event.stopImmediatePropagation(); const card=toggle.closest(".world-card"); const id=card?.dataset.familyId; if(!id)return;
    if(state.worldSelection.has(id))state.worldSelection.delete(id);else state.worldSelection.add(id);updateWorldBulkBar();toggle.textContent=state.worldSelection.has(id)?"✓":"";
  }, true);
  on("bulkMoveBtn", "click", bulkMoveSelected); on("bulkCollectionBtn", "click", bulkAddCollection); on("bulkArchiveBtn", "click", bulkArchiveSelected); on("bulkClearBtn", "click", clearWorldSelection);'''
js=once(js,attach_anchor,attach_new,'bulk bindings')

# Composer draft persistence and connection status.
js=once(js,'  on("promptInput", "input", () => { updateAutocomplete(); refreshPromptHighlight(); updateBudgetUI(); });','  on("promptInput", "input", () => { saveComposerDraft(); updateAutocomplete(); refreshPromptHighlight(); updateBudgetUI(); });','composer draft input')
js=once(js,'  on("refreshModelsBtn", "click", refreshModels); on("saveSettingsBtn", "click", saveSettings);','  on("refreshModelsBtn", "click", refreshModels); on("connectionBadge", "click", refreshModels); on("saveSettingsBtn", "click", saveSettings);','connection reconnect')
js=once(js,'    setConnection(true, `${payload.models?.length || 0} models`);\n    updateModelInfo();','    updateModelInfo();\n    const selectedModel=state.modelMap.get(select.value);\n    setConnection(true, selectedModel ? `${selectedModel.loaded?"loaded":"available"} · ${selectedModel.max_context_length?`${Math.round(selectedModel.max_context_length/1024)}K`:"model"}` : `${payload.models?.length||0} models`);','connection lifecycle detail')
# Clear sent draft and persist drafts before unload.
js=once(js,'  const payload = promptPayload();\n  if (!payload.prompt.trim()) return toast("Write a prompt first");','  const payload = promptPayload();\n  const sentDraftKey = composerDraftKey();\n  if (!payload.prompt.trim()) return toast("Write a prompt first");','sent draft key')
js=once(js,'  byId("promptInput").value = ""; refreshPromptHighlight(); updateBudgetUI();','  byId("promptInput").value = ""; clearComposerDraftKey(sentDraftKey); refreshPromptHighlight(); updateBudgetUI();','clear sent draft')
js=once(js,'  window.addEventListener("hashchange", () => {','  window.addEventListener("beforeunload", saveComposerDraft);\n  window.addEventListener("hashchange", () => {','beforeunload draft')
# keep bulk selection accurate after World grid rerenders
js=once(js,'  byId("worldEmpty").classList.toggle("hidden",cards.length>0);','  byId("worldEmpty").classList.toggle("hidden",cards.length>0); updateWorldBulkBar();','bulk rerender')
write('src/interface/web/static/arline.js',js)

# tests
test=r'''from __future__ import annotations
from pathlib import Path
import tempfile
import unittest

from src.workspace import WorkspaceStore, WORLD_BIBLE_WORLD_ID

ROOT=Path(__file__).resolve().parents[1]

class V11LastMileTests(unittest.TestCase):
    def test_safe_identity_merge_moves_non_overlapping_variants(self):
        with tempfile.TemporaryDirectory() as td:
            store=WorkspaceStore(Path(td)/"db.sqlite")
            target=store.create_entity_family(None,"Apartment",entity_type="location")
            source=store.create_entity_family(None,"A0325",entity_type="location",create_variant_in_world=WORLD_BIBLE_WORLD_ID)
            preview=store.preview_entity_family_merge(source["id"],target["id"])
            self.assertTrue(preview["safe"])
            merged=store.merge_entity_families(source["id"],target["id"])
            self.assertEqual(len(merged["variants"]),1)
            with self.assertRaises(KeyError): store.get_entity_family(source["id"])

    def test_identity_merge_blocks_scope_collision(self):
        with tempfile.TemporaryDirectory() as td:
            store=WorkspaceStore(Path(td)/"db.sqlite")
            left=store.create_entity_family(None,"Left",entity_type="character",create_variant_in_world=WORLD_BIBLE_WORLD_ID)
            right=store.create_entity_family(None,"Right",entity_type="character",create_variant_in_world=WORLD_BIBLE_WORLD_ID)
            preview=store.preview_entity_family_merge(left["id"],right["id"])
            self.assertFalse(preview["safe"])
            with self.assertRaises(ValueError): store.merge_entity_families(left["id"],right["id"])

    def test_last_mile_ui_foundations_exist(self):
        js=(ROOT/"src/interface/web/static/arline.js").read_text(encoding="utf-8")
        html=(ROOT/"src/interface/web/static/index.html").read_text(encoding="utf-8")
        self.assertIn("composerDraftKey",js)
        self.assertIn("turnForks",js)
        self.assertIn("openEntityMergeForm",js)
        self.assertIn("bulkMoveSelected",js)
        self.assertIn('id="worldBulkBar"',html)

if __name__=="__main__": unittest.main()
'''
write('tests/test_v11_lastmile.py',test)
Path(__file__).unlink()
print('v1.1 last-mile patch applied')
