# R5 — Narrative retrieval quality and release qualification

Opheline · 7 November 2026 · `codex/retrieval-r5-qualification`

## Scope and decision

This execution starts with **R5A only**, as requested. Ranking weights, thresholds, production configuration, context-counter architecture and retrieval defaults remain unchanged. R5B–D are gated on the evaluation evidence and review; this document must not be read as a completed release qualification.

The pre-R5 checkpoint preserves all 60 changed/untracked R0–R4 files, HEAD and binary diff in `.codex-audit/retrieval-r5-20261107/pre-r5-checkpoint.zip`. Existing database backups are preserved. No live user narrative database is opened, edited or indexed: evaluation uses disposable, newly initialized stores containing authored fictional narratives only. No model/package download, commit, push, merge, deployment or default-engine change is authorized or performed.

## Evaluation protocol, fixed before measurement

Development and held-out narratives are separately authored. Held-out authorship does not inspect development narratives or ranking outcomes. Both splits receive independent agent review against the source text before final freeze. Agent review is **not human judgement**. Premeasurement corrections retain a record of rejected versions and reasons; no query, label or threshold changes are permitted after seeing that split's baseline results without declaring a new evaluation version.

An initially submitted held-out draft was rejected before measurement: repeated generic filler and unsupported answers made its word count misleading. The rejected artifact and its review remain in ignored audit evidence. Its 9,913 words and 24 labels are not qualified evaluation evidence. The replacement must pass prose/label review and a deterministic eligibility oracle before any scored run.

The development story follows custody receipts, two people sharing a name, a temporary injury and recovery, unsupported accusations, an author's private proposal, and divergent/nested routes. The held-out story is independently authored. Existing frozen R0–R3 fixtures are unchanged. These are original synthetic manuscripts, not authorized copies of users' manuscripts. Long-form representativeness and literary quality remain limitations even when source facts are verifiable.

Frozen controls:

- Four baseline arms: existing safe legacy, existing scope-aware lexical/structured retrieval, diagnostic Bekko cosine extraction, and existing hybrid RRF. No alternative rankers or tuning in R5A.
- Every arm uses the same query/scope, 10 selected chunks, one chunk per source, and 4,096 estimated passage tokens. Canon, lineage, lifecycle, time and POV gates remain production-owned. An independent source-level fixture oracle checks observed selections against labels and branch inheritance.
- Diagnostic Bekko candidates come from the already eligible hybrid result pool, sorted by cosine with stable chunk-ID ties and the same final packing controls. This is not an independently deployed semantic engine or isolated cosine-latency measurement. Candidate discovery differs across baseline arms; identical candidate-pool ranker experiments belong to R5B.
- Source-level deduplication precedes Recall@5/@10, MRR@10 and binary nDCG@10. Multiple chunks of one source cannot inflate recall. No-answer queries have null relevance metrics and separately measured retrieval abstention.
- Forbidden evidence means an authorization/lifecycle failure. Historical statements that were once true are not automatically forbidden or unsupported; query-specific superseded-state distractors are recorded separately. An unrelated selected source is unjudged/relevance noise, not automatically a fabricated claim.
- Exact-name outcomes apply only to prelabelled exact-name cases. Current-state retrieval is measured as retrieval of the adjudicated applicable source, not as proof of generated factual accuracy. Contradictory-source selection is measured separately.
- Three timed repetitions follow one warm-up per query/arm in release mode. Aggregate quality uses one result per unique query; latency uses all repetitions. Determinism compares source-ID order across repetitions. Report percentiles with nearest-rank p95/p99 and sample counts; do not mix debug R0, R3 synthetic or R4 compiler figures.
- Controlled degradation runs after the complete baseline: half the vectors removed, then a source edited without projection refresh, then the provider path made unavailable. These scenarios are cumulative and reported separately, not pooled with primary relevance.
- Six `continuity_probe` query IDs per split are fixed before results. Legacy, scope-FTS and hybrid supply selected evidence to the existing R4 compiler, identical mandatory Canon, writer, output reserve and deterministic generation settings. The diagnostic semantic arm is not a writer mode. Scene probes are two-to-four sentences, with explicit permission to abstain; they are not long-form writing-quality qualification.
- Generated probes are scored independently with arm identities hidden. Reviewers inspect source facts, evidence actually retained after compilation, chronology, Canon and unsupported claims. Machine checks and independent-agent judgements must be labelled separately from Vian's or another human's judgement. Human review is a required gate, not inferred from model agreement.

