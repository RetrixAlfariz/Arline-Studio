import { useEffect, useState } from "react";
import { AlertTriangle, Cpu, Database, RefreshCcw, Save, SlidersHorizontal, Trash2, X } from "lucide-react";
import { studioApi } from "../api";
import { browserStorage } from "../browserStorage";
import type { ModelInfo, RuntimeConfig } from "../types";

interface SettingsDrawerProps {
  open: boolean;
  config: RuntimeConfig;
  onConfig: (config: RuntimeConfig) => void;
  onClose: () => void;
}

type SettingsTab = "runtime" | "generation" | "context" | "storage";
type ResetMode = "database" | "complete";

export function SettingsDrawer({ open, config, onConfig, onClose }: SettingsDrawerProps) {
  const [tab, setTab] = useState<SettingsTab>("runtime");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [apiKey, setApiKey] = useState("");
  const [status, setStatus] = useState("");
  const [loadingModels, setLoadingModels] = useState(false);
  const [resetMode, setResetMode] = useState<ResetMode | null>(null);
  const [resetConfirmation, setResetConfirmation] = useState("");
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    if (!open) setStatus("");
  }, [open]);

  if (!open) return null;

  const patch = <K extends keyof RuntimeConfig>(key: K, value: RuntimeConfig[K]) => onConfig({ ...config, [key]: value });

  const refreshModels = async () => {
    setLoadingModels(true);
    setStatus("");
    try {
      const result = await studioApi.models(config.server_url, apiKey);
      setModels(result.models || []);
      setStatus(`Found ${result.models?.length || 0} model(s)`);
    } catch (error) {
      setStatus((error as Error).message);
    } finally {
      setLoadingModels(false);
    }
  };

  const save = async () => {
    setStatus("Saving…");
    try {
      await studioApi.saveSettings({
        server_url: config.server_url,
        api_key: apiKey || null,
        model: config.model,
        gpu_ratio: config.gpu_ratio,
        context_length: config.context_length,
        input_mode: config.input_mode,
        reasoning: config.reasoning,
        projection_mode: config.projection_mode,
        temperature: config.temperature,
        top_p: config.top_p,
        top_k: config.top_k,
        min_p: config.min_p,
        repeat_penalty: config.repeat_penalty,
        visible_output_tokens: config.visible_output_tokens,
        reasoning_reserve_tokens: config.reasoning_reserve_tokens,
        generation_mode: config.generation_mode,
        beat_count: config.beat_count,
        beat_tokens: config.beat_tokens,
        total_story_target_tokens: config.total_story_target_tokens,
      });
      setStatus("Settings saved. API keys remain session-only.");
    } catch (error) {
      setStatus((error as Error).message);
    }
  };

  const closeReset = () => {
    if (resetting) return;
    setResetMode(null);
    setResetConfirmation("");
  };

  const performReset = async () => {
    if (!resetMode) return;
    setResetting(true);
    setStatus("Resetting local data…");
    try {
      await studioApi.resetStorage(resetMode, resetConfirmation);
      browserStorage.clearArline();
      location.reload();
    } catch (error) {
      setStatus((error as Error).message);
      setResetting(false);
    }
  };

  return (
    <>
      <div className="drawer-scrim" onMouseDown={onClose} />
      <aside className="settings-drawer">
        <header><div><span className="eyebrow">Arline Studio</span><h2>Settings</h2></div><button className="icon-control" onClick={onClose}><X size={16} /></button></header>
        <div className="settings-body">
          <nav>
            <button className={tab === "runtime" ? "active" : ""} onClick={() => setTab("runtime")}><Cpu size={14} />Models & Runtime</button>
            <button className={tab === "generation" ? "active" : ""} onClick={() => setTab("generation")}><SlidersHorizontal size={14} />Generation</button>
            <button className={tab === "context" ? "active" : ""} onClick={() => setTab("context")}><RefreshCcw size={14} />Context</button>
            <button className={tab === "storage" ? "active" : ""} onClick={() => setTab("storage")}><Database size={14} />Data & Storage</button>
          </nav>
          <section className="settings-panel">
            {tab === "runtime" && <>
              <PanelHeading title="Models & Runtime" description="The UI is TypeScript now; the model runtime remains local Python + LM Studio." />
              <label><span>LM Studio server</span><input value={config.server_url} onChange={(event) => patch("server_url", event.target.value)} /></label>
              <label><span>API token</span><input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={config.api_key_configured ? "Configured securely · optional override" : "Optional session token"} /></label>
              <button className="secondary-action wide" onClick={() => void refreshModels()} disabled={loadingModels}><RefreshCcw size={13} className={loadingModels ? "spin" : ""} />Refresh models</button>
              <label><span>Model</span><select value={config.model || ""} onChange={(event) => patch("model", event.target.value)}><option value="">Select model…</option>{models.map((model) => <option key={model.key} value={model.key}>{model.display_name || model.key}{model.loaded ? " · loaded" : ""}</option>)}{config.model && !models.some((model) => model.key === config.model) ? <option value={config.model}>{config.model}</option> : null}</select></label>
              <label><span>GPU offload <em>{Number(config.gpu_ratio || 0).toFixed(2)}</em></span><input type="range" min={0} max={1} step={0.05} value={config.gpu_ratio} onChange={(event) => patch("gpu_ratio", Number(event.target.value))} /></label>
              <label><span>Context length</span><input type="number" min={1024} step={1024} value={config.context_length} onChange={(event) => patch("context_length", Number(event.target.value))} /></label>
            </>}

            {tab === "generation" && <>
              <PanelHeading title="Generation" description="These values are sent through the existing PromptPayload contract." />
              <div className="settings-grid">
                <label><span>Input mode</span><select value={config.input_mode} onChange={(event) => patch("input_mode", event.target.value)}>{Object.entries(config.modes || { smart_hybrid: "Smart Hybrid", wcf: "WCF only", raw: "Raw only", wcf_raw: "WCF + Raw", aif_core: "AIF-Core" }).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
                <label><span>Reasoning</span><select value={config.reasoning} onChange={(event) => patch("reasoning", event.target.value)}>{(config.reasoning_modes || ["off", "on", "low", "medium", "high"]).map((value) => <option key={value}>{value}</option>)}</select></label>
                <NumberSetting label="Temperature" value={config.temperature} min={0} max={2} step={0.05} onChange={(value) => patch("temperature", value)} />
                <NumberSetting label="Top P" value={config.top_p} min={0} max={1} step={0.01} onChange={(value) => patch("top_p", value)} />
                <NumberSetting label="Top K" value={config.top_k} min={1} step={1} onChange={(value) => patch("top_k", value)} />
                <NumberSetting label="Min P" value={config.min_p} min={0} max={1} step={0.01} onChange={(value) => patch("min_p", value)} />
                <NumberSetting label="Repeat penalty" value={config.repeat_penalty} min={0.8} max={1.5} step={0.01} onChange={(value) => patch("repeat_penalty", value)} />
                <NumberSetting label="Visible output" value={config.visible_output_tokens} min={256} step={256} onChange={(value) => patch("visible_output_tokens", value)} />
                <NumberSetting label="Reasoning reserve" value={config.reasoning_reserve_tokens} min={0} step={256} onChange={(value) => patch("reasoning_reserve_tokens", value)} />
              </div>
            </>}

            {tab === "context" && <>
              <PanelHeading title="Context" description="Context is assembled by the Python memory, discovery, and workspace layers. The React UI only visualizes and requests it." />
              <label><span>Projection mode</span><select value={config.projection_mode} onChange={(event) => patch("projection_mode", event.target.value)}>{(config.projection_modes || ["off", "conservative", "balanced", "vivid"]).map((value) => <option key={value}>{value}</option>)}</select></label>
              <div className="settings-info"><strong>Context length</strong><span>{Number(config.context_length).toLocaleString()} tokens</span></div>
              <div className="settings-info"><strong>Output reservation</strong><span>{Number(config.visible_output_tokens + (config.reasoning === "off" ? 0 : config.reasoning_reserve_tokens)).toLocaleString()} tokens</span></div>
              <p className="settings-copy">Opening Library sheets is navigation only. Use explicit references from Chat to add them to a generation context.</p>
            </>}

            {tab === "storage" && <>
              <PanelHeading title="Data & Storage" description="Runtime databases, media, backups, and output remain owned by the backend." />
              <div className="settings-info"><strong>Frontend storage</strong><span>Only UI preferences and unsent recovery drafts</span></div>
              <div className="settings-info"><strong>Canonical storage</strong><span>Python WorkspaceStore / SQLite</span></div>
              <div className="settings-info"><strong>Native acceleration</strong><span>Rust adapter remains available</span></div>
              <p className="settings-copy">The TSX migration deliberately does not duplicate canonical state into browser storage. That would be convenient right until two sources of truth start fencing.</p>
              <section className="danger-zone">
                <div className="danger-zone-heading"><AlertTriangle size={15} /><div><strong>Danger zone</strong><span>These actions cannot be undone from the active database.</span></div></div>
                <div className="danger-action">
                  <div><strong>Reset database</strong><p>Remove projects, chats, Library/canon, memory, and discovery data. A timestamped recovery backup is kept.</p></div>
                  <button className="danger-button" onClick={() => setResetMode("database")}><RefreshCcw size={13} />Reset</button>
                </div>
                <div className="danger-action destructive">
                  <div><strong>Complete reset</strong><p>Also remove media, datasets, generated output, backups, and local UI state. Configuration and models are preserved.</p></div>
                  <button className="danger-button solid" onClick={() => setResetMode("complete")}><Trash2 size={13} />Delete all</button>
                </div>
              </section>
            </>}
          </section>
        </div>
        <footer><span>{status}</span><button className="primary-action small" onClick={() => void save()}><Save size={13} />Save settings</button></footer>
      </aside>
      {resetMode && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closeReset(); }}>
        <section className="modal reset-modal" role="dialog" aria-modal="true" aria-labelledby="reset-title">
          <button className="icon-control modal-close" onClick={closeReset} disabled={resetting}><X size={15} /></button>
          <AlertTriangle className="reset-warning-icon" size={24} />
          <h2 id="reset-title">{resetMode === "complete" ? "Completely reset Arline?" : "Reset the database?"}</h2>
          <p>{resetMode === "complete"
            ? "All canonical data, chats, media, exports, generated output, backups, and UI-local state will be permanently removed. Runtime configuration and installed models remain untouched."
            : "All canonical data, chats, memory, and discovery state will be removed. A recovery backup of each database will be created first."}</p>
          <label><span>Type <strong>{resetMode === "complete" ? "DELETE EVERYTHING" : "RESET DATABASE"}</strong> to continue</span><input autoFocus value={resetConfirmation} onChange={(event) => setResetConfirmation(event.target.value)} disabled={resetting} /></label>
          <div className="modal-actions">
            <button onClick={closeReset} disabled={resetting}>Cancel</button>
            <button className="danger-button solid" onClick={() => void performReset()} disabled={resetting || resetConfirmation !== (resetMode === "complete" ? "DELETE EVERYTHING" : "RESET DATABASE")}>
              {resetting ? <RefreshCcw className="spin" size={13} /> : <Trash2 size={13} />}{resetting ? "Resetting…" : "Confirm reset"}
            </button>
          </div>
        </section>
      </div>}
    </>
  );
}

function PanelHeading({ title, description }: { title: string; description: string }) {
  return <div className="settings-heading"><span className="eyebrow">Settings</span><h3>{title}</h3><p>{description}</p></div>;
}

function NumberSetting({ label, value, min, max, step, onChange }: { label: string; value: number; min?: number; max?: number; step?: number; onChange: (value: number) => void }) {
  return <label><span>{label}</span><input type="number" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} /></label>;
}
