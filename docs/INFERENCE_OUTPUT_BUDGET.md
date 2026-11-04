# Output budget optimization — INF-09

Implemented by Opheline · 23 October 2026 · Local changes

INF-09 adds one budget resolver for single, stream, beat and planner requests. It preserves the Fixed default and explicit numeric controls. INF-10 retry deduplication and INF-14 final-input token budgeting remain separate work. See [the roadmap](INFERENCE_UPDATE_CLUSTERS.md) and [INF-06/07 routing](INFERENCE_U2_VALIDATION.md).

## User controls and precedence

`output_budget_mode` accepts `fixed` or `auto`. Request mode takes precedence over saved `generation.output_budget_mode`; absence falls back to Fixed. Null means unspecified. Settings accepts flat `output_budget_mode` and persists the nested configuration value.

Settings → Generation and Chat → Run settings expose **Fixed / Auto by task**. Selecting a numeric response length switches to Fixed. In beat mode, that control also updates the per-beat allowance and corresponding total target. Auto requests omit fixed visible/per-beat/total values unless an explicit request override supplies them. Reasoning mode, reasoning reserve and beat count retain their independent controls. The API configuration's `api_max_output_tokens` remains a nominal configured Fixed allowance; actual per-run values are in statistics.

For a single response, an explicit positive `visible_output_tokens` wins over the task recommendation or configured Fixed target. A positive `max_output_tokens` overrides the combined provider cap, including when it is smaller than the desired visible target. This shortfall is reported as `visible_target_exceeds_cap`; the resolver does not enlarge or silently discard that explicit cap. Spare cap above visible target plus requested reserve is recorded as unallocated, rather than mislabeled as reasoning reserve.

Budget fields require signed-64-bit-range integers. Visible, per-beat, total, planner and provider caps must be positive; reasoning reserve may be zero. Beat count is 1–24. Overflowing combined/run totals are rejected before planner or writer calls. Invalid budget requests return HTTP 400. The frozen legacy schema is retained, with only the generation budget fields delegated to the new resolver; unrelated request validation remains intact.

## Auto recommendations

These are conservative application allowances, not a guarantee of output length or quality. Explicit numeric targets remain authoritative, including targets below the recommendation.

| Derived task | Default visible allowance |
|---|---:|
| Short continuation | 512 |
| Dialogue, recognized by structured command profile | 768 |
| Deep scene | 4096 |
| Alternatives, author intuition, continuity review | 1536 |
| Story Lab | 2048 |
| Beats | 1024 per beat |

Task classification reuses INF-06/07's deterministic routing result; an arbitrary request `task` string cannot override it. A short natural-language dialogue prompt may therefore remain `short_continue` unless a structured dialogue profile is present.

Auto recognizes whitespace-separated integer counts before `word/words/kata/token/tokens`, including ranges and conventional comma thousands separators. Word requests receive a conservative allowance of `3 × upper word count + 256`; token requests retain their count as a minimum. Auto uses the larger of this allowance and the task recommendation. For beats, a word/token hint applies to the whole story rather than every beat. Recognized long-form terms (`chapter`, `novel`, `long`, `panjang`, `bab`) retain at least 4096 tokens or the larger configured visible allowance. This limited parser does not understand every phrasing or language and does not replace tokenizer-based context-window accounting. Explicit numeric targets bypass hint-based recommendations.

## Reasoning, beats and planning

LM Studio receives one `max_output_tokens` generation cap and reports total and reasoning usage separately. The application's visible/reserve allocation is not a provider-enforced partition; reasoning can consume space intended for visible output. [LM Studio native Chat contract](https://lmstudio.ai/docs/developer/rest/chat).

Reasoning off uses zero active reserve. When enabled and supported by the existing model-capability checks, the nominal combined cap is visible target plus reserve. An explicit smaller cap reduces available reserve after the visible allowance; metadata retains the requested reserve and target shortfall. An explicit larger cap does not inflate reserve. No unsupported reasoning setting is enabled by this feature.

For beats, precedence is explicit `total_story_target_tokens`, then explicit `beat_tokens` (or visible target as a per-beat fallback), then Auto's recommendation or saved Fixed total/per-beat configuration. If both total and per-beat values are supplied, the explicit total controls the split. A total of 10 across three beats yields visible allowances **4, 3, 3**, without the previous silent 256-token floor. A total smaller than the number of beats is rejected. Fixed configuration uses its saved total when present; otherwise it uses count × saved per-beat allowance.

`max_output_tokens` remains a **per writer call** override in beat mode. Reasoning reserve is also per call. For the 10-token example with reserve 4 and reasoning enabled, combined caps are **8, 7, 7**; aggregate visible target is 10, reserve 12 and API allowance 22. `generation.total_budget` retains its visible-target meaning. Per-call statistics and aggregate API/reserve budgets are separate, and unknown usage in any call prevents a fabricated whole-run token count. Failed middle beats persist the completed prefix and its call statistics; planned total and completed-beat count remain explicit.

