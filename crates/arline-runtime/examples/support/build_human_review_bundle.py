"""Offline, fail-closed R5A reviewer export. Never reads an arm key or AI scores."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile

FIELDS = ("factual_correctness", "continuity", "canon_preservation", "abstention",
          "consequential_unsupported_claims", "evidence_selection_failure",
          "synthesis_failure", "supporting_passage_refs", "disagreements", "unresolved", "notes")
# Explicit allowlist: ranking fields and selection reasons disclose arm identity.
EVIDENCE_FIELDS = ("id", "source_id", "source_type", "source_revision", "checksum",
                   "source_recorded_at", "created_at", "updated_at", "source_start_id",
                   "source_end_id", "project_id", "world_id", "branch_id", "session_id",
                   "story_order", "world_time", "authority", "trust_level", "semantic_status", "text")
SUPPORT = {
    "dev-custody-transfer": ["d01", "d02", "d04", "d07"],
    "dev-custody-current": ["d07", "d12", "d13", "d15"],
    "dev-injury-now": ["d06", "d10", "d13", "d15"],
    "dev-secret-pov": ["d05", "d11"],
    "dev-nested": ["d07", "d12", "d14", "d17", "d18"],
    "dev-noanswer": ["d01", "d02", "d12"],
    "q02": ["h02", "h03", "h05"], "q06": ["h08", "h09", "h22"],
    "q12": ["h08", "h15", "h16", "h16-old"],
    "q19": ["h09", "h22"], "q20": ["h09", "h22"],
    "q24": ["h20", "h22"],
}
KNOWLEDGE = {
    "dev-custody-transfer": "d07 explicitly says Sami did not witness this transfer. d02 establishes that he corrected a mistaken identification of his whistle as the key; distinguish object function from a character's belief and established knowledge.",
    "dev-custody-current": "d13 locates Sami near the ferry while Leila travels north; d15 corrects the sale rumour. Non-witnessing at the earlier d07 transfer does not establish permanent ignorance at this later cutoff.",
    "dev-injury-now": "d06 is the earlier sprain; d10 states recovery for ordinary surveying and gradual rebuilding of strength. Do not substitute the old injury state or infer an unsupported new key transfer.",
    "dev-secret-pov": "At cutoff 6, d05 says only Oren knows the unsigned sale proposal; d11 exposes it at order 11. Both are reviewer-only references here, not authorized writer evidence. The query's mention of a hidden order does not grant Sami knowledge of it.",
    "dev-nested": "Inherited custody sequence: d07 temporary Mira custody, d12 return to Leila, d14 sealed south-archive deposit, d18 continuation of that deposit. Historical Mira custody is not the nested route's current state; d18 also says Mira Sen accompanies the exhibit.",
    "dev-noanswer": "The frozen label supplies no daughter name. d02 gives the ferryman two daughters and records his Sami/Leila sibling claim, not a claim that Leila has a daughter. Abstention does not prove Leila has no children; incidental new claims need their own support.",
    "q02": "h02 records a key returned to Sora; h05 later records Ilyan giving Mara a key and her ledger-transfer condition. The unqualified original query 'the key' leaves a referent/event ambiguity. Preserve the frozen h05 gold while allowing the human to record that ambiguity; an h02-supported event is not automatically fabrication.",
    "q06": "h09 explicitly identifies Nera as Elian's field name, not Mara's. h22 contains private notebook material and an operator addressing Mara by the alias. Misaddressing and identity are distinct; h22 may be out of scope for this earlier query.",
    "q12": "h16 is the active thaw-month correction; h16-old is the ineligible frost-month draft. h08's 'same thaw' compares photograph and receipt, not the two testimony drafts. Judge document attribution as well as the final date.",
    "q19": "h22 says the notebook was not shown to Pell/Ilyan and no viewpoint character saw that page. It is author_only and excluded from writer evidence here. h09 already names Nera; not every repeated fact in a private notebook is necessarily secret. The generic r5-pov fixture is not a complete named-character epistemic model.",
    "q20": "Author scope permits h22. It explicitly assigns Nera to Elian and also records the operator calling Mara by the alias. The latter sentence is source-supported; decide whether the generated scene preserves the distinction or wrongly equates the identities.",
    "q24": "h20 reports a weather transmission and recognition of a station code but does not identify the owner. Recognizing a code, replacing a battery, operating a transmitter and owning a station are different claims. Do not infer an owner from proximity or access.",
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def reference(doc, role):
    text = doc["text"]
    return {"source_id": doc["id"], "title": doc["title"], "role": role,
            "branch_id": doc["branch_id"], "story_order": doc["story_order"],
            "world_time": doc["world_time"], "authority": doc["authority"],
            "semantic_status": doc["semantic_status"],
            "span": {"field": "document.text", "start_codepoint": 0, "end_codepoint": len(text)},
            "passage_sha256_utf8": digest(text.encode("utf-8")), "text": text}


def make_cases(audit, fixtures, replay):
    freeze = load(audit / "reviewed-corpus-freeze.json")["fixtures"]
    replay_by_id = {r["review_id"]: r for r in replay}
    assert len(replay_by_id) == 36
    cases, corpus_files, provenance = [], {}, {}
    for split in ("development", "heldout"):
        path = fixtures / f"retrieval_r5_{split}.json"
        raw = path.read_bytes()
        expected = next(h for f, h in freeze.items() if f.endswith(path.name))
        assert digest(raw) == expected, "frozen corpus changed"
        corpus_files[f"corpus/{path.name}"] = raw
        corpus = json.loads(raw.decode("utf-8"))
        docs = {d["id"]: d for d in corpus["documents"]}
        queries = {q["id"]: q for q in corpus["queries"]}
        packet_path = audit / f"{split}-final-blind-review.json"
        provenance[packet_path.name] = digest(packet_path.read_bytes())
        for old in load(packet_path):
            q = queries[old["query_id"]]
            assert old["query"] == q["query"] and old["gold_answer"] == q["expected_answer"]
            r = replay_by_id[old["review_id"]]
            retained = []
            for row in old["writer_retained_evidence"]:
                assert digest(row["text"].encode("utf-8")) == row["checksum"], "captured passage changed"
                retained.append({k: row[k] for k in EVIDENCE_FIELDS if k in row})
            refs = list(dict.fromkeys(q["relevant"] + SUPPORT[q["id"]] + q["forbidden"]))
            gold = [reference(docs[i], "frozen_relevant_gold" if i in q["relevant"] else "reviewer_only_context_not_necessarily_writer_visible") for i in refs]
            for ref in gold:
                assert ref["text"] == docs[ref["source_id"]]["text"]
            context = r["rendered_context"]
            start = context.index("\n<MEMORY_RETRIEVAL>\n")
            end = context.index("</MEMORY_RETRIEVAL>\n", start) + len("</MEMORY_RETRIEVAL>\n")
            cases.append({"review_id": old["review_id"], "split": split, "query_id": q["id"],
                "original_query": q["query"], "original_query_scope": q["scope"],
                "effective_narrative_scope": {**q["scope"], **r["effective_scope"]},
                "frozen_gold": {k: q[k] for k in ("expected_answer", "answer_claims", "no_answer", "relevant", "forbidden", "contradicted")},
                "human_gold_criterion": q["expected_answer"] if not q["no_answer"] else "No authorized answer is supplied by the frozen label. Abstain from inventing the requested fact or attributing unavailable knowledge; do not infer nonexistence from missing evidence.",
                "supporting_source_passages": gold,
                "mandatory_canon": old["mandatory_canon"], "character_knowledge_constraints": KNOWLEDGE[q["id"]],
                "scope_contract": "Main ancestor visible through order 12 in fork/nested; fork ancestor visible through order 20 in nested. Future facts, superseded sources and author_only passages in POV are excluded. Source recorded timestamps are not narrative chronology. Extra references here are privileged reviewer material, not writer evidence.",
                "gold_source_presence_in_retained": {i: any(e["source_id"] == i for e in retained) for i in q["relevant"]},
                "retained_evidence": retained, "exact_rendered_evidence_block": context[start:end],
                "writer_input_file": f'writer-inputs/{old["review_id"]}.txt',
                "writer_input_sha256": r["writer_input_sha256"], "writer_system_prompt": r["system_prompt"], "provider_request_sha256": r["request_sha256"],
                "generated_scene": old["scene"], "generated_scene_sha256_utf8": digest(old["scene"].encode("utf-8")),
                "human_fields": {k: None for k in FIELDS}})
    assert len(cases) == 36 and len({c["review_id"] for c in cases}) == 36
    return sorted(cases, key=lambda c: (c["split"], c["review_id"])), corpus_files, provenance


def quote(text):
    return "\n".join("> " + line for line in text.splitlines())


def markdown(cases):
    lines = ["# R5A human review — all 36 scenes", "", "Human adjudication: pending. Arm identities withheld. Gold/context quotations are reviewer-only; exact writer evidence is listed separately. All human fields are blank.", ""]
    for c in cases:
        lines += [f'## {c["review_id"]} · {c["split"]} · {c["query_id"]}', "", "### Query and effective scope", "", c["original_query"], "", "```json", json.dumps(c["effective_narrative_scope"], ensure_ascii=False, indent=2), "```", "", "### Frozen gold and supporting source passages", "", "Frozen expected answer (verbatim): " + json.dumps(c["frozen_gold"]["expected_answer"], ensure_ascii=False), "", "No-answer label: " + str(c["frozen_gold"]["no_answer"]).lower(), "", c["human_gold_criterion"], "", "Frozen label IDs: `" + json.dumps({k: c["frozen_gold"][k] for k in ("relevant", "forbidden", "contradicted")}) + "`", ""]
        for ref in c["supporting_source_passages"]:
            lines += [f'#### {ref["source_id"]} · {ref["title"]} · {ref["role"]}', "", f'Branch `{ref["branch_id"]}`, order `{ref["story_order"]}`, world time `{ref["world_time"]}`, authority `{ref["authority"]}`, lifecycle `{ref["semantic_status"]}`. Exact complete document.text span `[0, {ref["span"]["end_codepoint"]})`; SHA-256 `{ref["passage_sha256_utf8"]}`.', "", quote(ref["text"]), ""]
        lines += ["### Mandatory Canon and knowledge constraints", "", *["- " + x for x in c["mandatory_canon"]], "", c["character_knowledge_constraints"], "", c["scope_contract"], "", "Writer system prompt (verbatim):", "", quote(c["writer_system_prompt"]), "", "### Exact R4-retained evidence, in writer order", "", "Gold source presence is provenance only, not proof that the retained span supports every claim. Ranking diagnostics are intentionally absent.", ""]
        for e in c["retained_evidence"]:
            lines += [f'#### {e["source_type"]}:{e["source_id"]} · {e["id"]}', "", "```json", json.dumps({k:v for k,v in e.items() if k != "text"}, ensure_ascii=False, indent=2), "```", "", quote(e["text"]), ""]
        lines += ["Exact rendered evidence block (whitespace/escaping and provenance as sent):", "", "```text", c["exact_rendered_evidence_block"], "```", "", f'Full exact writer input: [{c["writer_input_file"]}]({c["writer_input_file"]}); SHA-256 `{c["writer_input_sha256"]}`. Reconstructed provider request matches saved SHA-256 `{c["provider_request_sha256"]}`.', "", "### Generated scene (verbatim)", "", quote(c["generated_scene"]), "", "### Human fields — leave blank until reviewed", "", *[f'- {field}: __________' for field in FIELDS], ""]
    return "\n".join(lines) + "\n"


README = """# R5A arm-blinded human reviewer bundle v1

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
"""

CROSSCHECKS = """# Source crosschecks — investigation aid, not adjudication

