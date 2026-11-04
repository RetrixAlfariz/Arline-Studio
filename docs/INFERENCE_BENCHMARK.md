# Inference benchmark

`crates/arline-runtime/examples/inference_benchmark.rs` runs a bounded, reproducible benchmark through the local Arline HTTP router and a temporary SQLite workspace. It sends requests to the configured provider URL, records latency, output length, response `stats` (including arbitrary `stats.inference` when present), and reports unknown values explicitly. The benchmark does not load, unload, reset, or infer cache hits, and its timing output is not a speedup claim or a human-quality score.

The six synthetic workloads are stored in `crates/arline-runtime/tests/fixtures/inference_workloads.json`. Prompts and generated story text are never copied into the report; only workload IDs and measurements are retained. Requests alternate forward and reverse workload order across repetitions. `warm-prefix` repeats a stable prompt eligible for prefix reuse; `warm-dynamic` adds a synthetic per-repetition variation. These labels describe the request design, not verified provider cache behavior.

Examples:

```text
cargo run --example inference_benchmark --manifest-path crates/arline-runtime/Cargo.toml -- --dry-run --model my-model --category warm-prefix --repeats 2
cargo run --example inference_benchmark --manifest-path crates/arline-runtime/Cargo.toml -- --dry-run --model my-model --workload canon-short --temperature 0.2 --output-budget 256
cargo run --example inference_benchmark --manifest-path crates/arline-runtime/Cargo.toml -- --dry-run --model my-model --workload dialogue --output-budget-mode auto
cargo run --example inference_benchmark --manifest-path crates/arline-runtime/Cargo.toml -- --dry-run --model my-model --workload dialogue --output-budget-mode auto --output-budget 384
cargo run --example inference_benchmark --manifest-path crates/arline-runtime/Cargo.toml -- --model my-model --category warm-dynamic --repeats 3 --out inference-report.json --revision unknown
cargo run --example inference_benchmark --manifest-path crates/arline-runtime/Cargo.toml -- --model my-model --category cold-model --workload canon-short --cold-attestation operator-confirmed --repeats 1
```

`--out` uses create-new semantics and refuses to overwrite an existing file. `--provider-url` defaults to `http://127.0.0.1:1234`. `--repeats` is bounded to 1–100. `--dry-run` validates arguments and the corpus, prints the manifest, and never contacts the provider. NVIDIA telemetry is best effort through a read-only, bounded `nvidia-smi` query; absence is reported as `unavailable`.

`--workload` selects one corpus ID for a small smoke run. `--temperature` and `--output-budget-mode` are retained in the report environment. `fixed` is the compatibility default and emits a visible/max budget of `--output-budget`, or 256 when omitted. `auto` leaves visible/max budget fields absent so task-aware routing can choose an allowance; adding `--output-budget` is an explicit numeric override. The dialogue workload is a short static prompt (under 80 words), so its task-aware floor is expected to remain in the short-response class; this is a routing expectation, not a quality or latency claim. Seed control is currently reported as unsupported/unknown because the runtime does not forward a seed contract. The report also provides derived medians from known `stats.inference` paths; missing telemetry and cutoff detection are serialized as `null`/`unsupported_unknown`, never as zero.

`cold-model` requires exactly one `--workload`, `--repeats 1`, and a `--cold-attestation` description. The report records this as `attested_not_independently_verified`; the benchmark never resets or unloads a model.

Each sample gets a fresh temporary AppState, SQLite store, and loopback router; setup is outside the latency timer. The provider process remains external and resident between samples. This prevents prior generated turns from contaminating preparation or prefix comparisons, and is recorded as `application_state: fresh_per_sample`. The `--deliberation on|off|auto|fast|deep` field controls orchestration planning; neural reasoning remains `off`. The default remains `off`. See [the adaptive-routing contract](INFERENCE_U2_VALIDATION.md) for mode precedence and task rules. Reports retain the actual route in `stats.inference.metadata`, including cases where an explicit author command requires planning in `fast` mode.

The `multi-beat` workload uses three runtime beats; its output budget is per beat, so the provider receives three calls. The `continuation` workload seeds a synthetic prior turn in the temporary store before requesting continuation. `canon-long` expands a fixed synthetic context into a deterministic context of at least 1,500 words.

The report includes `median_latency_ms`, `p95_latency_ms`, and sample/error counts. `environment.runtime_config` records `output_budget_requested` and `output_budget_effective`; fixed mode reports the 256 fallback, while auto mode reports `null` unless an explicit numeric override was supplied. Auto mode's `null` means consumers should inspect each sample's `stats.output_budget` when the runtime reports one. Cutoff detection is reported as `per_sample_stats_unknown_when_unreported`: an observed `output_cutoff` remains in the raw sample stats, while missing provider stop information stays unknown; `likely_output_budget_cutoff` is a separate estimate. Both modes keep `reasoning: off` and `reasoning_reserve_tokens: 0`. If telemetry is absent, its value remains `null` or the raw stats object is empty; consumers must preserve that unknown state rather than treating it as zero.
