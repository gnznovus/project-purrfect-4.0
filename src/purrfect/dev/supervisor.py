"""Detached single-instance development supervisor for Gateway and Console.

The supervisor owns only processes that it starts. Never terminate arbitrary
port occupants or trust a stale PID without checking process creation time.
All management artifacts live in the Git-ignored .purrfect directory.
"""
import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil

from purrfect.config import config_path, load_settings

ROOT = config_path().parent
RUN = ROOT / ".purrfect"
STATE = RUN / "supervisor.json"
STOP = RUN / "stop.json"
LOG = RUN / "supervisor.log"
SERVICES = (
    ("gateway", "purrfect", "PURR_HOST", "PURR_PORT", 8765),
    ("console", "purrfect.operations", "PURR_OPERATIONS_HOST", "PURR_OPERATIONS_PORT", 8775),
)


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as file:
            json.dump(data, file)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _matches(pid, created) -> psutil.Process | None:
    try:
        process = psutil.Process(int(pid))
        if process.is_running() and process.status() != psutil.STATUS_ZOMBIE and abs(process.create_time() - float(created)) < 0.1:
            return process
    except (psutil.Error, ValueError, TypeError, OverflowError):
        pass
    return None


def _active(state: dict) -> psutil.Process | None:
    return _matches(state.get("pid"), state.get("created"))


def _require_development() -> bool:
    """Explicit production mode blocks every local supervisor command."""
    mode = load_settings().get("PURR_ENV", "development").lower()
    if mode != "development":
        print("Purr local supervisor disabled: PURR_ENV must be development.")
        return False
    return True


def init() -> int:
    """Create missing private local credentials without replacing existing ones."""
    if not _require_development():
        return 2
    from purrfect.config import initialize
    path = config_path()
    if path.exists() or path.is_symlink():
        print("Existing .env preserved; nothing to initialize.")
        return 0
    try:
        initialize()
    except FileExistsError:
        print(".env already exists; no credentials overwritten.")
        return 0
    except (ValueError, OSError) as exc:
        print(f"Local initialization failed: {type(exc).__name__}")
        return 1
    print("Development .env initialized. Operator token is stored there.")
    return 0


def _config():
    settings = load_settings()
    entries = []
    for name, module, host_key, port_key, default_port in SERVICES:
        host = settings.get(host_key, "127.0.0.1")
        # The supervisor is strictly local. Production/remote deployment
        # remains managed externally, not by this tool.
        if host not in ("127.0.0.1", "localhost"):
            raise ValueError(f"{name} host must be loopback for dev supervisor")
        port = int(settings.get(port_key, str(default_port)))
        if not 1 <= port <= 65535:
            raise ValueError(f"Invalid {name} port")
        entries.append((name, module, "127.0.0.1", port))
    if entries[0][3] == entries[1][3]:
        raise ValueError("Gateway and Console ports must be distinct")
    return entries


