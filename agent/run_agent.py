import os
import json
import socket
import sys
from pathlib import Path
from plc_agent.api.server import run


def _choose_port(preferred: int, host: str = "127.0.0.1") -> int:
    # Try preferred; optionally fail-fast if busy, else fall back to free port
    strict = os.environ.get("AGENT_STRICT_PORT", "0").lower() not in ("0", "false")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, preferred))
            return preferred
        except Exception:
            if strict:
                print(f"Port {preferred} busy and strict mode enabled", file=sys.stderr)
                sys.exit(97)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _write_lockfile(port: int, token: str) -> None:
    pid = os.getpid()
    data = {"pid": pid, "port": port, "token": token}
    # Prefer ProgramData (service path), then fall back to user LocalAppData
    wrote_any = False
    # 1) ProgramData
    try:
        base = os.environ.get("ProgramData") or os.getcwd()
        folder = Path(base) / "PLCLogger" / "agent"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "agent.lock.json"
        path.write_text(json.dumps(data))
        print(f"Lockfile: {path}")
        wrote_any = True
    except Exception as e:
        print("Lockfile write failed (ProgramData):", e, file=sys.stderr)
    # 2) LocalAppData fallback for dev
    try:
        base_local = os.environ.get("LOCALAPPDATA")
        if base_local:
            folder = Path(base_local) / "PLCLogger" / "agent"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / "agent.lock.json"
            path.write_text(json.dumps(data))
            print(f"Lockfile (LocalAppData): {path}")
            wrote_any = True
    except Exception as e:
        print("Lockfile write failed (LocalAppData):", e, file=sys.stderr)
    # 3) CWD as a last resort (dev)
    if not wrote_any:
        try:
            path = Path.cwd() / "agent.dev.lock.json"
            path.write_text(json.dumps(data))
            print(f"Lockfile (cwd): {path}")
        except Exception as e:
            print("Lockfile write failed (cwd):", e, file=sys.stderr)


def main():
    preferred = int(os.environ.get("AGENT_PORT", "5175"))
    host = os.environ.get("AGENT_HOST", "127.0.0.1")
    # ensure token exists
    if not os.environ.get("AGENT_TOKEN"):
        import secrets
        os.environ["AGENT_TOKEN"] = secrets.token_urlsafe(24)
    port = _choose_port(preferred, host=host)
    os.environ["AGENT_PORT"] = str(port)
    _write_lockfile(port, os.environ.get("AGENT_TOKEN", ""))
    run(host=host, port=port)


if __name__ == "__main__":
    main()
