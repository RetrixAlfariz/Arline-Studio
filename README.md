# Arline Studio 1.1

Arline Studio is a Project that mainly focused on making story.

## v1.1 status

**Feature scope is frozen.** After the final v1.1 PR is merged, changes on the v1.1 line should be bug fixes, regressions, compatibility fixes, and data-safety fixes only. New memory/RAG, autonomous reasoning, visual-semantic analysis, consequence simulation, relationship dynamics, and other intelligence-layer work belongs to v1.2.

## v1.1 mental model

- **Library** — what is true: worlds, entity sheets, variants, relationships, canon facts, lore, timeline.
- **Project** — what you are making: a focused story workspace, folders, manuscript, notes, research, assets, and references.
- **Manuscript** — what you have written: scenes, chapters, notes, research, and outline views.
- **Chat** — what you are exploring: conversations, forks, scratch/what-if exploration.
- **Scene** — where you are narratively: POV, location, participants, narrative time, target outcome.
- **Review & Evals** — what Arline learns from your choices: review, accept/edit/reject, fork comparisons, and advanced dataset exports under Settings → Developer.
- **Context Stack** — what Arline is allowed to use for the current generation.

Opening something in the UI does **not** automatically put it into context. Navigation state and Context Stack are deliberately separate.

## Quick start

1. Install the project dependencies used by your existing Arline setup. `uv sync`
2. Start LM Studio and expose its local API (the default config expects `127.0.0.1:1234`).
3. From the repository root, run either:

```powershell
python app.py
```

or the existing CLI entry point:

```powershell
python main.py
```

4. Open the Studio URL configured under `[ui]` in `config/arline.toml` (default port `7860`).

The SQLite database, local media, exports, backups, and generated output are runtime data and are intentionally not included in release ZIPs.

## The v1.1 workflow

### Create naturally

Use **Quick Create** instead of filling schema-heavy forms. For example:

```text
Taman Bunga di belakang kampus
```

Arline can infer a Location sheet, suggest possible duplicate identities, and place the sheet in a Library folder. Advanced family/variant/JSON editing is still available from the Inspector.

### Organize the Library

Library folders are organizational only. A sheet remains shared knowledge and is never made Project-owned by putting it in a folder.

Use:

- **Folders** for one structural location.
- **Tags** for many-to-many descriptors.
- **Collections** for curated groups without moving a sheet.
- **Saved Views** for reusable filters/query views.

Library presentation is independent of the underlying object model. The same sheets can be browsed as **List**, **Grid**, or **Gallery**, and Saved Views can remember their layout.

### Gallery and visual references

Library sheets can carry local visual references without turning images into a separate canon system.

- Entity families can have shared identity images.
- World/branch variants can have variant-specific images.
- One image per resource can be selected as its **Cover** for Gallery view.
- Media can store a kind, caption, ordering, and reviewed visual description.
- Deleting a media item removes its managed local file; permanent resource deletion also cleans its media, while identity merges move media to the surviving identity.
- The selected model's LM Studio metadata controls whether the **Describe** action is available.
- When a vision-capable local model is selected, **Describe** sends the image through the existing LM Studio inference path and returns a reviewable visual-description proposal.
- A vision description is saved only after explicit review and remains **media metadata, not canon**. It never silently changes character attributes, facts, relationships, or world state.

Gallery/visual references are the final v1.1 multimodal foundation. Automatic image tagging, visual embeddings/similarity, image-vs-canon contradiction detection, and autonomous multimodal canon extraction are intentionally deferred to v1.2.

### Write in Manuscript

Project folders contain Project files only. Manuscript items use explicit types such as Scene, Chapter, Note, Research, and Outline. Writing status is separate:

```text
Planned → Writing → Revising → Final
```

Editing autosaves recovery state without flooding revision history. Use **Checkpoint** when you want a meaningful durable revision.

### Use Context Stack deliberately

The Context Stack tracks the active Project, World/branch, Scene, Chat fork, Run Profile, explicit references, pins, and overrides. `@references` can use Mention / Context / Deep depth without changing the Library itself.

Visual media is not injected into normal story context merely because a sheet is open or has a cover. v1.1 uses vision only for the explicit **Describe image** action.

### Fork without polluting canon

