# R5A arm-blinded human reviewer bundle v1

All 36 scene IDs and frozen labels are preserved. Start with REVIEW.md or scenes.json. The corpus/ directory contains byte-identical original corpora for checking absence/no-answer claims. writer-inputs/ contains the exact rendered input for each scene; offline replay matched all 36 original provider request hashes. No inference or database access was used for export.

Gold quotations and knowledge constraints are privileged reviewer references, NOT evidence the writer necessarily received. The exact retained evidence and rendered block are separate. Raw text is preserved; R4 whitespace normalization and angle-bracket escaping appear in the rendered block. A source ID alone does not prove a particular claim was retained. Captured source revisions/checksums/timestamps are included; timestamps are recorded time, not fictional world chronology. The generic r5-pov fixture is not a complete named-character knowledge ledger.

Arm keys, rank/fusion scores, lane ranks, selection reasons, inference timings and prior AI scores are excluded. Retained evidence order is kept because it is part of the actual input. Do not consult the repository's hidden key or earlier ranking reports before scoring. Do not infer an arm from prose quality. Review IDs were preserved, not regenerated.

## Human scoring

Use human-scores.json (recommended) or human-scores.csv. Fill reviewer_name, reviewer_kind=human and reviewed_at yourself. Use pass/fail/uncertain/not_applicable for factual correctness, continuity, Canon preservation and abstention. Fill consequential_unsupported_claims as a nonnegative integer or uncertain. Assess abstention on EVERY frozen no_answer=true case, including blank gold answers: there are 12 such generated scenes, not just the 9 visible-target cases counted by the preliminary AI triage.

Do not convert a model's judgement into a human score. Human fields begin null/blank. The AI pre-review is an optional investigation aid only; risk and gold-alignment indicators are not comparable to full factual/continuity scores. Ordinary harmless scene elaboration need not be a consequential unsupported claim. A correct short answer can still have unsupported surrounding claims. A false character belief is not automatically an objective Canon violation: inspect established knowledge and the narrative framing.

## Two independent failure classes

Evidence selection failure: missing, stale, irrelevant or inapplicable evidence, including evidence lost during context packing. Record the actual missing/wrong passage and its applicability. An old-but-authorized historical source is not automatically a scope violation.

Synthesis failure: sufficient correct evidence is actually retained, but the writer invents facts, confuses referents, combines incompatible states, misattributes knowledge or disregards Canon. Record the conflicting claim and the supporting retained span. Presence of a correct source ID alone is insufficient proof of sufficient evidence.

Score these separately as none/failure/uncertain and describe subtypes in notes. Both may apply; neither is a combined retrieval-quality score. Treat a genuinely ambiguous query/source as unresolved rather than silently editing the gold. Distinguish source ambiguity, narrator knowledge, character knowledge and model invention.

## Review closure

Return the scored JSON/CSV, including uncertain/unresolved cases and claim-level disagreements with AI triage. Keep frozen corpora, scenes, exact evidence, IDs and manifest unchanged; edit only a copy of a score template. Review both requested answers and consequential additions.

After a person scores the scenes, the updated R5A assessment will list human results, disagreements with preliminary AI claims, unresolved cases and proposed R5B experiments. Evidence selection and synthesis findings remain separate. No human verdict or optimization is produced by this bundle. The default engine and production code remain unchanged.

manifest.json records every bundled file except itself. The ZIP includes only this public reviewer directory, never audit keys, source code or AI adjudications. SOURCE_CROSSCHECKS.md is a source-grounded investigation aid, not a score; read it after your initial judgement if avoiding anchoring is important.