The planner has an independent limit: request `deliberation_max_tokens`, then configuration `deliberation.max_tokens` (default 700). Auto can reduce a short/dialogue planner allowance to 512, bounded by the configured planner limit; other tasks use up to 700. Writer caps and word-count hints never become planner caps. Explicit planner/configuration limits are honored without the old hidden 128–4096 clamp. Existing planner failure/non-JSON fallback remains available. Planner usage diagnostics are removed before writer-input composition, then attached to the response/cache.

## Reporting and cutoff

`stats.output_budget` version `1` records mode, task, source, scope, visible target/allowance, requested/active reserve, provider cap, unallocated space and target shortfall. Existing `visible_output_target_tokens`, `api_max_output_tokens` and `reasoning_reserve_tokens` aliases use the same resolved object as the provider request. Beats retain `generation.beats[].stats` and a run-level aggregate. Planner budget/usage lives in `deliberation.output_budget`. `stats.inference.metadata.output_budget_mode` adds scalar correlation.

`output_cutoff` is true only for a recognized provider token-limit stop reason, false for a recognized normal stop, and null when unavailable. Recognized shapes include top-level stop/finish reason, statistics stop/finish reason and OpenAI choice finish reason. `likely_output_budget_cutoff` is a separate estimate when reported total usage reaches 98.5% of the cap. Token counts and ratios remain null when their required usage is absent; missing reasoning usage is not treated as zero. The Chat draft shows a definite token-limit notice or an explicitly uncertain allowance notice; a reported normal stop suppresses the estimate notice.

Cancellation and transport errors preserve resolved budget information while leaving unreported usage/cutoff unknown. This feature does not add automatic retries, continuation calls, or a new completion/durability policy.

## Validation and observations

- **174 desktop runtime tests + 3 benchmark tests passed**, including 77 library tests, eight dedicated budget HTTP tests and the existing generation/planning/scope suites.
- Desktop all-targets Clippy with `-D warnings`, Rust formatting and frontend typecheck passed.
- A direct execution of the actual frontend `runtimePayload` verifies Fixed defaults, Auto omission of fixed numbers, explicit numeric caps, unchanged reasoning controls and synchronized beat lengths; the reproducible check is retained as `frontend-payload-check.mjs` in the local evidence directory.
- Dedicated cases verify single/stream parity, numeric precedence, larger/smaller caps, null/invalid/overflow inputs, exact beat arithmetic, missing usage, reported cutoff, planner separation and absence of budget diagnostics in writer input. Settings tests cover persistence/reload and rejection without file writes. Cancellation and failed-middle-beat assertions verify persisted budgets.
- The benchmark supports `--output-budget-mode fixed|auto`; [usage](INFERENCE_BENCHMARK.md) explains explicit overrides and per-sample evidence.
- Browser interaction QA was unavailable: automatic approval review rejected starting the isolated backend/preview helpers as background processes with `blocked by policy`. No helpers were started. Frontend checks establish types/serialization, not rendered interaction or visual behavior.

Four foreground benchmark samples used the already resident local `qwen3.5-4b-uncensored-hauhaucs-aggressive` model, the fixed `dialogue` corpus prompt, warm-prefix category, temperature 0, planning off, reasoning off and fresh temporary storage per sample. Fixed explicitly selected 512; Auto independently selected 512 from the derived short-continuation task. Mode order was Fixed → Auto → Auto → Fixed.

| Mode | Samples | Actual visible tokens per sample | Cap | Server total (ms) |
|---|---:|---:|---:|---|
| Fixed | 2 | 148, 148 | 512 | 1924, 1845 |
| Auto | 2 | 148, 148 | 512 | 1859, 1841 |

Reported reasoning usage was zero in all four samples; no sample was near its cap and native stop reasons were unreported, so observed cutoff remains unknown. These samples control actual output length as well as the cap. They do not establish a speedup, narrative-quality equivalence, provider cache hits or general performance improvement. The runner does not retain story text, so equal token counts are not evidence of identical text. Two earlier pilot samples with different caps are retained separately and excluded from this comparison. Model loading, unloading and GPU settings were unchanged.

Raw reports, original failed checks, final logs, and the comparison summary are retained in `.codex-audit/inference-u2-inf09-20261023/`. The local APORIA review case is `.codex-audit/aporia/inference-output-budget/`; it records the static baseline failure, implementation evidence and remaining browser-QA limitation.

```powershell
cargo test --locked --offline --features desktop --manifest-path crates/arline-runtime/Cargo.toml --target-dir .codex-audit/native-target2 --tests --example inference_benchmark
cargo clippy --locked --offline --features desktop --all-targets --manifest-path crates/arline-runtime/Cargo.toml --target-dir .codex-audit/native-target2 -- -D warnings
npm --prefix frontend run typecheck -- --pretty false
```
