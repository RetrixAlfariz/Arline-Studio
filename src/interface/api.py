"""Thin programmatic interface over ArlineService for non-web frontends."""
from src.service import ArlineService


def analyze(prompt: str, config_path="config/arline.toml"):
    return ArlineService.from_config(config_path).analyze(prompt)


def generate(prompt: str, config_path="config/arline.toml", mode=None):
    return ArlineService.from_config(config_path).generate(prompt, mode=mode)