Zero observed authorization/Canon violations is a correctness requirement. Ranking improvement is not declared from a single aggregate without exact-name/current-state/temporal and no-answer breakdowns. No production performance gate is invented from these small workloads; R5D must predeclare numerical hardware/workload targets before any performance optimization.

## Measurements and review

The following are final R5A baseline observations, not release approval. All held-out labels were frozen before its first scored run, and no ranker, weight or threshold changed after results.

| Split | Narrative | Documents / projected chunks | Words | Queries / answerable / no-answer | Scene probes per writer arm |
|---|---|---:|---:|---:|---:|
| Development | The Sluice Receipts | 18 / 19 | 3206 | 20 / 17 / 3 | 6 |
| Held-out | Veyra lighthouse narrative | 25 / 26 | 4796 | 24 / 22 / 2 | 6 |

The projected counts include the registered viewpoint entity; one superseded narrative draft remains retained but ineligible. Query-level source labels include aliases, ambiguous names, possession transfers, injury/recovery, current/historical location, sibling negation, corrections, two branch levels, private author knowledge and unsupported answers. Development has two Indonesian scenes; held-out includes Indonesian queries over English evidence. This is narrow multilingual coverage, not language-wide qualification.

Final SHA-256:

- Development: `f10daedcddd27c26c5bce1b5384f4a1560ec51e318df64b1228a821e6e594cb7`.
- Held-out: `1c336960a5b5c5d2dd062ecf63f84f787465ec254c599b709ebb4be15d022102`.

Independent agent review inspected all 43 source documents and all 44 labels; final reviews and the deterministic validator pass. Human label/continuity judgement remains pending. The held-out set is independent in authorship and freezing, but its relatively literal, mostly single-source questions produce a Recall@5 ceiling. Two authored stories cannot establish real-manuscript generalization.

### Setup audit and invalid attempts

Two preliminary development runs (`development-baseline.json` and `development-baseline-corrected.json`) are **invalid**, preserved only as diagnostic history. R2 explicit maintenance and queued workspace change notifications reset evaluation-only scope annotations. The final harness drains notifications before indexing, applies annotations afterward, and verifies them after every query warm-up. Any oracle violation blocks that writer probe without filtering or hiding the measured retrieval failure. Both final runs have zero observed violations and no refused probes.

These were fixture-setup errors, not demonstrated production gate failures. No ranking or narrative labels were changed in response to those scores. All earlier scene packets are invalid and excluded from adjudication. The final packets explicitly contain the query scope, actual retained evidence, request hash and matching gold facts; arm identities alone are blinded.

Workspace document rows have no native temporal/private-knowledge columns. The harness explicitly annotates derived projections for these tests; it does not forge vectors, revisions or checksums. This proves behavior **given those annotations**, not automatic interpretation or durable storage of manuscript chronology/secrecy. Arbitrary source edits can rebuild such projections, and production ingestion/authoritative metadata support must be qualified before claiming equivalent real-manuscript safety. Only one generic POV and all-POV author-only exclusion are represented; selective knowledge sharing and evolving epistemic states remain gaps.

### Retrieval relevance

Binary source-level averages exclude no-answer queries. Repeated chunks do not increase credit; each query contributes once.

