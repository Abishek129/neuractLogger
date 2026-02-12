import copy
import json
import logging
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

_USE_UVICORN = os.environ.get("AGENT_USE_UVICORN", "1") not in ("0", "false", "False")

class _Handler(BaseHTTPRequestHandler):
    server_version = "NeuractLoggerAgent/0.1"

    def _cors_origin(self) -> str:
        return os.environ.get("CORS_ORIGIN") or "http://127.0.0.1:5173"

    def _set_json(self, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        # CORS headers for fallback server
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Headers", "*, authorization, content-type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.end_headers()

    def log_message(self, fmt, *args):
        return

    def do_OPTIONS(self):
        self._set_json(204)
        try:
            self.wfile.write(b"{}")
        except Exception:
            pass

    def _service_unavailable(self):
        """Fallback server cannot validate JWT tokens. Return 503 for protected endpoints."""
        self._set_json(503)
        self.wfile.write(json.dumps({
            "success": False,
            "error": "SERVICE_UNAVAILABLE",
            "message": "Fallback server active. JWT auth requires the full uvicorn server.",
        }).encode("utf-8"))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            body = {"status": "ok", "agent": "plc-agent", "version": "0.1.0"}
            self._set_json(200)
            self.wfile.write(json.dumps(body).encode("utf-8"))
            return
        if path == "/version":
            self._set_json(200)
            self.wfile.write(json.dumps({"version": "0.1.0"}).encode("utf-8"))
            return
        self._service_unavailable()

    def do_POST(self):
        self._service_unavailable()



def _uvicorn_log_config():
    try:
        from uvicorn.config import LOGGING_CONFIG as UVICORN_LOGGING_CONFIG
    except Exception:
        return None
    cfg = copy.deepcopy(UVICORN_LOGGING_CONFIG)
    formatters = cfg.setdefault("formatters", {})
    formatters["default"] = {
        "()": "logging.Formatter",
        "fmt": "%(asctime)s [%(levelname)s] %(message)s",
        "datefmt": "%Y-%m-%d %H:%M:%S",
    }
    formatters["access"] = {
        "()": "logging.Formatter",
        "fmt": "%(asctime)s [ACCESS] %(message)s",
        "datefmt": "%Y-%m-%d %H:%M:%S",
    }
    return cfg


def run(host: str = "127.0.0.1", port: int = 5175):
    if _USE_UVICORN:
        try:
            import uvicorn  # type: ignore
            from .app import app
            print(f"Starting uvicorn server at http://{host}:{port}")
            log_config = _uvicorn_log_config()
            run_kwargs = {"host": host, "port": port, "log_level": os.environ.get("UVICORN_LOG", "info")}
            if log_config is not None:
                run_kwargs["log_config"] = log_config
            uvicorn.run(app, **run_kwargs)

            return
        except ImportError as e:
            print("??? Uvicorn or FastAPI not installed:", e)
        except Exception as e:
            print("??? Error starting uvicorn:", e)
            raise  # ??? Re-raise unless fallback is really wanted
    httpd = HTTPServer((host, port), _Handler)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


if __name__ == "__main__":
    p = int(os.environ.get("AGENT_PORT", "5175"))
    run(port=p)






