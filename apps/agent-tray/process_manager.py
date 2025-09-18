import os
import sys
import time
import threading
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import logging_conf

logger = logging_conf.setup_logger("agent-tray.process")


@dataclass
class ProcessEvent:
    type: str
    detail: Optional[str] = None
    code: Optional[int] = None


class ProcessManager:
    def __init__(self, port: int = 5175):
        self.port = port
        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._restart_flag = False
        self._stopping = False
        self._lock = threading.RLock()
        self._callback: Optional[Callable[[ProcessEvent], None]] = None
        self._backoff = 1.0
        self._last_start: Optional[float] = None

    def on_event(self, cb: Callable[[ProcessEvent], None]):
        self._callback = cb

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def start(self) -> bool:
        with self._lock:
            if self.is_running():
                return True
            cmd = self._resolve_backend_cmd()
            env = os.environ.copy()
            env.setdefault("AGENT_PORT", str(self.port))
            env["AGENT_STRICT_PORT"] = "1"
            env.setdefault("AGENT_HOST", "127.0.0.1")
            env.setdefault("PYTHONUNBUFFERED", "1")
            creationflags = 0
            if os.name == "nt":
                creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                logger.info("Starting backend: %s", cmd)
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=env,
                    cwd=self._working_dir(),
                    creationflags=creationflags,
                    text=True,
                    bufsize=1,
                )
                self._stopping = False
                self._last_start = time.time()
                self._spawn_reader()
                self._emit(ProcessEvent("started"))
                return True
            except Exception as e:
                logger.exception("Failed to start backend: %s", e)
                self._emit(ProcessEvent("error", detail=str(e)))
                return False

    def stop(self, timeout: float = 5.0) -> bool:
        with self._lock:
            proc = self._proc
            self._stopping = True
        if not proc:
            with self._lock:
                self._stopping = False
            return True
        try:
            logger.info("Stopping backend ...")
            proc.terminate()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.warning("Backend did not exit in %.1fs, killing", timeout)
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except Exception:
                    pass
            code = proc.poll()
            self._emit(ProcessEvent("stopped", code=code))
            return True
        except Exception as e:
            logger.exception("Failed to stop backend: %s", e)
            return False
        finally:
            with self._lock:
                self._proc = None
                self._stopping = False
                self._backoff = 1.0
            try:
                if self._reader_thread and self._reader_thread.is_alive():
                    self._reader_thread.join(timeout=0.5)
            except Exception:
                pass
            self._reader_thread = None

    def restart(self):
        logger.info("Restart requested")
        self._emit(ProcessEvent("restarting"))
        self.stop()
        time.sleep(0.2)
        self._backoff = 1.0
        self.start()

    def _working_dir(self) -> Optional[str]:
        if getattr(sys, "frozen", False):
            return str(Path(sys.executable).parent)
        try:
            return str(Path(__file__).resolve().parents[2])
        except Exception:
            return None

    def _resolve_backend_cmd(self):
        candidates: list[list[str] | Path] = []
        exe_names = ["neuract-agent-core.exe", "plc-agent-core.exe"]
        exe_dir: Optional[Path] = Path(sys.executable).parent if getattr(sys, "frozen", False) else None
        if exe_dir:
            for name in exe_names:
                candidates.append(exe_dir / name)
                candidates.append(exe_dir / "agent-core" / name)
            base = getattr(sys, "_MEIPASS", None)
            if base:
                base_path = Path(base)
                for name in exe_names:
                    candidates.append(base_path / name)
                    candidates.append(base_path / "agent-core" / name)
        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "agent" / "run_agent.py"
        if script.exists():
            candidates.append(script)
        for c in candidates:
            if isinstance(c, Path) and c.suffix.lower() == ".exe" and c.exists():
                if c.is_file():
                    return [str(c)]
                nested = c / c.name
                if nested.exists():
                    return [str(nested)]
            if (
                isinstance(c, Path)
                and c.suffix.lower() == ".py"
                and c.exists()
                and not getattr(sys, "frozen", False)
            ):
                return [sys.executable, "-u", str(c)]
        if not getattr(sys, "frozen", False) and script.exists():
            return [sys.executable, "-u", str(script)]
        raise FileNotFoundError("Neuract agent core executable not found; reinstall or rebuild the bundle")

    def _spawn_reader(self):
        if not self._proc or not self._proc.stdout:
            return

        def _reader():
            assert self._proc and self._proc.stdout
            for line in self._proc.stdout:
                line = line.rstrip("\n")
                if not line:
                    continue
                logger.info("core: %s", line)
                self._emit(ProcessEvent("log_line", detail=line))
            code = self._proc.poll() if self._proc else None
            self._handle_exit(code)

        self._reader_thread = threading.Thread(target=_reader, name="agent-core-reader", daemon=True)
        self._reader_thread.start()

    def _handle_exit(self, code: Optional[int]):
        with self._lock:
            stopping = self._stopping
            self._proc = None
        logger.warning("Backend exited with code %s (stopping=%s)", code, stopping)
        if code == 97:
            self._emit(ProcessEvent("port_busy", code=code, detail=f"Port {self.port} busy"))
            with self._lock:
                self._stopping = False
            return
        self._emit(ProcessEvent("exited", code=code))
        if stopping:
            with self._lock:
                self._stopping = False
                self._backoff = 1.0
            return
        delay = min(self._backoff, 30.0)
        logger.info("Auto-restarting backend after %.1fs", delay)
        time.sleep(delay)
        with self._lock:
            self._backoff = min(self._backoff + 4.0, 30.0) if self._backoff >= 5 else self._backoff + 4.0
        self.start()

    def _emit(self, ev: ProcessEvent):
        try:
            if self._callback:
                self._callback(ev)
        except Exception:
            logger.exception("Event handler error")


