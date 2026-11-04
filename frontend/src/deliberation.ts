import type { DeliberationMode, RuntimeConfig } from "./types";

export const DELIBERATION_MODES = ["off", "auto", "fast", "deep"] as const;
export type DeliberationSelectorMode = Exclude<DeliberationMode, "on">;

function isDeliberationMode(value: unknown): value is DeliberationMode {
  return value === "on" || value === "off" || value === "auto" || value === "fast" || value === "deep";
}

/** Resolve an outgoing mode, keeping explicit request overrides ahead of saved config. */
export function resolveDeliberationMode(config: RuntimeConfig, overrides: Partial<RuntimeConfig> = {}): DeliberationMode {
  if (Object.prototype.hasOwnProperty.call(overrides, "deliberation_mode") && isDeliberationMode(overrides.deliberation_mode)) {
    return overrides.deliberation_mode;
  }
  if (Object.prototype.hasOwnProperty.call(overrides, "planning_enabled") && typeof overrides.planning_enabled === "boolean") {
    return overrides.planning_enabled ? "on" : "off";
  }
  if (isDeliberationMode(config.deliberation_mode)) return config.deliberation_mode;
  return config.planning_enabled === true ? "on" : "off";
}

/** The four-value UI intentionally presents legacy `on` as the closest `deep` choice. */
export function deliberationSelectorMode(config: RuntimeConfig): DeliberationSelectorMode {
  const mode = resolveDeliberationMode(config);
  return mode === "on" ? "deep" : mode;
}

/** Update both fields while retaining compatibility with older backend config readers. */
export function withDeliberationMode(config: RuntimeConfig, mode: DeliberationSelectorMode): RuntimeConfig {
  return { ...config, deliberation_mode: mode, planning_enabled: mode === "auto" || mode === "deep" };
}