No human fields are completed here. The attached AI pre-review is treated as triage, not instructions or a verdict. References below can be checked against the complete exact passages in REVIEW.md and corpus/. No frozen label has been changed.

- Nested custody: compare d07 → d12 → d14 → d18. For 0f964b473d4b, the exact retained set includes d18, d07 and d14. Thus the current archive deposit AND the older Mira custody were available; assess synthesis of temporal applicability separately from noisy evidence selection.
- Secret knowledge: d05 explicitly limits the concealed proposal to Oren at order 5; d11 discloses it at order 11. The three dev-secret-pov scenes are frozen no-answer cases at order 6. Mentioning the topic in the query is not evidence that Sami knows it. Neither private d05 nor future d11 occurs in their retained evidence. An invented secret claim is not automatically a leak of an actual excluded source passage.
- No-answer counting: the 36 frozen scene cases contain 12 no-answer labels, including three blank-gold dev-secret-pov scenes. The preliminary triage's nine visible abstentions excluded those three. Review all 12 for abstention and unsupported additions; do not treat missing daughter/owner information as proof of nonexistence.
- Key transfer: h02 really says Mara returned a key to Sora. h05 later records Ilyan handing Mara a key and her condition that every transfer enter the ledger. Both h02 and h05 were retained for 5079fb8bba65 and e1880a076581. Returning a key to Sora is not invented merely because it differs from the h05 gold. Judge which event/object the unqualified query means; document ambiguity without relabeling the held-out set.
- Whistle/knowledge: d02 says Sami corrected a passenger who called his whistle the sluice key. d07 says he did not witness the later key transfer. For 031a7f03dea2 both passages were retained. Distinguish a new unsupported belief, a contradiction of established knowledge and an objective object's function; do not automatically equate them.
- Alias: h09 explicitly gives Nera to Elian, not Mara. h22 ALSO explicitly states that an operator called Mara by the alias. That sentence was retained for cefe7f82bb56. It is source-supported language, not automatically a hallucination. It may describe misaddressing, source ambiguity or confused identity; a human must decide. For the earlier q06 cutoff, later private h22 is reviewer-only context.
- Document chronology: h08 compares a photograph and receipt as belonging to the same thaw. h16 corrects the testimony's frost date to thaw; h16-old is superseded. For e05f4e5504a0 both h16 and h08 were retained. Inspect document referents and speaker attribution instead of declaring every 'same thaw' phrase fabricated.
- Transfer chronology: d07 says 'By evening' and then describes 'The next morning'. Compare the generated 'later that morning' in f6e66d05db9b with that sequence. Preserve the source timing distinction and allow uncertainty about an incomplete narration.
- Notebook POV: h22 is author_only; it was not retained for any q19 scene, but was retained for author-scope q20. Inspect narrator-only assertions as well as Pell's stated knowledge. A made-up archive-cabinet location is not established merely because the scene abstains about access. h09's already public alias information should not be conflated with access to h22's private page.