| Split / arm | Recall@5 | Recall@10 | MRR@10 | nDCG@10 |
|---|---:|---:|---:|---:|
| Development / legacy | 0.529 | 0.765 | 0.373 | 0.465 |
| Development / scope FTS | 0.941 | 0.941 | 0.814 | 0.847 |
| Development / diagnostic Bekko | 1.000 | 1.000 | 0.941 | 0.957 |
| Development / hybrid RRF | 1.000 | 1.000 | 0.873 | 0.905 |
| Held-out / legacy | 1.000 | 1.000 | 0.811 | 0.860 |
| Held-out / scope FTS | 1.000 | 1.000 | 0.865 | 0.899 |
| Held-out / diagnostic Bekko | 1.000 | 1.000 | 0.864 | 0.898 |
| Held-out / hybrid RRF | 1.000 | 1.000 | 0.856 | 0.893 |

The R3 finding is not universal: Bekko leads development, while scope FTS narrowly leads this held-out story. Hybrid's held-out nDCG delta versus legacy is +0.03355. A descriptive paired query bootstrap (22 answerable queries, 10,000 resamples, seed 51937) gives a 95% interval **[-0.08983, +0.15693]**; it does not establish a reliable improvement. Scope FTS minus hybrid is +0.00568, interval [-0.05655, +0.07279]. These within-story intervals do not quantify manuscript-level generalization. No winning ranker is selected in R5A.

| Breakdown | Development legacy / FTS / Bekko / hybrid | Held-out legacy / FTS / Bekko / hybrid |
|---|---|---|
| Exact-name Recall@5 (2 / 3 cases) | 0 / 1 / 1 / 1 | 1 / 1 / 1 / 1 |
| Applicable current-state source Recall@5 (4 / 2 cases) | 0.75 / 1 / 1 / 1 | 1 / 1 / 1 / 1 |
| Temporal/branch evidence Recall@5 (6 / 3 cases) | 0.833 / 0.833 / 1 / 1 | 1 / 1 / 1 / 1 |
| No-answer retrieval abstention (3 / 2 cases) | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Query-specific superseded-state distractor selections | 5 / 4 / 5 / 5 | 0 / 0 / 0 / 0 |

All arms have **zero observed branch/POV/time/lifecycle oracle violations** and zero explicitly forbidden source selections in both final complete runs. All source-ID orders are stable across three repetitions. This does not mean every historical statement is the applicable current answer: old-but-eligible state distractors survive, as the separate count shows. Unjudged sources are reported as relevance noise, not automatically fabricated evidence. Unsupported *generated claims* require adjudication below.

The fixed planner reports 18/20 development hybrid requests as `historical`, one as relationship and one as POV knowledge. A story-order cutoff takes precedence over current-state wording in the existing intent planner. That is a concrete R5B investigation candidate; it has not been changed or tuned here.

### Actual generated continuity

The already provisioned `qwen3.5-4b-uncensored-hauhaucs-aggressive` writer was explicitly loaded under a task-owned ID with an **8192 loaded window**. No weights/packages were downloaded. There are 36 real LM Studio scene probes: six fixed queries × three production retrieval arms × two splits. The probes use the existing R4 compiler and selected-only evidence, a constant 256-token output cap, requested reasoning off/temperature zero, and no planner. They bypass full analysis/orchestration deliberately to isolate retrieval-to-compiler-to-writer behavior. They do **not** newly qualify full normal/stream/beat API preparation or bitwise writer determinism.

All 36 actual input-token counts remained under the native compiler bound. Native bounds were 6397–7522 development and 6678–7406 held-out, while actual inputs were roughly 1442–1794 tokens. All required Canon strings remained in compiled input. Optional evidence retained four or five items on these probes. The gold source survived 7/8 answerable legacy probes and 8/8 scope-FTS/hybrid probes. This illustrates conservative under-utilization and a lost legacy recovery source; it does not authorize a counter change before R5C.

Independent arm-blinded **agent** review found material factual and continuity failures. The reviewer sees gold and retained evidence, not arm names; this is not human review. Six scenes per arm/split are a small diagnostic sample, not a statistically qualified writing-quality comparison.

