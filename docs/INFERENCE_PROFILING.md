# Inference profiling contract

The first implementation slice of [the update roadmap](INFERENCE_UPDATE_CLUSTERS.md) adds request profiling and benchmark tooling to the existing Rust runtime. U1 itself does not change planning defaults, prompts, model settings, caching policy or provider selection. The subsequent [U2 routing slice](INFERENCE_U2_VALIDATION.md) adds opt-in deliberation modes and repairs the scoped workspace-context handoff.

## Response and persistence

Successful `/api/generate` responses and streaming `done` events contain `stats.inference`. The same final snapshot is stored in the turn's statistics and the analysis bundle. Stream cancellation retains a partial snapshot through the existing best-effort cancellation mechanism. Generation/provider preparation failures return the existing `detail` field plus `run_id` and profiled failure statistics; invalid requests may fail before a usable run exists.

The contract is versioned with `version: "1"`. The run identity is allocated before analysis, memory retrieval or deliberation. Timings use `std::time::Instant`; local durations serialize as integer milliseconds, with sub-millisecond measurements accumulated before rounding.

```json
{
  "version": "1",
  "run_id": "run-...",
  "durations_ms": {
    "analyze": 12,
    "memory_retrieval": 5,
    "deliberation": 0,
    "context_assembly": 1,
    "preparation": 18,
    "provider_capabilities": 2,
    "provider_request_first_text": 120,
    "provider_request_total": 1400,
    "provider_text_stream": 1280,
    "server_first_visible_text": null,
    "persistence": 4,
    "validation": 0,
    "memory_index": 2,
    "prefill": null,
    "decode": null,
    "total": 1450
  },
  "provider": {
    "input_tokens": null,
    "output_tokens": null,
    "reasoning_tokens": null,
    "ttft_ms": null,
    "output_tokens_per_sec": null,
    "model_load_ms": null,
    "call_count": 1,
    "calls": [{
      "input_tokens": null,
      "output_tokens": null,
      "reasoning_tokens": null,
      "ttft_ms": null,
      "output_tokens_per_sec": null,
      "model_load_ms": null,
      "app_timings_ms": {"first_text": 120, "total": 1400, "text_stream": 1280}
    }]
  },
  "metadata": {
    "backend": "lmstudio",
    "provider_call_scope": "writer"
  }
}
```

The numbers above illustrate field meanings; they are not benchmark results. The actual `calls` array contains one entry per observed writer request, with normalized optional provider statistics and `app_timings_ms.first_text`, `total` and `text_stream`.

## Timing boundaries

| Field | Measured boundary |
|---|---|
| `analyze` | Deterministic analysis and structured context construction |
| `memory_retrieval` | Awaited memory retrieval; null when that stage is disabled or unobserved |
| `deliberation` | Optional planning function, including a model request when enabled |
| `context_assembly` | Final input composition and history attachment |
| `preparation` | Inclusive preparation duration; overlaps the preceding four stages |
| `provider_capabilities` | Reasoning-capability resolution outside the writer request timer |
| `provider_request_first_text` | Writer request start to first non-empty provider text, including reasoning; available for a single writer call |
| `provider_request_total` | Writer request through response-stream completion, including network/parsing and any stream backpressure |
| `provider_text_stream` | First provider text through stream completion; this is not pure neural decode time |
| `server_first_visible_text` | Request entry to first emitted answer delta; null for the non-streaming endpoint |
| `persistence` | Observed primary turn/checkpoint and analysis writes; excludes final publication of telemetry itself |
| `validation` | Output quality-validation computation |
| `memory_index` | Completion-time memory refresh |
| `prefill`, `decode` | Unknown unless directly instrumented in a future provider contract; no subtraction-based estimates |
| `total` | Entry to the final measurement snapshot, before publishing that snapshot |

Do not sum these fields as disjoint durations. Preparation includes its component stages; streamed provider time can overlap persistence and client backpressure. Client network transfer, React rendering and button-to-visible-text latency are not measured by server instrumentation. The benchmark separately measures HTTP request through complete response-body parsing.

## Provider statistics

Normalization uses known native LM Studio fields, including `total_input_tokens`, `total_output_tokens`, `reasoning_output_tokens`, `time_to_first_token_seconds`, `tokens_per_second` and `model_load_time_seconds`, plus supported legacy/explicit-unit aliases. Seconds are converted to milliseconds. Missing, malformed, negative or non-finite values remain null. Provider TTFT is never replaced by an application timer.

Field references: [native REST Chat](https://beta.lmstudio.ai/docs/developer/rest/chat) and [legacy REST endpoints](https://lmstudio.ai/docs/developer/rest/endpoints).

For multi-beat generation, `provider.calls` preserves every writer call. Normalized run-level token/TTFT/throughput fields remain null instead of presenting the last beat as the whole run. Observed provider request totals and text-stream durations may be summed when every call reports them. Deliberation is measured separately and is not counted as a writer call.

The new telemetry namespace contains scalar run/model/sampling metadata and measurements. It does not copy story text, prompt text, model inputs, API keys, raw provider payloads or images. Existing application exports may already contain story/provider material; this feature does not change that existing export contract.

U2 adds scalar metadata `deliberation_requested_mode`, `deliberation_effective_mode`, `deliberation_route_reason`, `generation_task` and `preparation_fast_path`. The full versioned decision is returned and cached as `deliberation.routing` after writer-input composition. These diagnostics are not inserted into the writer prompt. Effective mode describes whether planning was requested by routing; `deliberation_status` records whether the existing planner produced model guidance, a fallback or a disabled result.

INF-09 additionally records scalar `output_budget_mode`. Resolved allocations and observed/estimated cutoff appear in `stats.output_budget` and adjacent statistics; see [the output-budget contract](INFERENCE_OUTPUT_BUDGET.md). Writer statistics retain unknown usage rather than inferring zero reasoning tokens. Beat statistics aggregate only fully observed token counts and retain per-call budget evidence.

## Benchmark and remaining gates

See [INFERENCE_BENCHMARK.md](INFERENCE_BENCHMARK.md) for the isolated six-workload runner and optional NVIDIA/model-residency snapshots. A snapshot is not a peak-VRAM measurement. Cold state requires an explicit operator attestation; the runner never unloads or resets the current model. Prefix-oriented request categories do not prove backend cache hits.

Planning defaults remain unchanged. Adaptive-routing default changes, cache reuse, batching, alternate providers and GPU tuning remain governed by their roadmap evidence/quality gates. The profiler and synthetic exploratory samples do not establish a speedup, production narrative quality or crash durability.