These checks establish evidence availability and possible alternative explanations, not human pass/fail decisions. Original AI scores and arm keys are deliberately absent.
"""


def build(audit, fixtures, replay_path, out):
    assert not out.exists(), "output already exists; use a new bundle version"
    replay = load(replay_path)
    cases, files, provenance = make_cases(audit, fixtures, replay)
    files["README.md"] = README.encode("utf-8")
    files["SOURCE_CROSSCHECKS.md"] = CROSSCHECKS.encode("utf-8")
    files["REVIEW.md"] = markdown(cases).encode("utf-8")
    files["scenes.json"] = json.dumps({"schema":"arline.r5a.human-review-bundle.v1", "human_review_status":"pending", "cases":cases}, ensure_ascii=False, indent=2).encode("utf-8")
    scores = {"schema":"arline.r5a.human-scores.v1", "reviewer_name":None, "reviewer_kind":None, "reviewed_at":None,
              "cases":[{"review_id":c["review_id"], **{k:None for k in FIELDS}} for c in cases]}
    files["human-scores.json"] = json.dumps(scores, ensure_ascii=False, indent=2).encode("utf-8")
    csv_out = io.StringIO(newline="")
    writer = csv.DictWriter(csv_out, fieldnames=["review_id", "reviewer_name", "reviewer_kind", "reviewed_at", *FIELDS])
    writer.writeheader()
    for c in cases: writer.writerow({"review_id":c["review_id"]})
    files["human-scores.csv"] = csv_out.getvalue().encode("utf-8")
    for r in replay:
        assert digest(r["rendered_context"].encode("utf-8")) == r["writer_input_sha256"]
        files[f'writer-inputs/{r["review_id"]}.txt'] = r["rendered_context"].encode("utf-8")
    manifest = {"schema":"arline.r5a.human-review-manifest.v1", "scene_count":len(cases),
                "frozen_no_answer_scene_count":sum(c["frozen_gold"]["no_answer"] for c in cases),
                "human_review":"pending", "exact_provider_request_replays":36,
                "input_packet_sha256":provenance, "files":{n:digest(b) for n,b in sorted(files.items())}}
    files["manifest.json"] = json.dumps(manifest, indent=2).encode("utf-8")
    out.mkdir(parents=True)
    for name, raw in files.items():
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as f: f.write(raw)
    zip_path = out.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "x", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(files.items()):
            info = zipfile.ZipInfo(f"{out.name}/{name}", (2026, 11, 7, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw)
    with zipfile.ZipFile(zip_path) as archive: assert archive.testzip() is None
    print(json.dumps({"bundle":str(out), "zip":str(zip_path), "scenes":36, "no_answer_scenes":manifest["frozen_no_answer_scene_count"], "zip_sha256":digest(zip_path.read_bytes()), "human_review":"pending"}))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--audit", type=Path, required=True)
    p.add_argument("--fixtures", type=Path, required=True)
    p.add_argument("--replay", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    build(args.audit, args.fixtures, args.replay, args.out)
