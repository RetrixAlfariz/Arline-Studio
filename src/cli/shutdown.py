from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from src.runtime_config import DEFAULT_CONFIG_PATH, RuntimeConfig


ARLINE_PROCESS_MARKERS = (
    "app.py",
    "arline-ui",
    "src.interface.react_app",
    "src.interface.web.app",
    "uvicorn",
)


def _parse_windows_netstat(output: str, port: int) -> set[int]:
    """Return listening PIDs for *port* from `netstat -ano` output."""
    pids: set[int] = set()
    port_suffix = f":{port}"
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0].upper() != "TCP":
            continue
        local_address, state, pid_text = fields[1], fields[3].upper(), fields[4]
        if state != "LISTENING" or not local_address.endswith(port_suffix):
            continue
        try:
            pids.add(int(pid_text))
        except ValueError:
            continue
    return pids


def _listener_pids(port: int) -> set[int]:
    if os.name == "nt":
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
        )
        return _parse_windows_netstat(result.stdout, port)

    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        capture_output=True,
        text=True,
        check=False,
    )
    return {int(value) for value in result.stdout.split() if value.isdigit()}


def _process_command_line(pid: int) -> str:
    if os.name == "nt":
        escaped_pid = str(pid).replace("'", "''")
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter \"ProcessId={escaped_pid}\").CommandLine",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip()

    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(
            errors="replace"
        ).strip()
    except (FileNotFoundError, PermissionError):
        return ""


def _looks_like_arline(command_line: str) -> bool:
    lowered = command_line.lower()
    return any(marker.lower() in lowered for marker in ARLINE_PROCESS_MARKERS)


def _terminate(pid: int) -> None:
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 and "not found" not in result.stdout.lower():
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "taskkill failed")
        return
    os.kill(pid, signal.SIGKILL)


def shutdown(port: int, *, force_any: bool = False, dry_run: bool = False, wait_seconds: float = 3.0) -> int:
    """Stop Arline's web listener on *port* and return a process-style status."""
    pids = _listener_pids(port) - {os.getpid()}
    if not pids:
        print(f"Arline web is not listening on port {port}.")
        return 0

    blocked: list[int] = []
    targets: list[int] = []
    for pid in sorted(pids):
        command_line = _process_command_line(pid)
        if force_any or _looks_like_arline(command_line):
            targets.append(pid)
        else:
            blocked.append(pid)

    if blocked:
        print(
            "Refusing to stop non-Arline listener(s) "
            f"{', '.join(map(str, blocked))}. Use --any-process only if intentional.",
            file=sys.stderr,
        )
    if not targets:
        return 1

    for pid in targets:
        command_line = _process_command_line(pid)
        print(f"{'Would stop' if dry_run else 'Stopping'} PID {pid}: {command_line or '<command unavailable>'}")
        if not dry_run:
            try:
                _terminate(pid)
            except (OSError, RuntimeError) as exc:
                print(f"Failed to stop PID {pid}: {exc}", file=sys.stderr)
                return 1

    if dry_run:
        return 0

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline and _listener_pids(port) & set(targets):
        time.sleep(0.1)
    remaining = _listener_pids(port) & set(targets)
    if remaining:
        print(f"Listener still active on port {port}: {sorted(remaining)}", file=sys.stderr)
        return 1
    print(f"Arline web stopped on port {port}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Force-stop the local Arline Studio web server.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--port", type=int, help="Override [ui].port from the runtime config.")
    parser.add_argument(
        "--any-process",
        action="store_true",
        help="Allow stopping a non-Arline process listening on the selected port.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show targets without stopping them.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.port is not None and not 1 <= args.port <= 65535:
        print("--port must be between 1 and 65535", file=sys.stderr)
        return 2
    try:
        port = args.port if args.port is not None else int(RuntimeConfig.load(args.config).ui.port)
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    return shutdown(port, force_any=args.any_process, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