| Split / arm | Factual passes | Continuity passes | No-answer abstention | Scenes with consequential unsupported claims |
|---|---:|---:|---:|---:|
| Development / legacy | 3/6 | 3/6 | 1/2 | 3/6 |
| Development / scope FTS | 4/6 | 5/6 | 1/2 | 2/6 |
| Development / hybrid | 3/6 | 4/6 | 1/2 | 3/6 |
| Held-out / legacy | 5/6 | 6/6 | 2/2 | 1/6 |
| Held-out / scope FTS | 3/6 | 5/6 | 2/2 | 3/6 |
| Held-out / hybrid | 3/6 | 5/6 | 2/2 | 3/6 |

Examples include inventing that the POV character knew a concealed sale order, assigning the nested-route key to the wrong custodian, and transferring a key to Sora instead of Mara. **Zero unauthorized retrieved evidence did not prevent fabricated private knowledge or wrong-state synthesis.** A query can introduce a private topic without authorizing the character to know it. High retrieval relevance is therefore insufficient for the release gate.

The original agent rubric's `canon_preserved` field broadly includes story/scope constraints and must not be equated with fidelity to persisted Canon. A separate explicit mandatory-Canon audit passed 17/18 development and 18/18 held-out scenes (35/36 total). It flagged a scope-FTS scene assigning Sami a belief that the silver whistle could unlock the cabinet, inconsistent with the fixed key/whistle distinction and his established knowledge. That additional flag was missed by the initial factual rubric, so the table above preserves the original judgements rather than concealing the disagreement; factual pass counts are provisional pending human adjudication. There was no Canon CRUD/promotion experiment: fixed Canon enters as mandatory compiler input, while narrative documents retain manuscript authority. Human reviewers may disagree with individual agent judgements, particularly whether an elaboration is consequential; no subjective agent score is a release certificate.

The concrete human packet is [RETRIEVAL_R5A_CONTINUITY_REVIEW_PACKET.md](RETRIEVAL_R5A_CONTINUITY_REVIEW_PACKET.md). It leaves all human scores blank. Your R5A requirement for human-judged continuity remains **open**.

### Degradation and resource observations

Each split runs four probes per cumulative degradation stage. Removing half the vectors exposes `partial_coverage`; editing a source without a manual projection refresh also exposes partial coverage; making the model directory absent reports `provider_unavailable` / `model_artifact_unavailable`, with lexical fallback remaining operational. Normal HTTP change notifications can refresh the edited projection after the first request; subsequent calls measure pending embedding, not a permanently unrefreshed source. These are readiness/fallback observations, not additional writer-quality trials.

Measurement host: Microsoft Windows 11 Pro, AMD Ryzen 9 7950X 16-Core Processor, 63.1 GiB physical RAM; graphics: Virtual Display, AMD Radeon(TM) Graphics, NVIDIA GeForce RTX 5060 Ti. Hardware is recorded for reproducibility, not used to set a post-hoc performance gate.

| Release query arm | Development p50 / p95 / p99 ms (60 samples) | Held-out p50 / p95 / p99 ms (72 samples) |
|---|---:|---:|
| Legacy | 24.32 / 27.97 / 33.98 | 26.92 / 30.00 / 35.07 |
| Scope FTS | 35.20 / 44.68 / 46.85 | 38.25 / 42.33 / 149.43 |
| Diagnostic Bekko orchestration | 133.27 / 137.71 / 267.55 | 138.16 / 153.76 / 445.52 |
| Hybrid RRF | 132.98 / 140.86 / 237.65 | 137.08 / 142.00 / 275.33 |

Warm-up, annotation checks, gold oracle and writer calls are outside timed retrieval samples. Runs are serial with no concurrent builds/tests. Small-sample p99 values are maxima-sensitive, not production SLOs. Bekko timings include hybrid orchestration, not isolated cosine scans. Compiler cost, writer time and R3/R4 figures are not added into an invented end-to-end number.

