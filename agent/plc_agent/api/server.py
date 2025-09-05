import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

_USE_UVICORN = os.environ.get("AGENT_USE_UVICORN", "1") not in ("0", "false", "False")

class _Handler(BaseHTTPRequestHandler):
    server_version = "PLCLoggerAgent/0.1"

    def _set_json(self, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header(" ", "no-store")
        self.end_headers()

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            body = {
                "status": "ok",
                "agent": "plc-agent",
                "version": "0.1.0",
            }
            self._set_json(200)
            self.wfile.write(json.dumps(body).encode("utf-8"))
            return
        if path == "/schemas":
            self._set_json(200)
            self.wfile.write(json.dumps({"items": []}).encode("utf-8"))
            return
        if path == "/jobs":
            self._set_json(200)
            self.wfile.write(json.dumps({"items": []}).encode("utf-8"))
            return
        self._set_json(404)
        self.wfile.write(json.dumps({"error": "not_found"}).encode("utf-8"))

    def do_POST(self):
        self._set_json(501)
        self.wfile.write(json.dumps({"error": "not_implemented"}).encode("utf-8"))

def run(host: str = "127.0.0.1", port: int = 5175):
    if _USE_UVICORN:
        try:
            import uvicorn  # type: ignore
            from .app import app
            print(f"Starting uvicorn server at http://{host}:{port}")
            uvicorn.run(app, host=host, port=port, log_level=os.environ.get("UVICORN_LOG", "info"))
            return
        except ImportError as e:
            print("❌ Uvicorn or FastAPI not installed:", e)
        except Exception as e:
            print("❌ Error starting uvicorn:", e)
            raise  # ✅ Re-raise unless fallback is really wanted
    httpd = HTTPServer((host, port), _Handler)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


if __name__ == "__main__":
    p = int(os.environ.get("AGENT_PORT", "5175"))
    run(port=p)
