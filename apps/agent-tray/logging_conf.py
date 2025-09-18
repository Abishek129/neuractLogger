import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable


LOG_DIR_ENV = "NEURACTLOGGER_AGENT_LOG_DIR"
LEGACY_LOG_DIR_ENV = "PLCLOGGER_AGENT_LOG_DIR"

def _candidate_dirs() -> Iterable[Path]:
    seen: set[str] = set()
    for env_name in (LOG_DIR_ENV, LEGACY_LOG_DIR_ENV):
        env_dir = os.environ.get(env_name)
        if env_dir:
            p = Path(env_dir)
            key = str(p.resolve()) if p.exists() else str(p)
            if key not in seen:
                seen.add(key)
                yield p
    program_data = os.environ.get("ProgramData")
    if program_data:
        for brand in ("NeuractLogger", "PLCLogger"):
            p = Path(program_data) / brand / "agent" / "logs"
            key = str(p)
            if key not in seen:
                seen.add(key)
                yield p
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        for brand in ("NeuractLogger", "PLCLogger"):
            p = Path(local_app) / brand / "agent" / "logs"
            key = str(p)
            if key not in seen:
                seen.add(key)
                yield p
    cwd = Path.cwd() / "logs"
    key = str(cwd)
    if key not in seen:
        seen.add(key)
        yield cwd


def get_logs_dir() -> Path:
    for candidate in _candidate_dirs():
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except PermissionError:
            continue
    fallback = Path.cwd() / "logs"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def setup_logger(name: str = "agent-tray", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)

    log_path = None
    handler = None
    for candidate in _candidate_dirs():
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            log_path = candidate / "agent.log"
            handler = RotatingFileHandler(str(log_path), maxBytes=1_000_000, backupCount=5, encoding="utf-8")
            break
        except (PermissionError, OSError):
            continue

    if handler is None:
        handler = logging.StreamHandler()
        fmt = logging.Formatter(fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                                datefmt="%Y-%m-%d %H:%M:%S")
        handler.setFormatter(fmt)
        handler.setLevel(level)
        logger.addHandler(handler)
        logger.warning("Falling back to stream logging; could not open log files in any candidate directory")
        return logger

    fmt = logging.Formatter(fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(fmt)
    logger.addHandler(handler)

    if os.environ.get("PYINSTALLER_RUN") != "1":
        sh = logging.StreamHandler()
        sh.setLevel(logging.WARNING)
        sh.setFormatter(fmt)
        logger.addHandler(sh)

    if log_path:
        logger.debug("Logger initialized at %s", log_path)
    return logger



