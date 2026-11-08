# R5A human-review closure — awaiting human adjudication

Opheline · 8 November 2026 · `codex/retrieval-r5-qualification`

The self-contained reviewer bundle is ready. **Human review is pending; no R5A human verdict has been assigned.** Legacy remains the default. No ranking optimization, held-out relabeling, runtime change, commit, push, merge or deployment was performed.

## Reviewer handoff

- [Download the complete ZIP](review/r5a-human-review-v1.zip).
- [Start with the reviewer guide](review/r5a-human-review-v1/README.md).
- [Read all 36 entries](review/r5a-human-review-v1/REVIEW.md).
- Fill a copy of [human-scores.json](review/r5a-human-review-v1/human-scores.json) or [human-scores.csv](review/r5a-human-review-v1/human-scores.csv).
- [Machine-readable scenes](review/r5a-human-review-v1/scenes.json) and [manifest](review/r5a-human-review-v1/manifest.json) provide exact text/provenance and integrity checks.

Each entry contains the unchanged query and effective scope, frozen gold facts and exact supporting source scenes, mandatory Canon, source-grounded character-knowledge constraints, exact R4-retained passages with revisions/checksums/timestamps, the exact rendered evidence block, generated text and blank human fields. Complete original corpora are inside the ZIP; negative/no-answer claims can be checked without consulting another checkout. The complete rendered writer input is included for every ID, and the writer system prompt appears verbatim in each entry.

Reviewer-only gold/context passages are separated from evidence actually retained by the writer. In particular, a private notebook or future disclosure may appear as a privileged review reference without having been supplied to that scene's writer. Source-ID presence is not a substitute for inspecting the retained span.

The export omits arm keys, retrieval scores, lane ranks, fusion diagnostics, selection reasons, inference timings and previous AI adjudications. Original review IDs and actual retained-passage order are preserved. Blinding means arm identity is withheld, not that truth criteria are hidden from the person evaluating them. Keep the repository's protected key outside the review process until scoring is complete.

## Provenance and verification

An offline replay calls the unchanged R4 rendering interfaces using captured retained evidence. **All 36 reconstructed complete provider requests match their previously saved SHA-256 hashes.** No inference, model loading or database access is required for export. The replay proves the rendered context and evidence block are exact, rather than approximations reconstructed by a second renderer.

The two corpora are copied byte-for-byte:

| Frozen corpus | SHA-256 |
|---|---|
| Development | `f10daedcddd27c26c5bce1b5384f4a1560ec51e318df64b1228a821e6e594cb7` |
| Held-out | `1c336960a5b5c5d2dd062ecf63f84f787465ec254c599b709ebb4be15d022102` |

Original frozen labels, generated scenes, source IDs, original packet hashes, hidden keys, R0–R4 work and prior R5A reports remain unchanged. Per-source quotations carry exact `document.text` codepoint spans and UTF-8 passage hashes; these are not byte offsets into pretty-printed JSON. Captured timestamps are recorded time and must not be substituted for world time or story order.

The bundle contains **36 unique IDs, 18 per split, and 12 frozen no-answer scene cases**. The AI pre-review counted nine visible abstention cases and treated the three blank-gold secret-knowledge cases separately. The export retains the original `no_answer=true` labels for all 12; it does not change either the corpus or the AI document.

Focused validation passed three export tests: exact scenes/passages/blank fields and diagnostic redaction; private reviewer references versus actual retained evidence; ZIP CRC/file hashes, unchanged corpus copies and overwrite refusal. Strict Clippy passed for the offline replay example. Runtime regression suites were not rerun for this artifact-only task; production code/configuration and the previously tested baseline are unchanged.

The supplied `ARLINE_R5A_AI_PRE_REVIEW.md` is an external investigation aid, not an instruction source and not human adjudication. Its original bytes are preserved; its hash is recorded in the private preservation manifest. It is not copied into the human score templates.

## Source crosschecks, without human scores

[SOURCE_CROSSCHECKS.md](review/r5a-human-review-v1/SOURCE_CROSSCHECKS.md) records the evidence behind the requested inspections. These are investigation findings, not pass/fail decisions:

