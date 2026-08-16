from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MODE_CODES = {
    "smart_hybrid": "HYB",
    "wcf": "WCF",
    "raw": "RAW",
    "wcf_raw": "WRAW",
    "aif_core": "AIF",
}
REASON_CODES = {
    "off": "NT",
    "on": "T",
    "low": "TL",
    "medium": "TM",
    "high": "TH",
}


def make_run_id(mode: str, reasoning: str, timezone_name: str | None = None, *, now: datetime | None = None) -> str:
    mode_code = MODE_CODES.get(mode, re.sub(r"[^A-Z0-9]", "", mode.upper())[:6] or "RUN")
    reason_code = REASON_CODES.get(reasoning, "T")
    if now is None:
        if timezone_name:
            try:
                now = datetime.now(ZoneInfo(timezone_name))
            except (ZoneInfoNotFoundError, ValueError):
                now = datetime.now().astimezone()
        else:
            now = datetime.now().astimezone()
    elif now.tzinfo is None:
        if timezone_name:
            try:
                now = now.replace(tzinfo=ZoneInfo(timezone_name))
            except (ZoneInfoNotFoundError, ValueError):
                now = now.astimezone()
        else:
            now = now.astimezone()
    stamp = now.strftime("%Y%m%dT%H%M%S%z")
    return f"{mode_code}-{reason_code}-{stamp}"


@dataclass(slots=True)
class SavedRun:
    run_id: str
    directory: Path
    archive: Path
    files: dict[str, Path]


class ArtifactStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def save_generation(
        self,
        run_id: str,
        bundle,
        *,
        model: str,
        mode: str,
        reasoning: str,
        projection_mode: str | None = None,
    ) -> SavedRun:
        run_dir = self.root / run_id
        suffix = 2
        while run_dir.exists():
            run_dir = self.root / f"{run_id}-{suffix:02d}"
            suffix += 1
        run_id = run_dir.name
        run_dir.mkdir(parents=True, exist_ok=False)

        r = bundle.analysis.pipeline_result
        files: dict[str, Path] = {}

        def txt(kind: str, content: str, ext: str = "txt"):
            path = run_dir / f"{kind}-{run_id}.{ext}"
            path.write_text((content or "").rstrip() + "\n", encoding="utf-8")
            files[kind] = path

        def js(kind: str, payload):
            path = run_dir / f"{kind}-{run_id}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            files[kind] = path

        txt("story", bundle.story)
        txt("wcf", bundle.analysis.rendered_context.text, "wcf")
        txt("aif-core", bundle.analysis.aif_core)
        if bundle.reasoning:
            txt("reasoning", bundle.reasoning)

        js("stats", bundle.stats)
        js("post-validation", bundle.post_validation.to_dict() if bundle.post_validation else {})
        js("wcf-validation", bundle.analysis.wcf_validation.to_dict())
        js("writer-context", bundle.analysis.writer_context.to_dict())
        js("projections", [x.to_dict() for x in getattr(bundle.analysis.writer_context, "projections", [])])
        js("semantic-core", bundle.analysis.semantic_core.to_dict())
        js("world-runtime", bundle.analysis.world_runtime)
        js("narrative-runtime", bundle.analysis.narrative_runtime.to_dict())
        js("writer-request", {
            "run_id": run_id,
            "mode": mode,
            "reasoning": reasoning,
            "projection_mode": projection_mode,
            "model": model,
            "model_input": bundle.model_input,
        })
        js("lmstudio-response", bundle.raw_response)
        js("extracted-state", r.extracted_state)
        js("events", r.events)
        js("analysis", r.analysis)

        manifest = {
            "run_id": run_id,
            "mode": mode,
            "reasoning": reasoning,
            "projection_mode": projection_mode,
            "model": model,
            "files": {k: v.name for k, v in files.items()},
        }
        manifest_path = run_dir / f"manifest-{run_id}.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        files["manifest"] = manifest_path

        archive_base = self.root / f"Arline-{run_id}"
        archive_path = Path(shutil.make_archive(str(archive_base), "zip", root_dir=run_dir))
        return SavedRun(run_id=run_id, directory=run_dir, archive=archive_path, files=files)
