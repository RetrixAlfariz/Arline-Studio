from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "interface" / "web" / "static"
INDEX = STATIC / "index.html"
SHELL = STATIC / "chat-runtime-v125.css"
BASE = STATIC / "chat-runtime-v125-base.css"


def test_ortheon_shell_preserves_existing_runtime_stylesheet():
    shell = SHELL.read_text(encoding="utf-8")
    base = BASE.read_text(encoding="utf-8")

    assert shell.lstrip().startswith(
        '@import url("/static/chat-runtime-v125-base.css?v=1.2.5-scroll");'
    )
    assert base.strip(), "The preserved v1.2.5 chat runtime stylesheet must not be empty."
    assert "--ortheon-surface-0" in shell
    assert "--ortheon-core:#2f9b81" in shell
    assert ".workspace-sidebar" in shell
    assert ".composer-card" in shell
    assert ".inspector" in shell
    assert ".sheet-panel" in shell


def test_html_keeps_critical_runtime_ids_singleton():
    html = INDEX.read_text(encoding="utf-8")

    # These IDs are hard runtime contracts used by the existing vanilla-JS UI.
    # The shell redesign must never replace them with a parallel React-only DOM.
    critical_ids = (
        "workspaceSidebar",
        "workbench",
        "mainStage",
        "chatView",
        "conversationFeed",
        "composerDock",
        "promptInput",
        "generateBtn",
        "inspector",
        "sheetPanel",
    )
    for element_id in critical_ids:
        assert html.count(f'id="{element_id}"') == 1, element_id


def test_html_still_loads_final_runtime_layer():
    html = INDEX.read_text(encoding="utf-8")
    expected = '/static/chat-runtime-v125.css?v=1.2.5-scroll'
    assert html.count(expected) == 1

    # Basic document guards for the brittle monolithic static shell.
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert html.count("<html") == 1
    assert html.count("</html>") == 1
    assert html.count("<body") == 1
    assert html.count("</body>") == 1
