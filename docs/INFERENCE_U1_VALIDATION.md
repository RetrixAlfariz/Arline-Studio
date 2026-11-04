# U1 implementation validation — 23 October 2026

The first roadmap slice adds monotonic generation-stage timing, request identity before preparation, optional provider-stat normalization and isolated benchmark tooling. Generation prompts, planning defaults and provider/GPU policies remain unchanged. Later U2–U7 behavior changes are not implemented by this slice.

## Automated checks

- Desktop-featured crate suite: **146 passed, 0 failed**.
- Benchmark example unit tests: **3 passed, 0 failed**.
- Desktop-featured Clippy across all targets with `-D warnings`: passed.
- Generation HTTP checks include progressive streaming, cancellation snapshots, terminal-only provider output, normalized/unknown metrics, consistent persisted snapshots, beat-call accounting and profiled provider failures.

Commands from the repository root:

```powershell
cargo test --locked --offline --features desktop --manifest-path crates/arline-runtime/Cargo.toml --target-dir .codex-audit/native-target2 --tests
cargo test --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --example inference_benchmark
cargo clippy --locked --offline --features desktop --all-targets --manifest-path crates/arline-runtime/Cargo.toml --target-dir .codex-audit/native-target2 -- -D warnings
```

Raw test and benchmark evidence is retained in `.codex-audit/inference-u1-20261023/`.

## Local exploratory observations

Environment: existing LM Studio instance; `qwen3.5-4b-uncensored-hauhaucs-aggressive` already loaded; RTX 5060 Ti with 16,311 MiB total device memory. The provider reported an active 32,768-token instance context, Flash Attention and GPU KV offload. Backend version and exact quantization were not established by the exposed metadata. No model load/unload or GPU setting changes were performed.

Each accepted sample used fresh temporary application storage and a fixed synthetic writer contract. Neural reasoning was off, temperature 0.2, and the writer budget was 96 tokens per call; the three-beat workload made three calls. This is a bounded tool-validation corpus, not a production narrative-quality benchmark. Prefix/cache state was not reset and backend cache hits were not observable.

| Run | Samples | Errors | Median HTTP duration | Interpretation |
|---|---:|---:|---:|---|
| Six workloads, two repetitions, forward/reverse order | 12 | 0 | 1,377 ms | Mixed workload exploratory summary; raw per-workload values are retained |
| Identical short-prefix requests | 2 | 0 | 1,272 ms | Request-shape check; output counts differed (90/96), so no cache speedup inference |
| Short request with deliberation enabled | 2 | 0 | 7,456 ms | Planning returned model-generated structured guidance in both samples |

The first run's descriptive p95 was 3,812 ms. Two observations per workload do not establish stable tail latency. Its successful single-call provider throughput reports ranged approximately 81–90 tokens/s; multi-beat throughput remains per-call instead of inventing a run aggregate.

For the short request, the two planning-enabled samples spent 5,614 and 6,408 ms in deliberation. The corresponding planning-disabled samples in the six-workload run completed in 1,371 and 1,383 ms, also producing 96 writer tokens each. This identifies a useful next routing experiment; it does not establish that disabling planning preserves narrative quality, and no routing default was changed.

Primary persistence measured approximately 10–12 ms per accepted sample. This small synthetic corpus does not justify prioritizing a batching refactor. Long-context provider TTFT varied substantially, including approximately 46 ms and 2,090 ms for the two long-context observations; cache reuse remains unknown.

Reports:

- `warm-dynamic-isolated.json`: accepted 12-sample exploratory corpus.
- `warm-prefix-isolated.json`: two identical-prefix requests.
- `planning-on-isolated.json`: two planning-enabled requests.
- `warm-dynamic.json`: preserved earlier exploratory run using shared temporary application state. It is excluded from the accepted baseline because earlier outputs could enter later memory retrieval.

## Remaining gates

Cold-model timing, actual browser/render TTFT, peak/process VRAM, confirmed prefix/KV hits and comparative narrative quality were not validated. A device snapshot is not a peak memory trace. No inference speedup or production quality improvement is claimed.

The next performance decision should compare adaptive deliberation on the same task classes while retaining explicit overrides and checking continuity/POV/Canon quality. Cache, persistence and GPU changes retain their separate roadmap gates.
