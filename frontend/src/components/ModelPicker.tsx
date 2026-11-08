import { useCallback, useEffect, useState } from "react";
import { ArlineSelect } from "./ArlineSelect";
import { studioApi } from "../api";
import type { ModelInfo, RuntimeConfig } from "../types";

interface ModelPickerProps {
  config: RuntimeConfig;
  onConfig: (config: RuntimeConfig) => void;
  /** Block switching while a generation streams: a reload would cut it off. */
  disabled?: boolean;
}

/** Pick a local model; choosing one loads it and makes it the saved default. */
export function ModelPicker({ config, onConfig, disabled = false }: ModelPickerProps) {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(
    () => studioApi.models(config.server_url).then((result) => setModels(result.models || [])).catch(() => setModels([])),
    [config.server_url],
  );
  useEffect(() => { void refresh(); }, [refresh, config.inference_engine, config.models_dir]);

  const choose = async (model: string) => {
    if (!model || (model === config.model && models.some((item) => item.key === model && item.loaded))) return;
    onConfig({ ...config, model });
    setLoading(model);
    setError("");
    try {
      await studioApi.reloadModel({ server_url: config.server_url, model, gpu_ratio: config.gpu_ratio, context_length: config.context_length });
      await studioApi.saveSettings({ model });
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setLoading("");
      void refresh();
    }
  };

  const loaded = models.some((item) => item.key === config.model && item.loaded);
  const options = models.map((item) => ({
    value: item.key,
    label: item.display_name || item.key,
    description: item.loaded ? "Loaded · ready" : "Select to load",
  }));
  if (config.model && !models.some((item) => item.key === config.model)) {
    options.push({ value: config.model, label: config.model, description: "Configured model (not found locally)" });
  }

  return (
    <div className="model-picker" title={error || undefined}>
      <span className={`model-status ${loaded && !loading ? "online" : ""} ${loading ? "busy" : ""}`} aria-hidden="true" />
      <ArlineSelect
        ariaLabel="Model"
        density="compact"
        value={config.model || ""}
        placeholder={models.length ? "Select a model…" : "No local models found"}
        options={options}
        onValueChange={(model) => void choose(model)}
        disabled={disabled || Boolean(loading)}
        menuMinWidth={340}
      />
      <small role="status">{loading ? "Loading…" : error ? "Load failed" : loaded ? "Ready" : config.model ? "Not loaded" : ""}</small>
    </div>
  );
}
