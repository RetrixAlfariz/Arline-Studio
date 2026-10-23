<p align="center">
  <img src="src/interface/web/static/assets/brand/arline-primary.svg" width="88" height="88" alt="Arline mark">
</p>

<h1 align="center">Arline Studio</h1>

<p align="center">
  <strong>Write the scene. Keep the world coherent.</strong><br>
  A local-first writing workspace for stories, characters, and the worlds they inhabit.
</p>

<p align="center">
  <a href="#quick-start">Get started</a> ·
  <a href="#the-workspace">Explore the workspace</a> ·
  <a href="#development">Development</a> ·
  <a href="crates/arline-runtime/VALIDATION.md">Native validation</a>
</p>

<p align="center">
  <img src="frontend/src/assets/writing-island.png" width="700" alt="An open book becoming a coastal path to a lighthouse">
</p>

Arline brings conversations, manuscripts, and structured worldbuilding into one workspace. Develop an idea in Story Lab, write a scene with explicit references, and keep the resulting prose separate from the facts you choose to make canon.

The desktop application uses **React + TypeScript**, a **Rust/Axum runtime**, and **Tauri**. **LM Studio** runs the language model. The native application runs without Python; the Python backend remains available for development and existing workflows.

> **Development status:** v1.2 alpha (`1.2.5a1`). The native runtime is on `main`. See the [validation record](crates/arline-runtime/VALIDATION.md) for tested behavior and migration limits.

## The workspace

| Surface | What you do there |
| --- | --- |
| **Chat** | Write prose in **Story Writer**, develop ideas in **Story Lab**, or enter a scene through **Interactive** mode. Stream responses, fork conversations, and review previous turns. |
| **Manuscript** | Organize scenes, chapters, notes, research, and outlines. Use checkpoints for meaningful revisions and recovery state for work in progress. |
| **Library** | Maintain worlds, characters, locations, items, relationships, and canon facts. Use entity variants for differences across worlds and branches. |
| **Context Stack** | Choose the references, scene, and scope a generation may use. Opening a sheet and adding it to context are separate actions. |
| **Quick Create** | Describe a scene, character, location, or other resource naturally, then review the structured result. |
| **Review & Evals** | Accept, edit, or reject writing and export review data. Feedback collection does not automatically train a model. |

Library sheets are shared world knowledge. Projects organize the writing you are making from that knowledge. Putting a Library sheet in a folder does not make it owned by a Project.

### Three ways to work in Chat

- **Story Writer** turns a writing request into prose, using the selected context and generation settings.
- **Story Lab** helps develop a premise, character, or story problem through discussion. It writes fiction when you explicitly ask for it.
- **Interactive** lets you enter the scene through a chosen Presence while keeping your dialogue and major decisions under your control.

Planning and model reasoning have separate controls. You can ask Arline to plan a scene before writing without enabling the model's reasoning mode.

## Quick start

The source launcher currently targets **Windows**. Before building, install:

| Requirement | Purpose |
| --- | --- |
| PowerShell 7 | Run the native launcher. |
| Node.js **22.12+** and npm | Install and build the React interface. |
| Rust **1.88+**, with the MSVC toolchain | Build the native runtime and desktop host. |
| Visual Studio C++ Build Tools and Windows SDK | Compile and link native dependencies. |
| Microsoft Edge WebView2 Runtime | Display the desktop window. |
| LM Studio and a downloaded generation model | Run local inference. Model weights are installed separately. |

### First launch

Start LM Studio's local API server at `http://127.0.0.1:1234`, then run:

```powershell
git clone https://github.com/RetrixAlfariz/Arline-Studio.git "Arline Studio"
cd "Arline Studio"
npm --prefix frontend ci
.\run-native.ps1
```

The launcher builds the frontend and release executable, then opens the desktop application. In **Settings → Models & Runtime**, select a model that is actually installed in LM Studio. The model key in the repository configuration may differ from yours.

For later launches, reuse the compiled application:

```powershell
.\run-native.ps1 -SkipBuild
```

Run without `-SkipBuild` after changing the application source. The release executable is written to `crates/arline-runtime/target/release/arline.exe`.

### Other launch options

```powershell
# Serve the application in your browser without a desktop window.
.\run-native.ps1 -SkipBuild -Headless
# Open http://127.0.0.1:7861

# Use a separate copy of your data for a trial.
.\run-native.ps1 -SkipBuild -DataDirectory E:\Arline-native-trial

# Build without launching, or choose a different port.
.\run-native.ps1 -BuildOnly
.\run-native.ps1 -SkipBuild -Port 17861
```

The launcher uses loopback port **7861** by default. Pass `-Port 0` to select a free port. Native CLI options and model-loading details are documented in the [runtime guide](crates/arline-runtime/README.md).

## From an idea to a scene