def _port_busy(host: str, port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def _terminate(proc: psutil.Process, timeout: float = 6) -> None:
    # Child processes are identified via psutil, not by port number.
    try:
        descendants = proc.children(recursive=True)
    except psutil.Error:
        descendants = []
    for child in reversed(descendants):
        try:
            child.terminate()
        except psutil.Error:
            pass
    try:
        proc.terminate()
    except psutil.Error:
        pass
    alive = psutil.wait_procs(descendants + [proc], timeout=timeout)[1]
    for process in alive:
        try:
            process.kill()
        except psutil.Error:
            pass


def _stop_children(children: list[subprocess.Popen]) -> None:
    for child in reversed(children):
        try:
            process = psutil.Process(child.pid)
            if child.poll() is None and process.is_running():
                _terminate(process)
        except psutil.Error:
            pass


def _serve():
    if not _require_development():
        return
    import msvcrt  # Windows-only single-instance lock.
    RUN.mkdir(exist_ok=True)
    with (RUN / "supervisor.lock").open("a+b") as lock:
        lock.seek(0)
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return  # Another supervisor already owns the instance.
        current = _read(STATE)
        if _active(current):
            return
        settings = _config()
        for name, _, host, port in settings:
            if _port_busy(host, port):
                _write_atomic(STATE, {"state": "failed", "reason": f"{name} port {port} is occupied"})
                return
        token = secrets.token_urlsafe(32)
        current_process = psutil.Process()
        state = {
            "state": "starting", "pid": os.getpid(),
            "created": current_process.create_time(), "token": token,
            "services": {},
        }
        _write_atomic(STATE, state)
        children = []
        STOP.unlink(missing_ok=True)
        try:
            for name, module, host, port in settings:
                logfile = RUN / (name + ".log")
                with logfile.open("ab") as log:
                    child = subprocess.Popen(
                        [sys.executable, "-m", module],
                        cwd=ROOT, stdin=subprocess.DEVNULL,
                        stdout=log, stderr=subprocess.STDOUT,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                children.append(child)
                state["services"][name] = {"pid": child.pid, "port": port}
                _write_atomic(STATE, state)
            deadline = time.monotonic() + 18
            while time.monotonic() < deadline:
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("A service exited before readiness")
                if all(_port_busy(host, port) for _, _, host, port in settings):
                    state["state"] = "running"
                    _write_atomic(STATE, state)
                    break
                time.sleep(0.15)
            else:
                raise RuntimeError("Services did not open their local ports")
            while all(child.poll() is None for child in children):
                order = _read(STOP)
                if order.get("token") == token and order.get("action") == "stop":
                    break
                time.sleep(0.25)
            else:
                state["state"] = "failed"
                state["reason"] = "One of the managed services exited"
                _write_atomic(STATE, state)
        except Exception as exc:
            state["state"] = "failed"
            # Error details are static/local; avoid leaking system credentials.
            state["reason"] = str(exc)
            _write_atomic(STATE, state)
        finally:
            _stop_children(children)
            if _read(STATE).get("token") == token:
                state["state"] = "stopped" if state["state"] == "running" else state["state"]
                _write_atomic(STATE, state)
            if _read(STOP).get("token") == token:
                STOP.unlink(missing_ok=True)
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def status() -> dict:
    state = _read(STATE)
    owner = _active(state)
    if not owner:
        return {"state": "failed" if state.get("state") == "failed" else "stopped",
                "reason": state.get("reason", "No active supervisor")}
    return {
        "state": state.get("state", "unknown"),
        "pid": owner.pid,
        "services": state.get("services", {}),
        "reason": state.get("reason"),
    }


def start() -> int:
    if not _require_development():
        return 2
    if os.name != "nt":
        print("The detached development supervisor currently supports Windows only.")
        return 2
    previous = status()
    if previous["state"] in ("starting", "running"):
        print("Purr already managed:", previous)
        return 0
    if not config_path().exists():
        print("Missing .env. Run .\\setup-local.ps1 first.")
        return 2
    # Reject occupied ports before detaching; never attach to foreign services.
    try:
        configured = _config()
    except (ValueError, TypeError) as exc:
        print(str(exc))
        return 2
    for name, _, host, port in configured:
        if _port_busy(host, port):
            print(f"Cannot start: {name} port {port} is occupied by another service.")
            return 2
    RUN.mkdir(exist_ok=True)
    with LOG.open("ab") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "purrfect.dev.supervisor", "serve"],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
    deadline = time.monotonic() + 22
    while time.monotonic() < deadline:
        state = status()
        if state.get("pid") != process.pid:
            if process.poll() is not None:
                print("Supervisor exited during startup. Inspect .purrfect/supervisor.log.")
                return 1
            time.sleep(0.2)
            continue
        if state["state"] == "running":
            print("Purr running in background:", state["services"])
            return 0
        if state["state"] == "failed":
            print("Startup failed:", state.get("reason"))
            return 1
        if process.poll() is not None:
            print("Supervisor exited during startup. Inspect .purrfect/supervisor.log.")
            return 1
        time.sleep(0.2)
    print("Startup timed out. Inspect .purrfect/supervisor.log.")
    return 1


def stop() -> int:
    info = _read(STATE)
    proc = _active(info)
    if proc is None:
        print("Purr is not running.")
        return 0
    _write_atomic(STOP, {"token": info["token"], "action": "stop"})
    try:
        proc.wait(timeout=12)
    except psutil.TimeoutExpired:
        print("Graceful shutdown timed out; supervisor still active. Check logs.")
        return 1
    print("Purr services stopped.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage local Purr Gateway + Console")
    parser.add_argument("command", choices=["init", "start", "stop", "status", "restart", "serve"])
    args = parser.parse_args()
    if args.command == "init":
        return init()
    if not _require_development():
        return 2
    if args.command == "serve":
        if os.name != "nt":
            return 2
        _serve()
        return 0
    if args.command == "status":
        print(json.dumps(status(), indent=2))
        return 0
    if args.command == "stop":
        return stop()
    if args.command == "restart":
        if stop() != 0:
            return 1
    return start()


if __name__ == "__main__":
    raise SystemExit(main())
