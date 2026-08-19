from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Missing expected block in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace(
    "src/runtime_config.py",
    '''        doc["lmstudio"].update({
            "base_url": self.lmstudio.base_url,
            "model": self.lmstudio.model,
            "api_key": self.lmstudio.api_key,
            "timeout_seconds": self.lmstudio.timeout_seconds,
            "auto_load": self.lmstudio.auto_load,
        })
''',
    '''        # API keys are runtime secrets. They may come from the environment
        # or a transient UI request, but saving ordinary settings must never
        # copy them into the portable TOML file.
        doc["lmstudio"].update({
            "base_url": self.lmstudio.base_url,
            "model": self.lmstudio.model,
            "api_key": "",
            "timeout_seconds": self.lmstudio.timeout_seconds,
            "auto_load": self.lmstudio.auto_load,
        })
''',
)

replace(
    "src/interface/web/static/arline.js",
    '''  byId("apiKey").placeholder = config.api_key_configured ? "Configured — leave blank to keep" : "Optional API key";
''',
    '''  byId("apiKey").placeholder = config.api_key_configured
    ? "Configured securely · optional session override"
    : "Session-only key · persist with ARLINE_LMSTUDIO_API_KEY";
''',
)
replace(
    "src/interface/web/static/arline.js",
    '''    toast("Settings saved");
''',
    '''    toast("Settings saved · API keys stay out of arline.toml");
''',
)

replace(
    "config/arline.toml",
    '''api_key = ""
''',
    '''# Runtime secret only. For persistence, set ARLINE_LMSTUDIO_API_KEY;
# Settings saves intentionally keep this portable file blank.
api_key = ""
''',
)

print("secret persistence hardening applied")