1. **Choose a Project, World, and branch.** These define the active workspace scope.
2. **Build the references you need.** Use Quick Create for characters and places, then review their sheets in the Library.
3. **Add context deliberately.** Use explicit references and the Context Stack to choose what the model can draw on.
4. **Discuss or write.** Work through uncertainty in Story Lab, then switch to Story Writer when you want the scene itself.
5. **Review the result.** Keep the prose, revise it in Manuscript, and explicitly review any proposed changes to canon.

For example, a writing request can be as direct as:

```text
At dawn, Mara returns to the lighthouse with a letter she was told
never to open. Continue the scene, keeping the letter sealed.
```

### Context and canon

Arline distinguishes between **established facts**, **retrieved evidence**, **creative exploration**, and **generated prose**. Retrieval uses scoped sources, structured lookup, and SQLite FTS5; a search result is evidence to inspect, not an automatic canon update.

Chat forks create separate conversations. World branches represent changes in world state. Scratch mode supports exploration without staging proposed state changes into canon.

Visual references can belong to Library identities or their variants. A reviewed image description remains media metadata until you explicitly make a canon decision.

## Your data

On first launch, the native launcher copies the repository's runtime configuration, writer prompt, and configured SQLite data into an application data directory. It preserves uncheckpointed WAL changes and rehomes managed media. Subsequent launches use that application copy.

| Native data | Default Windows location |
| --- | --- |
| Workspace database | `%LOCALAPPDATA%\Arline Studio\arline_history.db` |
| Runtime configuration | `%LOCALAPPDATA%\Arline Studio\config\arline.toml` |
| Managed images and media | `%LOCALAPPDATA%\Arline Studio\media\` |
| Saved runs, output, and dataset exports | Under `%LOCALAPPDATA%\Arline Studio\` |

Use `-DataDirectory` to choose another location. After the first launch, change native settings in the application or its copied configuration; editing the repository's `config/arline.toml` does not update an existing application copy.

- The original repository workspace is preserved during bootstrap. Keep it until you have reviewed the imported data.
- Supported schema upgrades create SQLite backups. This does not establish compatibility with every historical database version.
- Trash supports recovery; permanent deletion is a separate action. Shared Library sheets are not owned by the Projects that reference them.
- Generation requests go to the configured LM Studio server, which defaults to your machine. Model weights are not bundled with Arline.
- API credentials stay out of the public configuration response and saved portable settings. `ARLINE_LMSTUDIO_API_KEY` supplies a runtime credential when needed.

## Development

### Frontend with the Python backend

The Vite development proxy targets the Python backend on port **7860**. Python **3.11+** and `uv` are required for this path.

From the repository root:

```powershell
uv sync
uv run python app.py
```

In a second terminal, from the same root:

```powershell
npm --prefix frontend ci
npm --prefix frontend run dev
```

Open `http://127.0.0.1:5173`. Vite proxies API and asset requests to `http://127.0.0.1:7860`. See [Vite's configuration](frontend/vite.config.ts) before pointing it at a different backend or port.

### Integrated Python interface and CLI

```powershell
npm --prefix frontend run build
uv run python app.py
# Open http://127.0.0.1:7860

uv run python main.py --help
uv run python shutdown.py --dry-run
```

`app.py` serves the built React interface when available and falls back to the legacy static interface when it is absent. The Python path reads `config/arline.toml` and normally uses repository-local `data/` and `output/` directories. `shutdown.py` targets the Python web server; it is not the native desktop shutdown command.

### Validation

Run these commands from the repository root. Install the dependencies for the relevant runtime first.

```powershell
# Native runtime and desktop feature.
cargo test --locked --features desktop --manifest-path crates/arline-runtime/Cargo.toml
cargo clippy --locked --features desktop --manifest-path crates/arline-runtime/Cargo.toml --all-targets -- -D warnings

# React type checking and production build.
npm --prefix frontend run typecheck
npm --prefix frontend run build

# Python regression suite.
uv run python -m unittest discover -s tests -v
```

The automated suites use temporary databases and mock model providers where needed. Real-model observations and migration checks are recorded separately in [native validation](crates/arline-runtime/VALIDATION.md). Route inventory coverage does not prove identical semantics or output for every historical endpoint.

### Repository map

| Path | Responsibility |
| --- | --- |
| [`frontend/`](frontend/) | React interface, client state, and Vite configuration. |
| [`crates/arline-runtime/`](crates/arline-runtime/) | Rust application runtime, SQLite services, inference integration, and Tauri host. |
| [`crates/arline-native/`](crates/arline-native/) | Optional Rust storage extension for the Python backend. |
| [`src/`](src/) | Python backend, CLI services, and legacy interface. |
| [`config/`](config/) | Repository defaults and writer contracts. |
| [`tests/`](tests/) | Python and legacy frontend regression coverage; native tests live in the runtime crate. |

## License

Arline Studio is available under the [MIT License](LICENSE).
