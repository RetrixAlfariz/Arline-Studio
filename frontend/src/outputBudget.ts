import type { OutputBudgetMode, RuntimeConfig } from "./types";

export const OUTPUT_BUDGET_OPTIONS = [
  { value: "fixed", label: "Fixed", description: "Use the selected token allowance" },
  { value: "auto", label: "Auto by task", description: "Choose an allowance for the task" },
] as const;

function isOutputBudgetMode(value: unknown): value is OutputBudgetMode {
  return value === "fixed" || value === "auto";
}

export function resolveOutputBudgetMode(config: RuntimeConfig, overrides: Partial<RuntimeConfig> = {}): OutputBudgetMode {
  if (Object.prototype.hasOwnProperty.call(overrides, "output_budget_mode") && isOutputBudgetMode(overrides.output_budget_mode)) {
    return overrides.output_budget_mode;
  }
  return isOutputBudgetMode(config.output_budget_mode) ? config.output_budget_mode : "fixed";
}

export function withOutputBudgetMode(config: RuntimeConfig, mode: OutputBudgetMode): RuntimeConfig {
  return { ...config, output_budget_mode: mode };
}

export function withResponseLength(config: RuntimeConfig, tokens: number): RuntimeConfig {
  const next = { ...config, output_budget_mode: "fixed" as const, visible_output_tokens: tokens };
  if (config.generation_mode === "beats") {
    next.beat_tokens = tokens;
    next.total_story_target_tokens = Number(config.beat_count || 4) * tokens;
  }
  return next;
}