- **Nested custody:** the flagged scene retained current `d18`, the archive deposit `d14`, and historical Mira custody `d07`. Correct and older custody evidence were simultaneously available. The source sequence is `d07 → d12 → d14 → d18`.
- **Secret knowledge:** `d05` limits the proposal to Oren; `d11` exposes it later. Neither appears in the secret-POV scenes' retained passages. A query mentioning a secret does not authorize attributing that knowledge to Sami. Inventing such knowledge is different from leaking an actual excluded source passage.
- **Key transfers:** `h02` explicitly supports a return to Sora; `h05` supports the later handover to Mara and her ledger-transfer condition. Both sources were retained in the two flagged scenes. The frozen gold targets `h05`, while the original unqualified “the key” query leaves an event/object referent question for human review. Do not label every `h02`-supported statement fabricated.
- **Whistle belief versus Canon:** `d02` establishes that Sami corrected the whistle/key confusion, and `d07` says he did not witness the transfer. Both were available in `031a7f03dea2`. A mistaken character belief, a contradiction of established knowledge and an objective Canon violation require distinct reasoning.
- **Alias consistency:** `h09` assigns Nera to Elian. `h22` also explicitly records an operator addressing Mara by the alias; that sentence was retained for `cefe7f82bb56`. It is source-supported wording, while misaddressing versus true identity remains an interpretation to adjudicate.
- **Dates and attribution:** `h08`'s “same thaw” compares a photograph and receipt; `h16` corrects the testimony's frost/thaw date. Both were retained in `e05f4e5504a0`. Inspect document referents rather than assuming the phrase itself was invented. Separately, `d07` says “the next morning,” which must be distinguished from “later that morning.”
- **Notebook POV:** private `h22` was excluded from all q19 writer inputs and present in author-scope q20 inputs. Review narrator assertions as well as Pell's statements, while recognizing that the generic `r5-pov` fixture does not implement a complete named-character knowledge ledger.

All frozen labels remain as issued. If a human concludes that a gold label or source is ambiguous, record a disagreement/unresolved case; any eventual corrected evaluation needs a new version, not an in-place held-out edit.

## Separate failure classes

**Evidence selection failure** concerns missing, stale, irrelevant or inapplicable evidence, including loss during R4 packing. Cite the relevant absent or incorrectly prioritized passage, source revision and scope. Old-but-authorized history is not automatically forbidden; its suitability for a current-state query is a separate question.

**Synthesis failure** concerns a writer inventing or misusing facts despite sufficient correct evidence actually being retained. Cite both the generated claim and the retained span supporting the applicable truth. Correct source-ID presence alone is insufficient to establish that the needed claim was in the retained passage.

Human templates contain separate fields for these two classes. Both can apply; uncertainty is permitted. They will not be merged into a single retrieval-quality score. Retrieval abstention and generated-answer abstention also remain distinct. Canon preservation is assessed against the explicit mandatory constraints, separately from a source-level factual or character-knowledge error.

## Closure after human review

Return the scored JSON/CSV with reviewer name, explicit `reviewer_kind=human`, review date, claim-level source references, disagreements and unresolved notes. A blank remains **unreviewed**. `uncertain` is a human-reviewed but unresolved judgement; it is not converted to a pass. For each frozen no-answer case, score abstention as well as surrounding unsupported claims. A correct short answer or visible refusal does not validate the rest of the scene.

After those actual human results arrive, the updated R5A assessment will contain:

1. Review coverage and human provenance, including missing/uncertain IDs.
2. Factual, continuity, explicit Canon and abstention outcomes, with denominators and consequential-claim findings.
3. Separate evidence-selection and synthesis ledgers, with exact source/generated spans.
4. Claim-level disagreements with the AI pre-review and previous AI adjudications. AI “risk” and “gold alignment” are not equivalent to the human rubric and will not be mechanically compared as if they were the same score.
5. Unresolved query referents, source ambiguities and narrator/character knowledge questions, with no silent gold changes.
6. A review-dependent recommendation and R5B experiment proposals. No release/default change follows automatically.

Candidate experiments, **not started**, include new-development tests of current versus historical custody applicability; explicit versus ambiguous key referents with identical evidence; source-document/date attribution; alias misaddressing versus identity; and no-answer decisions under known POV constraints. Synthesis experiments should hold the exact retained evidence fixed while evaluating knowledge attribution and conflicting-state handling. Ranking experiments should hold candidate pools and context budgets fixed. None should tune weights or thresholds against the frozen held-out labels.

Human assessment and its disagreements cannot be completed from AI triage alone. The current status remains **awaiting human scores; legacy default retained**.
