#!/usr/bin/env python3
"""One-command SentinelMAS + Booster/Webots launcher."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
BOOSTER_DIR = ROOT / "unitree-g1-webots"
SIMAGIA_DIR = ROOT / "SIMAGIA" / "sentinel_mas"
LOG_DIR = BOOSTER_DIR / ".logs"
SIMAGIA_IMPORTS = ("spade", "aiohttp", "loguru", "pyjabber")


def quote_cmd(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in command)


def run_command(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
    capture: bool = False,
    start_new_session: bool = False,
) -> subprocess.CompletedProcess[str]:
    location = f" (cwd={cwd})" if cwd else ""
    print(f"$ {quote_cmd(command)}{location}")
    if dry_run:
        return subprocess.CompletedProcess(command, 0, "", "")
    return subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(env) if env is not None else None,
        text=True,
        capture_output=capture,
        start_new_session=start_new_session,
        check=True,
    )


def command_succeeds(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    return (
        subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def host_platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def booster_env(base_env: Mapping[str, str]) -> dict[str, str]:
    env = dict(base_env)
    env.update(read_env_file(BOOSTER_DIR / ".env"))
    env.update(read_env_file(BOOSTER_DIR / f".env.{host_platform()}"))
    env.update(base_env)
    return env


def require_layout(root: Path) -> None:
    required = [
        root / "FULLSTACK_RUN.md",
        BOOSTER_DIR / "docker-compose.yml",
        BOOSTER_DIR / "tools" / "run_sentinelmas_booster.sh",
        SIMAGIA_DIR / "main.py",
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Missing required files:\n  " + "\n  ".join(missing))


def require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"Missing required command on PATH: {name}")


def default_webots_candidates() -> list[Path]:
    if os.environ.get("WEBOTS_PATH"):
        return [Path(os.environ["WEBOTS_PATH"])]
    if sys.platform == "darwin":
        return [Path("/Applications/Webots.app/Contents/MacOS/webots")]
    if sys.platform.startswith("linux"):
        return [
            Path("/usr/local/webots/webots"),
            Path("/snap/bin/webots"),
            Path("/opt/webots/webots"),
        ]
    return []


def check_webots_available() -> None:
    if shutil.which("webots"):
        return
    candidates = default_webots_candidates()
    if any(path.exists() for path in candidates):
        return
    checked = ", ".join(str(path) for path in candidates) or "PATH"
    raise SystemExit(
        f"Webots was not found ({checked}). Set WEBOTS_PATH to the Webots binary."
    )


def choose_simagia_python(root: Path, env: Mapping[str, str]) -> list[str]:
    explicit = env.get("SIMALGIA_PYTHON")
    if explicit:
        return shlex.split(explicit)

    for rel in (".venv-simagia310/bin/python", ".venv-simagia/bin/python"):
        candidate = root / rel
        if candidate.exists():
            return [str(candidate)]

    conda = shutil.which("conda")
    conda_env = env.get("SIMALGIA_CONDA_ENV", "cyberpatrol")
    if conda and command_succeeds([conda, "run", "-n", conda_env, "python", "--version"]):
        return [conda, "run", "--no-capture-output", "-n", conda_env, "python"]

    return [sys.executable]


def import_probe_code(modules: Iterable[str]) -> str:
    return "\n".join(
        [
            "import importlib.util, json, sys",
            f"modules = {json.dumps(list(modules))}",
            "missing = [name for name in modules if importlib.util.find_spec(name) is None]",
            "print(json.dumps(missing))",
            "raise SystemExit(1 if missing else 0)",
        ]
    )


def missing_python_modules(
    python_cmd: Sequence[str],
    modules: Iterable[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    dry_run: bool,
) -> list[str]:
    command = [*python_cmd, "-c", import_probe_code(modules)]
    if dry_run:
        print(f"$ {quote_cmd(command)} (cwd={cwd})")
        return []
    result = subprocess.run(
        command,
        cwd=cwd,
        env=dict(env),
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        missing = json.loads(result.stdout.strip() or "[]")
    except json.JSONDecodeError as exc:
        raise SystemExit(
            "Could not parse SIMAGIA dependency probe output:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        ) from exc
    return list(missing)


def ensure_simagia_deps(
    python_cmd: Sequence[str],
    *,
    env: Mapping[str, str],
    install: bool,
    dry_run: bool,
) -> None:
    missing = missing_python_modules(
        python_cmd,
        SIMAGIA_IMPORTS,
        cwd=SIMAGIA_DIR,
        env=env,
        dry_run=dry_run,
    )
    if dry_run:
        print("Dry run: SIMAGIA dependency install skipped.")
        return
    if not missing:
        print("SIMALGIA dependencies are already importable; skipping pip install.")
        return
    if not install:
        raise SystemExit(
            "SIMALGIA is missing imports: "
            + ", ".join(missing)
            + "\nRun again without --no-install-simagia-deps, or set SIMALGIA_PYTHON."
        )

    requirements = SIMAGIA_DIR / "requirements.txt"
    if requirements.exists():
        run_command(
            [*python_cmd, "-m", "pip", "install", "-r", str(requirements)],
            cwd=SIMAGIA_DIR,
            env=env,
            dry_run=dry_run,
        )

    still_missing = missing_python_modules(
        python_cmd,
        SIMAGIA_IMPORTS,
        cwd=SIMAGIA_DIR,
        env=env,
        dry_run=dry_run,
    )
    if still_missing:
        run_command(
            [*python_cmd, "-m", "pip", "install", *still_missing],
            cwd=SIMAGIA_DIR,
            env=env,
            dry_run=dry_run,
        )

    still_missing = missing_python_modules(
        python_cmd,
        SIMAGIA_IMPORTS,
        cwd=SIMAGIA_DIR,
        env=env,
        dry_run=dry_run,
    )
    if still_missing:
        raise SystemExit("SIMALGIA imports still missing: " + ", ".join(still_missing))


def build_simagia_env(
    base_env: Mapping[str, str],
    *,
    simulated_sensors: bool,
) -> dict[str, str]:
    env = dict(base_env)
    env["USE_BOOSTER_BRIDGE"] = "1"
    env.setdefault("USE_PPO_NAV", "1")
    env["PYTHONUNBUFFERED"] = "1"
    if simulated_sensors:
        env["SENTINEL_SIM"] = "1"
    return env


def ensure_booster_container(args: argparse.Namespace, env: Mapping[str, str]) -> None:
    run_command(["docker", "info"], capture=True, dry_run=args.dry_run)
    run_command(["docker", "compose", "version"], capture=True, dry_run=args.dry_run)

    image = env.get("IMAGE_NAME", "booster-t1-webots-ros:humble")
    if args.rebuild_booster or not command_succeeds(["docker", "image", "inspect", image]):
        run_command(
            ["./containers/build_ros_container.sh"],
            cwd=BOOSTER_DIR,
            env=env,
            dry_run=args.dry_run,
        )

    run_command(
        ["docker", "compose", "up", "-d", "ros2"],
        cwd=BOOSTER_DIR,
        env=env,
        dry_run=args.dry_run,
    )

    container = env.get("CONTAINER_NAME", "booster-t1-ros")
    run_command(
        ["docker", "exec", container, "test", "-f", "/workspace/rl/policy_runner.py"],
        cwd=BOOSTER_DIR,
        env=env,
        dry_run=args.dry_run,
    )


def run_booster_stack(args: argparse.Namespace, env: Mapping[str, str]) -> None:
    run_command(
        ["./tools/check_booster_runner_assets.sh"],
        cwd=BOOSTER_DIR,
        env=env,
        dry_run=args.dry_run,
    )
    launcher_env = dict(env)
    launcher_env.setdefault("USE_PPO_PATROL", "1")
    run_command(
        ["./tools/run_sentinelmas_booster.sh"],
        cwd=BOOSTER_DIR,
        env=launcher_env,
        dry_run=args.dry_run,
        start_new_session=True,
    )


def wait_for_port(host: str, port: int, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            if sock.connect_ex((host, port)) == 0:
                return True
        time.sleep(1)
    return False


def start_simagia(
    python_cmd: Sequence[str],
    *,
    env: Mapping[str, str],
    dry_run: bool,
) -> subprocess.Popen[bytes] | None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "simagia.log"
    command = [*python_cmd, "main.py", "--web"]
    print(f"$ {quote_cmd(command)} (cwd={SIMAGIA_DIR}, log={log_path})")
    if dry_run:
        return None
    log_file = log_path.open("ab")
    return subprocess.Popen(
        command,
        cwd=SIMAGIA_DIR,
        env=dict(env),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def stop_process(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (AttributeError, ProcessLookupError):
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preflight and launch SentinelMAS, Booster ROS, and Webots."
    )
    parser.add_argument("--dry-run", action="store_true", help="print commands only")
    parser.add_argument("--detach", action="store_true", help="exit after startup")
    parser.add_argument("--rebuild-booster", action="store_true", help="force Docker image rebuild")
    parser.add_argument(
        "--no-install-simagia-deps",
        dest="install_simagia_deps",
        action="store_false",
        default=True,
        help="only check SIMAGIA imports; do not pip install missing packages",
    )
    parser.add_argument(
        "--simagia-python",
        help="Python executable for SIMAGIA; same as SIMAGIA_PYTHON",
    )
    parser.add_argument(
        "--no-simulated-sensors",
        action="store_true",
        help="do not set SENTINEL_SIM=1 for the demo",
    )
    parser.add_argument("--dashboard-port", type=int, default=8080)
    parser.add_argument("--timeout", type=int, default=180)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    base_env = dict(os.environ)
    if args.simagia_python:
        base_env["SIMALGIA_PYTHON"] = args.simagia_python
    env = booster_env(base_env)
    simagia_env = build_simagia_env(
        env,
        simulated_sensors=not args.no_simulated_sensors,
    )

    require_layout(ROOT)
    require_command("docker")
    check_webots_available()

    python_cmd = choose_simagia_python(ROOT, simagia_env)
    print(f"SIMALGIA Python: {quote_cmd(python_cmd)}")
    print("No SIMAGIA docker-compose service exists here; launching SIMAGIA on host Python.")

    ensure_simagia_deps(
        python_cmd,
        env=simagia_env,
        install=args.install_simagia_deps,
        dry_run=args.dry_run,
    )
    ensure_booster_container(args, env)
    run_booster_stack(args, env)

    proc = start_simagia(python_cmd, env=simagia_env, dry_run=args.dry_run)
    if args.dry_run:
        return 0

    if proc is None:
        return 0

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "simagia.pid").write_text(f"{proc.pid}\n", encoding="utf-8")
    if proc.poll() is not None:
        raise SystemExit(
            f"SIMAGIA exited early with {proc.returncode}; see {LOG_DIR / 'simagia.log'}"
        )

    if not wait_for_port("127.0.0.1", args.dashboard_port, args.timeout):
        stop_process(proc)
        raise SystemExit(
            f"Timed out waiting for SIMAGIA dashboard on port {args.dashboard_port}; "
            f"see {LOG_DIR / 'simagia.log'}"
        )

    print(f"Dashboard: http://localhost:{args.dashboard_port}")
    print(f"Logs: {LOG_DIR}")
    if args.detach:
        print(f"SIMAGIA left running with PID {proc.pid}")
        return 0

    print("SIMAGIA is running; press Ctrl-C to stop it. Booster/Webots stay up until docker compose down.")
    try:
        return proc.wait()
    except KeyboardInterrupt:
        stop_process(proc)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
