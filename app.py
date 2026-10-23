from __future__ import annotations

import argparse
from pathlib import Path

from src.interface.react_app import launch_ui
from src.runtime_config import DEFAULT_CONFIG_PATH


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Launch Arline Studio (React/Vite frontend with legacy fallback)"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Runtime TOML config (default: config/arline.toml)",
    )
    args = parser.parse_args()
    launch_ui(args.config)


if __name__ == "__main__":
    main()