A Chat fork is only a conversation fork. It does not become a semantic World branch unless you explicitly promote it. Scratch mode prevents proposed state changes from being staged into canon.

### Review instead of silently learning

Generated prose is reviewable under **Settings → Developer → Review & Evals**. Accept/edit/reject decisions and fork comparisons can later feed SFT, preference, and evaluation exports; dataset plumbing stays out of the primary writing navigation.

## v1.1 final UI / recovery polish

- The Composer stays spacious for a new chat, then automatically becomes a compact sticky dock once a conversation is active.
- Response-length, token-budget, and context-detail controls collapse in active chats and can be expanded from the profile control when needed.
- Chat rendering is progressive: very long sessions initially render only the newest turns and expose a **Load earlier messages** control.
- Unsent Composer drafts, the last chat/document, navigation state, density, and sidebar preferences are restored where possible after restart.
- First-run onboarding offers **Start a story**, **Build the Library**, and **Import existing writing** without exposing the underlying schema first.
- Settings uses a vertical top-to-down layout. Developer tools can be hidden when the user only wants writing-facing settings.
- **Data & Storage → Workspace health** provides a read-only Doctor that reports dangling references, stale scene pointers, and obvious duplicate identities without auto-repairing canon.
- Startup failures keep a visible recovery surface with direct access to Data & Storage and reload, rather than disappearing into a transient toast.
- Settings search matches both category names and the actual setting content inside each panel.
- Static assets are versioned together so browsers are less likely to mix stale HTML, CSS, and JavaScript after an update.
- Library view modes are List / Grid / Gallery, with local cover images and explicit vision-description review.

## Data safety

Normal destructive actions use **Trash**, not immediate permanent deletion. Activity Center provides Restore and explicit permanent deletion. Archive is separate from Trash.

Before a database schema upgrade, v1.1 creates a consistent SQLite backup under the runtime database directory's `backups/` folder. Legacy Manuscript rows are migrated from the old broad Draft vocabulary to the v1.1 Scene/writing-state model. The visual-reference foundation advances the shared workspace schema to v7 and therefore passes through the same pre-migration backup boundary.

Project deletion never owns or deletes shared Library sheets. Project bundles reference Library resources rather than silently embedding ownership copies.

## Useful shortcuts

- `Ctrl/Cmd + K` — global Search / Command Palette
- `Ctrl/Cmd + Shift + P` — Command Palette
- `Ctrl/Cmd + N` — Quick Create
- `Ctrl/Cmd + Shift + N` — New Chat
- `Ctrl/Cmd + S` — create a meaningful Manuscript checkpoint
- `Ctrl/Cmd + Z` — undo the most recent Trash action when not editing text
- `Alt + Left / Right` — navigation history
- `Ctrl/Cmd + Shift + F` — Manuscript Focus mode

## Regression tests

The v1.1 foundation suite uses temporary databases and does not require a running LM Studio server:

```powershell
python -m unittest discover -s tests -v
```

A release pass should also include:

```powershell
python -m compileall -q src
node --check src/interface/web/static/js/commands.js
node --check src/interface/web/static/js/stream.js
node --check src/interface/web/static/arline.js
```

## v1.1 hardening guarantees

- Composer reference highlighting only overlays actual `@references` and `/commands`; plain prose remains a native textarea with native spellcheck.
- Context-budget UI consumes the same token-breakdown contract returned by the backend, so response MAX is computed from real assembled context rather than prompt length alone.
- Run Profiles capture and restore the complete generation configuration.
- Normal deletion is recoverable Trash; permanent project/world/branch deletion uses one cross-store cleanup path so chat history cannot become orphaned.
- Existing SQLite data is backed up before **any** History/Workspace migration starts, including pre-versioned legacy databases.
- Context Stack state is browser-tab scoped, preventing two open Studio tabs from overwriting each other.
- API keys are no longer returned by `/api/config` or sent in model-discovery query strings.
- CI rejects duplicate top-level frontend functions and frontend/backend context-contract regressions.
- The final v1.1 release gate covers compact Composer behavior, onboarding/recovery surfaces, Data Doctor wiring, progressive chat rendering, Developer/Settings separation, Gallery/media lifecycle, and native LM Studio image-input plumbing.
