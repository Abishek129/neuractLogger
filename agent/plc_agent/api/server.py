import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

_USE_UVICORN = os.environ.get("AGENT_USE_UVICORN", "1") not in ("0", "false", "False")

class _Handler(BaseHTTPRequestHandler):
    server_version = "PLCLoggerAgent/0.1"

    def _cors_origin(self) -> str:
        return os.environ.get("CORS_ORIGIN") or "http://127.0.0.1:5173"

    def _set_json(self, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        # CORS headers for fallback server
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Headers", "*, x-agent-token, authorization, content-type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.end_headers()

    def log_message(self, fmt, *args):
        return

    def _is_authorized(self) -> bool:
        token = os.environ.get("AGENT_TOKEN")
        if not token:
            return True
        hdr = self.headers.get("x-agent-token") or self.headers.get("authorization")
        if not hdr:
            return False
        if hdr.lower().startswith("bearer "):
            hdr = hdr.split(" ", 1)[1]
        return hdr == token

    def do_OPTIONS(self):
        # Preflight CORS
        self._set_json(204)
        try:
            self.wfile.write(b"{}")
        except Exception:
            pass

    def do_GET(self):
        path = urlparse(self.path).path
        # Unauthenticated endpoints
        if path == "/auth/handshake":
            tok = os.environ.get("AGENT_TOKEN") or ""
            port = int(os.environ.get("AGENT_PORT", "0") or 0)
            self._set_json(200)
            self.wfile.write(json.dumps({"token": tok, "port": port}).encode("utf-8"))
            return
        if path == "/health":
            body = {
                "status": "ok",
                "agent": "plc-agent",
                "version": "0.1.0",
            }
            self._set_json(200)
            self.wfile.write(json.dumps(body).encode("utf-8"))
            return
        # Authenticated paths follow
        if not self._is_authorized():
            self._set_json(401)
            self.wfile.write(json.dumps({"success": False, "error": "PERMISSION_DENIED", "message": "Missing or invalid token"}).encode("utf-8"))
            return
        try:
            if path == "/devices":
                from .store import Store
                from .appdb import init as _init
                _init(); Store.instance().load_from_app_db()
                items = Store.instance().list_devices()
                self._set_json(200)
                self.wfile.write(json.dumps({"items": items}).encode("utf-8"))
                return
            if path == "/storage/targets":
                from .appdb import load_targets as _load
                tgs, default_id = _load()
                self._set_json(200)
                self.wfile.write(json.dumps({"items": tgs, "defaultId": default_id}).encode("utf-8"))
                return
            if path == "/networking/gateways":
                from .store import Store
                from .appdb import init as _init
                _init(); Store.instance().load_from_app_db()
                items = Store.instance().list_gateways()
                self._set_json(200)
                self.wfile.write(json.dumps({"items": items}).encode("utf-8"))
                return
            if path == "/schemas":
                from .store import Store
                from .appdb import init as _init
                _init(); Store.instance().load_from_app_db()
                items = Store.instance().list_schemas()
                self._set_json(200)
                self.wfile.write(json.dumps({"items": items}).encode("utf-8"))
                return
            if path == "/jobs":
                from .store import Store
                from .appdb import init as _init
                _init(); Store.instance().load_from_app_db()
                items = Store.instance().list_jobs()
            if path == "/system/summary":
                try:
                    from .store import Store
                    from .appdb import init as _init
                    _init(); Store.instance().load_from_app_db()
                    st = Store.instance()
                    devs = st.list_devices()
                    connected = sum(1 for d in devs if (d.get("status") or "").lower() in ("connected","degraded"))
                    default_id = st.get_default_db_target()
                    default_ok = False
                    if default_id:
                        t = st.get_db_target(default_id)
                        default_ok = bool(t and (t.get("status") == "ok"))
                    jobs = st.list_jobs()
                    running = sum(1 for j in jobs if (j.get("status") or "").lower() == "running")
                    self._set_json(200)
                    self.wfile.write(json.dumps({"ok": True, "devicesConnected": connected, "defaultDbOk": default_ok, "jobsRunning": running}).encode("utf-8"))
                    return
                except Exception as e:
                    self._set_json(500)
                    self.wfile.write(json.dumps({"error":"internal_error","message":str(e)}).encode("utf-8"))
                    return
                self._set_json(200)
                self.wfile.write(json.dumps({"items": items}).encode("utf-8"))
                return
        except Exception as e:
            self._set_json(500)
            self.wfile.write(json.dumps({"error": "internal_error", "message": str(e)}).encode("utf-8"))
            return
        self._set_json(404)
        self.wfile.write(json.dumps({"error": "not_found"}).encode("utf-8"))

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(body.decode('utf-8') or '{}')
            except Exception:
                payload = {}
            if path == "/auth/handshake":
                tok = os.environ.get("AGENT_TOKEN") or ""
                port = int(os.environ.get("AGENT_PORT", "0") or 0)
                self._set_json(200)
                self.wfile.write(json.dumps({"token": tok, "port": port}).encode("utf-8"))
                return
            # Auth required beyond this point
            if not self._is_authorized():
                self._set_json(401)
                self.wfile.write(json.dumps({"success": False, "error": "PERMISSION_DENIED", "message": "Missing or invalid token"}).encode("utf-8"))
                return
            if path == "/networking/ping":
                t0 = time.perf_counter(); time.sleep(0.05)
                dt = int((time.perf_counter() - t0) * 1000)
                out = {"ok": False, "lossPct": 100, "min": 0, "avg": 0, "max": 0, "samples": [], "timeMs": dt}
                self._set_json(200)
                self.wfile.write(json.dumps(out).encode("utf-8"))
                return
            if path == "/networking/tcp_test":
                out = {"status": "timeout", "timeMs": 0}
                self._set_json(200)
                self.wfile.write(json.dumps(out).encode("utf-8"))
                return
        except Exception as e:
            self._set_json(500)
            self.wfile.write(json.dumps({"error": "internal_error", "message": str(e)}).encode("utf-8"))
            return
        self._set_json(404)
        self.wfile.write(json.dumps({"error": "not_found"}).encode("utf-8"))

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