Runtime process resident peaks are **673.57 MiB development** and **673.81 MiB held-out**, dropping to 58.59/61.43 MiB after explicit Bekko unload for the missing-provider scenario. LM Studio's separate writer process is excluded. No 1K/10K/100K scaling, sustained contention, full-system peak RAM or Linux qualification was run in R5A.

### Validation and reproduction

- Default all-target suite: **237 passed**, zero failures.
- Native-Bekko all-target suite: **238 passed**, zero failures, three provisioned-artifact tests intentionally ignored by the ordinary suite. Their historical results are preserved, not claimed as rerun here.
- One new metric test checks duplicate-source inflation and no-answer denominators. Strict native Clippy for the new example passed with `-D warnings`; the release example built locked/offline.
- Both UTF-8 corpora pass structural and gold-eligibility validation. All 60 pre-R5 files remain byte-identical, including R0–R4 implementations, schemas, fixtures, reports and dependency locks.
- The task-owned writer is unloaded after its SDK instance reference is verified; pre-existing/user-reloaded instances are preserved. No live narrative database is opened.

Reproduction uses already provisioned local model/runtime paths and an already loaded writer. Outputs refuse overwrite:

```powershell
uv run --no-project python crates/arline-runtime/examples/support/validate_narrative_corpus.py crates/arline-runtime/tests/fixtures/retrieval_r5_development.json crates/arline-runtime/tests/fixtures/retrieval_r5_heldout.json
cargo test --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets
cargo test --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets --features native-bekko
cargo build --release --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --example narrative_qualification --features native-bekko
# Repeat separately with each frozen fixture, new output path and provisioned artifacts.
crates/arline-runtime/target/release/examples/narrative_qualification.exe --fixture PATH_TO_FROZEN_FIXTURE --out NEW_REPORT.json --model-dir PROVISIONED_BEKKO_DIR --runtime PROVISIONED_ONNXRUNTIME_DLL --writer-model ALREADY_LOADED_WRITER --repeats 3
uv run --no-project python crates/arline-runtime/examples/support/summarize_narrative_qualification.py --fixture PATH_TO_FROZEN_FIXTURE --report NEW_REPORT.json --out-prefix NEW_PREFIX
```

Final local evidence lives under `.codex-audit/retrieval-r5-20261107/`: `reviewed-corpus-freeze.json`, independent final label reviews, `development-baseline-final.json`, `heldout-baseline-final.json`, matching `*-final-summary.json` and blinded packets/keys, scene adjudications, `heldout-paired-uncertainty.json`, writer retention, source/binary manifests, `hardware.json`, command logs and final verification. Keep the keys hidden from subsequent human reviewers until scoring. Discard neither invalid attempts nor backups; they remain clearly excluded from final results.

Final recommendation: **remain legacy**. The synthetic held-out improvement is uncertain, no-answer retrieval does not abstain, generated factual/continuity errors remain, real-user manuscripts and human judgement are unqualified, and R5C/D have not run. R5A evidence is reviewable; its human acceptance gate is not complete.

## R5B–D status and compatibility

Not started. R5A does not authorize rank tuning, persistent SDK processes, native tokenizer dependencies, ANN, metadata caches, Linux installation or packaging/deployment changes. Legacy remains the default. R0–R4 rollback and database backups remain intact; the new harness and fixtures have no production database migration or runtime interface change. Release recommendation remains **legacy pending qualification**, independently of eventual R5A scores.


## R5A handoff

Human adjudication of the review packet and source labels is the next required input. Preserve the frozen held-out set for reporting; R5B must use new development experiments, not tune on these outcomes. Investigate applicability/current-state planning, noisy mixed-age evidence and no-answer decisions before choosing semantic-first or weighted fusion. The generated-scene failures also require a separate synthesis/epistemic-boundary investigation: source authorization alone did not ensure knowledge-correct output. R5C must qualify stronger retention with comparable writer counts; R5D still owns large-corpus targets, Windows packaging, Linux runtime and rollback deployment gates. None is qualified by this baseline.
