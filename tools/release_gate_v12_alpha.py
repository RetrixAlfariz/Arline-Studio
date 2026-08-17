from __future__ import annotations

from pathlib import Path
import ast
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(path: str, *, when: bool = True) -> None:
    target = ROOT / path
    if when and target.exists():
        subprocess.run(["python", str(target)], cwd=ROOT, check=True)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


# Build the additive v1.2 integration if an earlier one-shot job did not finish.
app = read("src/interface/web/app.py")
run("tools/apply_v12_memory_foundation.py", when="/api/memory/status" not in app)

# Idempotent hardening/polish passes. Only run optional extensions when their
# final source contracts are still absent, avoiding duplicate service wiring.
run("tools/finalize_v12_memory_foundation.py")
run("tools/verify_v12_alpha.py")
run("tools/polish_v12_spatial_ui.py", when="openSpatialLinkDialog" not in read("src/interface/web/static/js/memory.js"))
run("tools/extend_v12_cutoffs.py", when="branch_fork_metadata" not in read("src/memory/store.py"))
run("tools/fix_v12_branch_cutoff_chain.py")
run("tools/extend_v12_reasoning_indexes.py", when="/api/memory/summaries" not in read("src/interface/web/app.py"))

# Final source invariants after all additive patches.
store_path = "src/memory/store.py"
store = read(store_path)
store = store.replace(
    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active','ready',?,?,?,?,?,?)",
    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active','ready',?,?,?,?,?)",
)
write(store_path, store)

app_path = "src/interface/web/app.py"
app = read(app_path)
app = app.replace(
    '            payload={"project_id": payload.project_id}, message="Indexing source-backed evidence",\n',
    '            payload={"project_id": payload.project_id},\n',
)
app = app.replace("payload.model_dump()", "payload.model_dump() if hasattr(payload, 'model_dump') else payload.dict()")
write(app_path, app)

# Avoid repeated imports produced by an interrupted/retried one-shot workflow.
scope_path = "src/memory/scope.py"
scope = read(scope_path)
scope = re.sub(r"(?:import sqlite3\n){2,}", "import sqlite3\n", scope)
write(scope_path, scope)

# Keep exports deterministic regardless of the pre-v1.2 eval package shape.
eval_path = "src/eval/__init__.py"
eval_source = read(eval_path)
if "from .memory import" in eval_source and "__all__ +=" in eval_source and "__all__ =" not in eval_source:
    eval_source = eval_source.replace("from .memory import", "__all__ = []\n\nfrom .memory import", 1)
write(eval_path, eval_source)

# Permanent CI must validate the development branch and every browser module.
ci_path = ".github/workflows/ci.yml"
ci = read(ci_path)
if '      - "develop/**"' not in ci:
    ci = ci.replace('      - "release/**"\n', '      - "release/**"\n      - "develop/**"\n')
if "src/interface/web/static/js/memory.js" not in ci:
    ci = ci.replace(
        "          node --check src/interface/web/static/js/stream.js\n",
        "          node --check src/interface/web/static/js/stream.js\n          node --check src/interface/web/static/js/memory.js\n",
    )
write(ci_path, ci)

# Ensure the implementation note exists even if the earlier verifier raced.
doc_path = ROOT / "docs/V12_ALPHA_FOUNDATION.md"
if not doc_path.exists():
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(
        "# Arline Studio v1.2 Alpha Foundation\n\n"
        "The `develop/v1.2` branch contains the additive evidence-memory and "
        "specialized-query foundation. It remains intentionally unmerged until "
        "the user accepts its behavior and the remaining v1.2 milestones are complete.\n",
        encoding="utf-8",
    )

# Parse every Python file before dependency installation can hide syntax errors.
for folder in (ROOT / "src", ROOT / "tests"):
    for source in sorted(folder.rglob("*.py")):
        ast.parse(source.read_text(encoding="utf-8"), filename=str(source))

print("Consolidated Arline v1.2 alpha source; ready for full regression gate")
